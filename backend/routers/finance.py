import logging
from calendar import monthrange
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense
from schemas import FinanceResponse, PnlRow, WaterfallItem

logger = logging.getLogger("skynet.finance")
router = APIRouter(prefix="/api/v1", tags=["finance"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/finance", response_model=FinanceResponse)
async def get_finance(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Total revenue
        rev_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
        )
        total_revenue = float(rev_result.scalar() or 0)

        # Revenue by model (P&L rows)
        model_rev_result = await db.execute(
            select(Transaction.model, func.sum(Transaction.amount).label("amount"))
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
            .group_by(Transaction.model)
            .order_by(func.sum(Transaction.amount).desc())
        )
        model_rows = model_rev_result.all()

        # Expenses by category
        cat_result = await db.execute(
            select(Expense.category, func.sum(Expense.amount).label("amount"))
            .where(
                and_(
                    Expense.tenant_id == tenant.id,
                    Expense.date >= start,
                    Expense.date <= end,
                )
            )
            .group_by(Expense.category)
            .order_by(func.sum(Expense.amount).desc())
        )
        cat_rows = cat_result.all()

        total_expenses = sum(float(r.amount or 0) for r in cat_rows)
        total_profit = total_revenue - total_expenses
        margin = round(total_profit / total_revenue * 100, 1) if total_revenue > 0 else 0.0

        # Previous month delta
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_start, prev_end = _month_range(prev_year, prev_month)
        prev_rev_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= prev_start,
                    Transaction.date <= prev_end,
                )
            )
        )
        prev_revenue = float(prev_rev_result.scalar() or 0)
        revenue_delta = round((total_revenue - prev_revenue) / prev_revenue * 100, 1) if prev_revenue > 0 else 0.0

        # Build P&L rows
        pnl_rows: list[PnlRow] = [
            PnlRow(label="Выручка", amount=round(total_revenue, 2), is_total=True),
        ]
        for r in model_rows:
            pnl_rows.append(PnlRow(label=f"  {r.model or 'Unknown'}", amount=round(float(r.amount or 0), 2)))
        pnl_rows.append(PnlRow(label="Расходы", amount=round(total_expenses, 2), is_total=True))
        for r in cat_rows:
            pnl_rows.append(PnlRow(label=f"  {r.category or 'Other'}", amount=round(float(r.amount or 0), 2)))
        pnl_rows.append(PnlRow(label="Прибыль", amount=round(total_profit, 2), is_total=True))

        # Waterfall: Revenue → each expense category → Profit
        waterfall: list[WaterfallItem] = [
            WaterfallItem(name="Выручка", value=round(total_revenue, 2), type="revenue")
        ]
        for r in cat_rows:
            waterfall.append(
                WaterfallItem(name=r.category or "Other", value=round(float(r.amount or 0), 2), type="expense")
            )
        waterfall.append(WaterfallItem(name="Прибыль", value=round(total_profit, 2), type="result"))

        expenses_by_category = [
            {"category": r.category or "Other", "amount": round(float(r.amount or 0), 2)}
            for r in cat_rows
        ]

        return FinanceResponse(
            total_revenue=round(total_revenue, 2),
            total_expenses=round(total_expenses, 2),
            total_profit=round(total_profit, 2),
            margin=margin,
            revenue_delta=revenue_delta,
            pnl_rows=pnl_rows,
            waterfall=waterfall,
            expenses_by_category=expenses_by_category,
        )

    except Exception as e:
        logger.error("finance error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
