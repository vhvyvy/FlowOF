"""Build a management PDF report for an agency month."""
from __future__ import annotations

import io
import logging
import os
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.report_pdf")

# ── Font registration ─────────────────────────────────────────────────────────

def _register_fonts() -> tuple[str, str]:
    """Register DejaVuSans from matplotlib's bundled fonts.
    Returns (regular_name, bold_name) as registered in pdfmetrics.
    Falls back to Helvetica if fonts not found.
    """
    try:
        import matplotlib
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        font_dir = os.path.join(
            os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf"
        )
        reg_path  = os.path.join(font_dir, "DejaVuSans.ttf")
        bold_path = os.path.join(font_dir, "DejaVuSans-Bold.ttf")

        if os.path.exists(reg_path) and os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont("DejaVu", reg_path))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold_path))
            logger.info("report_pdf: registered DejaVuSans fonts from %s", font_dir)
            return "DejaVu", "DejaVu-Bold"
    except Exception as e:
        logger.warning("report_pdf: could not register DejaVuSans: %s", e)

    return "Helvetica", "Helvetica-Bold"


# ── KPI summary text ──────────────────────────────────────────────────────────

def _kpi_to_text(rows: list) -> str:
    if not rows:
        return "KPI данные недоступны."
    lines = ["Метрики чаттеров за месяц (топ по выручке):"]
    for r in rows[:15]:
        parts = [f"  {r.chatter}: выручка ${r.revenue:,.0f}"]
        if r.total_chats:
            parts.append(f"чатов {r.total_chats}")
        if r.rpc is not None:
            parts.append(f"RPC {r.rpc:.2f}")
        if r.ppv_open_rate is not None:
            parts.append(f"OpenRate {r.ppv_open_rate:.1f}%")
        if r.revenue_delta is not None:
            sign = "+" if r.revenue_delta >= 0 else ""
            parts.append(f"MoM {sign}{r.revenue_delta:.1f}%")
        lines.append(", ".join(parts))
    return "\n".join(lines)


# ── Main builder ──────────────────────────────────────────────────────────────

