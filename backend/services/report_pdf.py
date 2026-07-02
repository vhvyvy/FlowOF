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
    def _img(png_bytes: bytes, width_cm: float = 17.0) -> Image:
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
    # A4 usable width = 21cm - 2*2cm margins = 17cm
    CONTENT_W = 17.0 * cm

    BLUE    = colors.HexColor("#4f46e5")
    DARK    = colors.HexColor("#1e293b")
    GREY    = colors.HexColor("#64748b")
    BOX_BG  = colors.HexColor("#eef2ff")

    def _style(name, **kw) -> ParagraphStyle:
        defaults = dict(fontName=FONT, fontSize=10, leading=14, textColor=DARK)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    s_title    = _style("title",   fontName=FONT_BOLD, fontSize=22, leading=28, textColor=BLUE,
                         alignment=TA_CENTER, spaceAfter=4)
    s_subtitle = _style("subtitle",fontName=FONT, fontSize=11, textColor=GREY,
                         alignment=TA_CENTER, spaceAfter=8)
    # Section headings: generous spaceBefore so they never sit right on previous content
    s_h1       = _style("h1",      fontName=FONT_BOLD, fontSize=14, leading=20, textColor=BLUE,
                         spaceBefore=18, spaceAfter=10)
    s_body     = _style("body",    fontSize=10, leading=15, spaceAfter=4)
    s_box      = _style("box",     fontSize=10, leading=15, leftIndent=12, rightIndent=12,
                         backColor=BOX_BG, borderColor=BLUE, borderWidth=1, borderPadding=8,
                         spaceAfter=6)
    s_bullet   = _style("bullet",  fontSize=10, leading=15, leftIndent=20, bulletIndent=8,
                         spaceAfter=3)
    # Cell style for tables — wraps text, uses DejaVu so Cyrillic renders
    s_cell     = _style("cell",    fontSize=9,  leading=13)
    s_cell_hdr = _style("cell_hdr",fontName=FONT_BOLD, fontSize=9, leading=13,
                         textColor=colors.white)

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
    story: list = []

    def hr():
        return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"),
                          spaceBefore=6, spaceAfter=6)

    def spacer(h: float = 0.4):
        return Spacer(1, h * cm)

    # ── Title ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(f"Отчёт агентства {tenant_name}", s_title))
    story.append(Paragraph(
        f"{period} · сгенерирован {datetime.now().strftime('%d.%m.%Y %H:%M')}", s_subtitle
    ))
    story.append(hr())

    # ── Ключевые метрики ──────────────────────────────────────────────────────
    story.append(Paragraph("Ключевые метрики", s_h1))
    t  = snapshot.get("totals", {})
    tp = snapshot.get("totals_prev", {})
    d  = snapshot.get("deltas", {})

    def _delta_str(pct) -> str:
        if pct is None:
            return "—"
        sign = "+" if pct >= 0 else ""
        return f"{sign}{pct:.1f}%"

    # Wrap every header cell in Paragraph so DejaVu renders Cyrillic correctly
    COL_W = [5 * cm, 4 * cm, 4 * cm, 4 * cm]  # total = 17 cm = full content width

    def _hdr(txt: str):
        return Paragraph(txt, s_cell_hdr)

    def _cell(txt: str):
        return Paragraph(txt, s_cell)

    metrics_data = [
        [_hdr("Показатель"), _hdr(f"Тек. {period}"), _hdr(f"Пред. {period_prev}"), _hdr("Изменение")],
        [_cell("Выручка"),   _cell(f"${t.get('revenue',0):,.0f}"),   _cell(f"${tp.get('revenue',0):,.0f}"),   _cell(_delta_str(d.get("revenue_pct")))],
        [_cell("Расходы"),   _cell(f"${t.get('expenses',0):,.0f}"),  _cell(f"${tp.get('expenses',0):,.0f}"),  _cell("—")],
        [_cell("Прибыль"),   _cell(f"${t.get('profit',0):,.0f}"),    _cell(f"${tp.get('profit',0):,.0f}"),    _cell(_delta_str(d.get("profit_pct")))],
        [_cell("Маржа"),     _cell(f"{t.get('margin_pct',0):.1f}%"), _cell(f"{tp.get('margin_pct',0):.1f}%"), _cell("—")],
    ]
    metrics_tbl = Table(metrics_data, colWidths=COL_W)
    metrics_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("ALIGN",         (1, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(metrics_tbl)
    story.append(spacer(0.5))
    story.append(hr())

    # ── Главный вывод ─────────────────────────────────────────────────────────
    if insights.get("summary"):
        story.append(Paragraph("Главный вывод", s_h1))
        story.append(Paragraph(insights["summary"], s_box))
        story.append(spacer(0.3))
        story.append(hr())

    # ── Финансовые графики ────────────────────────────────────────────────────
    # Chart titles are already embedded by matplotlib — no duplicate caption here.
    story.append(Paragraph("Финансовые графики", s_h1))
    story.append(chart_rev_trend)
    story.append(spacer(0.5))
    story.append(chart_rev_exp)
    story.append(spacer(0.5))
    story.append(chart_top)
    story.append(spacer(0.3))
    story.append(hr())

    # ── Диагноз ───────────────────────────────────────────────────────────────
    if insights.get("diagnosis"):
        story.append(Paragraph("Диагноз", s_h1))
        story.append(Paragraph(insights["diagnosis"], s_body))
        story.append(spacer(0.3))
        story.append(hr())

    # ── KPI графики ───────────────────────────────────────────────────────────
    story.append(Paragraph("KPI чаттеров", s_h1))
    story.append(chart_scatter)
    story.append(spacer(0.5))
    story.append(chart_open_rate)
    story.append(spacer(0.5))
    story.append(chart_movers)
    story.append(spacer(0.3))
    story.append(hr())

    # ── Приоритеты ────────────────────────────────────────────────────────────
    priorities = insights.get("priorities") or []
    if priorities:
        story.append(Paragraph("Приоритеты на следующий период", s_h1))
        for i, p in enumerate(priorities, 1):
            story.append(Paragraph(f"{i}.\u2002{p}", s_bullet))
        story.append(spacer(0.3))
        story.append(hr())

    # ── Выводы по чаттерам ────────────────────────────────────────────────────
    # Wrap every cell in Paragraph(s_cell) so text wraps and uses DejaVu (Cyrillic).
    # Column widths: Чаттер 4.5 cm + Комментарий 12.5 cm = 17 cm (full content width).
    chatter_notes = insights.get("chatter_notes") or []
    if chatter_notes:
        story.append(Paragraph("Выводы по чаттерам", s_h1))
        CN_COLS = [4.5 * cm, 12.5 * cm]
        cn_data = [
            [Paragraph("Чаттер", s_cell_hdr), Paragraph("Комментарий", s_cell_hdr)],
        ]
        for cn in chatter_notes:
            cn_data.append([
                Paragraph(str(cn.get("chatter") or ""), s_cell),
                Paragraph(str(cn.get("note") or ""),    s_cell),
            ])
        cn_tbl = Table(cn_data, colWidths=CN_COLS)
        cn_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), DARK),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]))
        story.append(cn_tbl)
        story.append(spacer(0.3))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    buf.seek(0)
    return buf.read()
