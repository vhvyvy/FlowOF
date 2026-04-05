import logging
from datetime import date
from calendar import monthrange
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense
from schemas import OverviewResponse, DailyRevenue, EconomicBreakdown
from economics import load_settings, compute_economics, compute_actual_chatter_cut

logger = logging.getLogger("skynet.overview")
router = APIRouter(prefix="/api/v1", tags=["overview"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


async def _monthly_revenue(db: AsyncSession, tenant_id: int, year: int, month: int) -> float:
    start, end = _month_range(year, month)
    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            and_(
                Transaction.tenant_id == tenant_id,
                Transaction.date >= start,
                Transaction.date <= end,
            )
        )
    )
    return float(result.scalar() or 0)


async def _monthly_db_expenses(db: AsyncSession, tenant_id: int, year: int, month: int) -> float:
    start, end = _month_range(year, month)
    result = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            and_(
                Expense.tenant_id == tenant_id,
                Expense.date >= start,
                Expense.date <= end,
            )
        )
    )
    return float(result.scalar() or 0)


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Load settings once
        settings = await load_settings(db, tenant.id)

        # Current period
        revenue     = await _monthly_revenue(db, tenant.id, year, month)
        db_expenses = await _monthly_db_expenses(db, tenant.id, year, month)
        ur = settings.get("use_retention", "1") == "1"
        chatter_gross, chatter_net = await compute_actual_chatter_cut(
            db, tenant.id, year, month, ur
        )
        eco = compute_economics(
            revenue, db_expenses, settings,
            actual_chatter_gross=chatter_gross,
            actual_chatter_net=chatter_net,
        )

        # Previous period
        prev_month  = month - 1 if month > 1 else 12
        prev_year   = year if month > 1 else year - 1
        prev_rev    = await _monthly_revenue(db, tenant.id, prev_year, prev_month)
        prev_db_exp = await _monthly_db_expenses(db, tenant.id, prev_year, prev_month)
        prev_ch_gross, prev_ch_net = await compute_actual_chatter_cut(
            db, tenant.id, prev_year, prev_month, ur
        )
        prev_eco = compute_economics(
            prev_rev, prev_db_exp, settings,
            actual_chatter_gross=prev_ch_gross,
            actual_chatter_net=prev_ch_net,
        )

        revenue_delta = round((revenue - prev_rev) / prev_rev * 100, 1) if prev_rev > 0 else 0.0
        profit_delta  = (
            round((eco["profit"] - prev_eco["profit"]) / abs(prev_eco["profit"]) * 100, 1)
            if prev_eco["profit"] != 0 else 0.0
        )

        # Transaction count
        cnt_result = await db.execute(
            select(func.count(Transaction.id)).where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
        )
        transactions_count = cnt_result.scalar() or 0

        # Daily revenue
        daily_result = await db.execute(
            select(Transaction.date, func.sum(Transaction.amount).label("amount"))
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
            .group_by(Transaction.date)
            .order_by(Transaction.date)
        )
        daily_revenue = [
            DailyRevenue(date=str(row.date), amount=float(row.amount or 0))
            for row in daily_result.all()
        ]

        return OverviewResponse(
            revenue=round(revenue, 2),
            expenses=eco["total_costs"],
            profit=eco["profit"],
            margin=eco["margin"],
            transactions_count=transactions_count,
            revenue_delta=revenue_delta,
            profit_delta=profit_delta,
            daily_revenue=daily_revenue,
            economic=EconomicBreakdown(**{k: eco[k] for k in EconomicBreakdown.model_fields}),
        )

    except Exception as e:
        logger.error("overview error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
