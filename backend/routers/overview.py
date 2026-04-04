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
from schemas import OverviewResponse, DailyRevenue

logger = logging.getLogger("skynet.overview")
router = APIRouter(prefix="/api/v1", tags=["overview"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


async def _monthly_revenue(db: AsyncSession, tenant_id: int, year: int, month: int) -> Decimal:
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
    return result.scalar() or Decimal(0)


async def _monthly_expenses(db: AsyncSession, tenant_id: int, year: int, month: int) -> Decimal:
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
    return result.scalar() or Decimal(0)


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Current period
        revenue = float(await _monthly_revenue(db, tenant.id, year, month))
        expenses = float(await _monthly_expenses(db, tenant.id, year, month))
        profit = revenue - expenses
        margin = round(profit / revenue * 100, 1) if revenue > 0 else 0.0

        # Previous period for deltas
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_revenue = float(await _monthly_revenue(db, tenant.id, prev_year, prev_month))
        prev_expenses = float(await _monthly_expenses(db, tenant.id, prev_year, prev_month))
        prev_profit = prev_revenue - prev_expenses

        revenue_delta = round((revenue - prev_revenue) / prev_revenue * 100, 1) if prev_revenue > 0 else 0.0
        profit_delta = round((profit - prev_profit) / abs(prev_profit) * 100, 1) if prev_profit != 0 else 0.0

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
            expenses=round(expenses, 2),
            profit=round(profit, 2),
            margin=margin,
            transactions_count=transactions_count,
            revenue_delta=revenue_delta,
            profit_delta=profit_delta,
            daily_revenue=daily_revenue,
        )

    except Exception as e:
        logger.error("overview error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
