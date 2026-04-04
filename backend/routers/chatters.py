import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Plan, AppSetting
from schemas import ChattersResponse, ChatterRow

logger = logging.getLogger("skynet.chatters")
router = APIRouter(prefix="/api/v1", tags=["chatters"])


PLAN_TIERS = [
    (1.00, 0.25),  # 100%+ → 25% to chatters
    (0.85, 0.22),
    (0.70, 0.20),
    (0.50, 0.18),
    (0.00, 0.15),  # <50% → 15%
]


def _tier_pct(completion: float) -> float:
    for threshold, pct in PLAN_TIERS:
        if completion >= threshold:
            return pct
    return PLAN_TIERS[-1][1]


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/chatters", response_model=ChattersResponse)
async def get_chatters(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Revenue by chatter
        chatter_result = await db.execute(
            select(
                Transaction.chatter,
                func.sum(Transaction.amount).label("revenue"),
                func.count(Transaction.id).label("txn_count"),
            )
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                    Transaction.chatter.isnot(None),
                )
            )
            .group_by(Transaction.chatter)
            .order_by(func.sum(Transaction.amount).desc())
        )
        chatter_rows = chatter_result.all()

        # Total revenue for this period
        total_revenue = sum(float(r.revenue or 0) for r in chatter_rows)

        # Plans for this period → weighted completion
        plan_result = await db.execute(
            select(Plan.model, Plan.plan_amount).where(
                and_(
                    Plan.tenant_id == tenant.id,
                    Plan.year == year,
                    Plan.month == month,
                )
            )
        )
        plan_rows = {r.model: float(r.plan_amount or 0) for r in plan_result.all()}

        # Revenue by model for plan comparison
        model_rev_result = await db.execute(
            select(Transaction.model, func.sum(Transaction.amount).label("rev"))
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
            .group_by(Transaction.model)
        )
        model_revenue = {r.model: float(r.rev or 0) for r in model_rev_result.all()}

        # Weighted plan completion across models (skip zero-plan models)
        nonzero_plans = {m: pa for m, pa in plan_rows.items() if pa > 0}
        total_plan = sum(nonzero_plans.values())
        if total_plan > 0:
            achieved = sum(model_revenue.get(m, 0) for m in nonzero_plans)
            weighted = achieved / total_plan
        else:
            weighted = 0.0

        chatter_pct = _tier_pct(weighted)

        # Build response rows
        rows: list[ChatterRow] = []
        for r in chatter_rows:
            rev = float(r.revenue or 0)
            txns = int(r.txn_count or 0)
            rpc = round(rev / txns, 2) if txns > 0 else 0.0
            cut = round(rev * chatter_pct, 2)

            if rev >= total_revenue * 0.20:
                status = "top"
            elif rpc >= 5.0:
                status = "ok"
            elif txns < 10:
                status = "risk"
            else:
                status = "miss"

            rows.append(
                ChatterRow(
                    name=r.chatter or "Unknown",
                    revenue=round(rev, 2),
                    transactions=txns,
                    rpc=rpc,
                    chatter_pct=round(chatter_pct * 100, 1),
                    chatter_cut=cut,
                    status=status,
                )
            )

        return ChattersResponse(
            chatters=rows,
            total_revenue=round(total_revenue, 2),
            plan_completion=round(weighted * 100, 1),
        )

    except Exception as e:
        logger.error("chatters error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