async def build_agency_report_pdf(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
    tenant_name: str = "Агентство",
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table,
        TableStyle,
    )

    from services.analytics_context import build_agency_snapshot, snapshot_to_text
    from services.kpi_service import get_chatter_kpi
    from services.llm_analyst import LLMAnalyst
    from services.report_charts import (
        chart_revenue_trend,
        chart_revenue_expenses_profit,
        chart_top_chatters,
        chart_kpi_scatter_rpc_chats,
        chart_kpi_open_rate,
        chart_kpi_biggest_movers,
    )

    FONT, FONT_BOLD = _register_fonts()
    period = f"{month:02d}/{year}"
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    period_prev = f"{pm:02d}/{py}"

    # ── 1. Data collection ────────────────────────────────────────────────────
    snapshot = await build_agency_snapshot(db, tenant_id, year, month)
    snap_txt = snapshot_to_text(snapshot)

    kpi_rows, total_rev, total_txns, avg_rpc = await get_chatter_kpi(db, tenant_id, year, month)
    kpi_txt = _kpi_to_text(kpi_rows)

    # ── 2. LLM insights ───────────────────────────────────────────────────────
    try:
        analyst  = LLMAnalyst()
        insights = await analyst.generate_report_insights(snap_txt, kpi_txt)
    except Exception as e:
        logger.warning("report_pdf: LLM insights failed: %s", e)
        insights = {
            "summary":       "AI-аналитик недоступен (нет ключа или ошибка API).",
            "diagnosis":     "",
            "priorities":    [],
            "chatter_notes": [],
        }

    # ── 3. Charts ─────────────────────────────────────────────────────────────
    def _img(png_bytes: bytes, width_cm: float = 16.0) -> Image:
        buf = io.BytesIO(png_bytes)
        img = Image(buf)
        aspect = img.imageHeight / img.imageWidth
        w = width_cm * cm
        img.drawWidth  = w
        img.drawHeight = w * aspect
        return img

    chart_rev_trend  = _img(chart_revenue_trend(snapshot.get("monthly_series") or []))
    chart_rev_exp    = _img(chart_revenue_expenses_profit(snapshot.get("monthly_series") or []))
    chart_top        = _img(chart_top_chatters(snapshot.get("top_chatters") or [], period))
    chart_scatter    = _img(chart_kpi_scatter_rpc_chats(kpi_rows, period))
    chart_open_rate  = _img(chart_kpi_open_rate(kpi_rows, period))
    chart_movers     = _img(chart_kpi_biggest_movers(kpi_rows, period, period_prev))

    # ── 4. Styles ─────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()
    BLUE    = colors.HexColor("#4f46e5")
    DARK    = colors.HexColor("#1e293b")
    GREY    = colors.HexColor("#64748b")
    GREEN   = colors.HexColor("#059669")
    RED     = colors.HexColor("#dc2626")
    BOX_BG  = colors.HexColor("#eef2ff")

    def _style(name, **kw) -> ParagraphStyle:
        defaults = dict(fontName=FONT, fontSize=10, leading=14, textColor=DARK)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    s_title     = _style("title",    fontName=FONT_BOLD, fontSize=22, leading=28, textColor=BLUE,  alignment=TA_CENTER)
    s_subtitle  = _style("subtitle", fontName=FONT,      fontSize=11, textColor=GREY,               alignment=TA_CENTER)
    s_h1        = _style("h1",       fontName=FONT_BOLD, fontSize=14, leading=20, textColor=BLUE,  spaceBefore=12)
    s_h2        = _style("h2",       fontName=FONT_BOLD, fontSize=11, leading=16, textColor=DARK,  spaceBefore=8)
    s_body      = _style("body",     fontSize=10, leading=14)
    s_caption   = _style("caption",  fontSize=8,  textColor=GREY, alignment=TA_CENTER)
    s_box       = _style("box",      fontSize=10, leading=15, leftIndent=12, rightIndent=12,
                          backColor=BOX_BG, borderColor=BLUE, borderWidth=1, borderPadding=8)
    s_bullet    = _style("bullet",   fontSize=10, leading=14, leftIndent=16, bulletIndent=8)

    # ── 5. Page template with footer ──────────────────────────────────────────
    buf = io.BytesIO()
    PAGE_W, PAGE_H = A4
    MARGIN = 2.0 * cm

    def _on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(PAGE_W / 2, 1.2 * cm, f"Стр. {doc.page}")
        canvas.drawString(MARGIN, 1.2 * cm, f"FlowOF · Отчёт {period}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=2.0 * cm,
        onFirstPage=_on_page, onLaterPages=_on_page,
    )

    # ── 6. Content ────────────────────────────────────────────────────────────
    story = []

    def hr():
        return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8)

    def spacer(h: float = 0.3):
        return Spacer(1, h * cm)

    # Title
    story.append(Paragraph(f"Отчёт агентства {tenant_name}", s_title))
    story.append(Paragraph(f"{period} · сгенерирован {datetime.now().strftime('%d.%m.%Y %H:%M')}", s_subtitle))
    story.append(spacer(0.6))
    story.append(hr())

    # ── Ключевые метрики ──────────────────────────────────────────────────────
    story.append(Paragraph("Ключевые метрики", s_h1))
    t = snapshot.get("totals", {})
    tp = snapshot.get("totals_prev", {})
    d  = snapshot.get("deltas", {})

    def _delta_str(pct) -> str:
        if pct is None: return "—"
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    metrics_data = [
        ["Показатель", f"Тек. {period}", f"Пред. {period_prev}", "Изменение"],
        ["Выручка",    f"${t.get('revenue',0):,.0f}",  f"${tp.get('revenue',0):,.0f}",  _delta_str(d.get("revenue_pct"))],
        ["Расходы",    f"${t.get('expenses',0):,.0f}", f"${tp.get('expenses',0):,.0f}", "—"],
        ["Прибыль",    f"${t.get('profit',0):,.0f}",   f"${tp.get('profit',0):,.0f}",   _delta_str(d.get("profit_pct"))],
        ["Маржа",      f"{t.get('margin_pct',0):.1f}%", f"{tp.get('margin_pct',0):.1f}%", "—"],
    ]
    tbl = Table(metrics_data, colWidths=[4*cm, 4*cm, 4*cm, 3.5*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME",    (0, 1), (-1, -1), FONT),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)
    story.append(spacer())

    # ── Главный вывод ─────────────────────────────────────────────────────────
    if insights.get("summary"):
        story.append(Paragraph("Главный вывод", s_h1))
        story.append(Paragraph(insights["summary"], s_box))
        story.append(spacer())

    story.append(hr())

    # ── Финансовые графики ────────────────────────────────────────────────────
    story.append(Paragraph("Финансовые графики", s_h1))

    story.append(chart_rev_trend)
    story.append(Paragraph("Выручка по месяцам", s_caption))
    story.append(spacer(0.4))

    story.append(chart_rev_exp)
    story.append(Paragraph("Выручка / Расходы / Прибыль", s_caption))
    story.append(spacer(0.4))

    story.append(chart_top)
    story.append(Paragraph("Топ чаттеров за месяц", s_caption))
    story.append(spacer())
    story.append(hr())

    # ── Диагноз ───────────────────────────────────────────────────────────────
    if insights.get("diagnosis"):
        story.append(Paragraph("Диагноз", s_h1))
        story.append(Paragraph(insights["diagnosis"], s_body))
        story.append(spacer())
        story.append(hr())

    # ── KPI графики ───────────────────────────────────────────────────────────
    story.append(Paragraph("KPI чаттеров", s_h1))

    story.append(chart_scatter)
    story.append(Paragraph("Объём диалогов × RPC", s_caption))
    story.append(spacer(0.4))

    story.append(chart_open_rate)
    story.append(Paragraph("PPV Open Rate (%)", s_caption))
    story.append(spacer(0.4))

    story.append(chart_movers)
    story.append(Paragraph(f"Крупнейшие изменения выручки: {period_prev} → {period}", s_caption))
    story.append(spacer())
    story.append(hr())

    # ── Приоритеты ────────────────────────────────────────────────────────────
    priorities = insights.get("priorities") or []
    if priorities:
        story.append(Paragraph("Приоритеты на следующий период", s_h1))
        for i, p in enumerate(priorities, 1):
            story.append(Paragraph(f"{i}. {p}", s_bullet))
        story.append(spacer())
        story.append(hr())

    # ── Выводы по чаттерам ────────────────────────────────────────────────────
    chatter_notes = insights.get("chatter_notes") or []
    if chatter_notes:
        story.append(Paragraph("Выводы по чаттерам", s_h1))
        cn_data = [["Чаттер", "Комментарий"]]
        for cn in chatter_notes:
            cn_data.append([cn.get("chatter", ""), cn.get("note", "")])
        cn_tbl = Table(cn_data, colWidths=[5*cm, 11*cm])
        cn_tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTNAME",    (0, 0), (-1, 0), FONT_BOLD),
            ("FONTNAME",    (0, 1), (-1, -1), FONT),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",  (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("WORDWRAP",    (1, 1), (1, -1), True),
        ]))
        story.append(cn_tbl)

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    buf.seek(0)
    return buf.read()
