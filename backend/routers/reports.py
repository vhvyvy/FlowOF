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

CHART_TYPES = {
    "revenue_trend",
    "revenue_expenses_profit",
    "top_chatters",
    "chatter_mom_change",
    "tx_count",
    "avg_check",
    "expenses_by_category",
}


@router.get("/chart/{chart_type}")
async def get_chart(
    chart_type: str,
    year: int  = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if chart_type not in CHART_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный тип графика. Доступные: {', '.join(sorted(CHART_TYPES))}",
        )

    try:
        from services.report_charts import (
            chart_revenue_trend,
            chart_revenue_expenses_profit,
            chart_top_chatters,
            chart_chatter_mom_change,
            chart_tx_count,
            chart_avg_check,
            chart_expenses_by_category,
        )

        snapshot = await build_agency_snapshot(db, tenant.id, year, month)
        period      = snapshot.get("period", "")
        period_prev = snapshot.get("period_prev", "")

        if chart_type == "revenue_trend":
            png = chart_revenue_trend(snapshot.get("monthly_series") or [])

        elif chart_type == "revenue_expenses_profit":
            png = chart_revenue_expenses_profit(snapshot.get("monthly_series") or [])

        elif chart_type == "top_chatters":
            png = chart_top_chatters(snapshot.get("top_chatters") or [], period)

        elif chart_type == "chatter_mom_change":
            # Get current and prev month top chatters from monthly_detail
            detail = snapshot.get("monthly_detail") or []
            ym_cur  = f"{year}-{month:02d}"
            py, pm  = (year - 1, 12) if month == 1 else (year, month - 1)
            ym_prev = f"{py}-{pm:02d}"
            cur_detail  = next((d for d in detail if d["month"] == ym_cur),  {})
            prev_detail = next((d for d in detail if d["month"] == ym_prev), {})
            png = chart_chatter_mom_change(
                cur_detail.get("top_chatters") or snapshot.get("top_chatters") or [],
                prev_detail.get("top_chatters") or [],
                period,
                period_prev,
            )

        elif chart_type == "tx_count":
            # Build tx_count series from monthly_detail where available
            detail = snapshot.get("monthly_detail") or []
            detail_map = {d["month"]: d for d in detail}
            series_with_count = []
            for row in snapshot.get("monthly_series") or []:
                d = detail_map.get(row["month"])
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
