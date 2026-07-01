"""Chart image endpoints for agency analytics reports."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from services.analytics_context import build_agency_snapshot

logger = logging.getLogger("flowof.reports")
router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

FINANCE_CHART_TYPES = {
    "revenue_trend",
    "revenue_expenses_profit",
    "top_chatters",
    "chatter_mom_change",
    "tx_count",
    "avg_check",
    "expenses_by_category",
}

KPI_CHART_TYPES = {
    "kpi_scatter_rpc_chats",
    "kpi_open_rate",
    "kpi_top_revenue",
    "kpi_biggest_movers",
}

ALL_CHART_TYPES = FINANCE_CHART_TYPES | KPI_CHART_TYPES


@router.get("/chart/{chart_type}")
async def get_chart(
    chart_type: str,
    year: int  = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if chart_type not in ALL_CHART_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный тип графика. Доступные: {', '.join(sorted(ALL_CHART_TYPES))}",
        )

    try:
        # ── KPI charts ────────────────────────────────────────────────────────
        if chart_type in KPI_CHART_TYPES:
            from services.kpi_service import get_chatter_kpi
            from services.report_charts import (
                chart_kpi_scatter_rpc_chats,
                chart_kpi_open_rate,
                chart_kpi_top_revenue,
                chart_kpi_biggest_movers,
            )

            rows, _total_rev, _total_txns, _avg_rpc = await get_chatter_kpi(
                db, tenant.id, year, month
            )
            period      = f"{month:02d}/{year}"
            py, pm      = (year - 1, 12) if month == 1 else (year, month - 1)
            period_prev = f"{pm:02d}/{py}"

            if chart_type == "kpi_scatter_rpc_chats":
                png = chart_kpi_scatter_rpc_chats(rows, period)
            elif chart_type == "kpi_open_rate":
                png = chart_kpi_open_rate(rows, period)
            elif chart_type == "kpi_top_revenue":
                png = chart_kpi_top_revenue(rows, period)
            elif chart_type == "kpi_biggest_movers":
                png = chart_kpi_biggest_movers(rows, period, period_prev)
            else:
                raise HTTPException(status_code=400, detail="Неизвестный тип графика")

            return Response(content=png, media_type="image/png")

        # ── Finance charts ────────────────────────────────────────────────────
        from services.report_charts import (
            chart_revenue_trend,
            chart_revenue_expenses_profit,
            chart_top_chatters,
            chart_chatter_mom_change,
            chart_tx_count,
            chart_avg_check,
            chart_expenses_by_category,
        )

        snapshot    = await build_agency_snapshot(db, tenant.id, year, month)
        period      = snapshot.get("period", "")
        period_prev = snapshot.get("period_prev", "")

        if chart_type == "revenue_trend":
            png = chart_revenue_trend(snapshot.get("monthly_series") or [])

        elif chart_type == "revenue_expenses_profit":
            png = chart_revenue_expenses_profit(snapshot.get("monthly_series") or [])

        elif chart_type == "top_chatters":
            png = chart_top_chatters(snapshot.get("top_chatters") or [], period)

        elif chart_type == "chatter_mom_change":
            detail      = snapshot.get("monthly_detail") or []
            ym_cur      = f"{year}-{month:02d}"
            py, pm      = (year - 1, 12) if month == 1 else (year, month - 1)
            ym_prev     = f"{py}-{pm:02d}"
            cur_detail  = next((d for d in detail if d["month"] == ym_cur),  {})
            prev_detail = next((d for d in detail if d["month"] == ym_prev), {})
            png = chart_chatter_mom_change(
                cur_detail.get("top_chatters") or snapshot.get("top_chatters") or [],
                prev_detail.get("top_chatters") or [],
                period,
                period_prev,
            )

        elif chart_type == "tx_count":
            detail     = snapshot.get("monthly_detail") or []
            detail_map = {d["month"]: d for d in detail}
            series_with_count = []
            for row in snapshot.get("monthly_series") or []:
                d        = detail_map.get(row["month"])
                tx_total = sum(c.get("tx_count", 0) for c in (d.get("top_chatters") or [])) if d else 0
                series_with_count.append({**row, "tx_count": tx_total})
            png = chart_tx_count(series_with_count)

        elif chart_type == "avg_check":
            png = chart_avg_check(snapshot.get("monthly_detail") or [])

        elif chart_type == "expenses_by_category":
            png = chart_expenses_by_category(snapshot.get("expenses_by_category") or [], period)

        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип графика")

        return Response(content=png, media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("chart error tenant=%d type=%s: %s", tenant.id, chart_type, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка генерации графика: {e}")


@router.get("/pdf")
async def get_pdf_report(
    year: int  = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a full management PDF report for the given month."""
    try:
        from services.report_pdf import build_agency_report_pdf

        pdf_bytes = await build_agency_report_pdf(
            db, tenant.id, year, month, tenant_name=tenant.name or "Агентство"
        )
        filename = f"report_{year}_{month:02d}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.error("pdf report error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка генерации PDF: {e}")
