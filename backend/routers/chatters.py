import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Plan, AppSetting

RETENTION_RATE = 0.025  # 2.5% удерживается агентством при use_retention=1
from schemas import ChattersResponse, ChatterRow, ChatterModelBreakdown

logger = logging.getLogger("skynet.chatters")
router = APIRouter(prefix="/api/v1", tags=["chatters"])


PLAN_TIERS = [
    (1.00, 0.25),  # ≥100% → 25%
    (0.90, 0.24),  # ≥90%  → 24%
    (0.80, 0.23),  # ≥80%  → 23%
    (0.70, 0.22),  # ≥70%  → 22%
    (0.60, 0.21),  # ≥60%  → 21%
    (0.00, 0.20),  # <60%  → 20% (минимум)
]

DEFAULT_TIER = 0.25  # нет плана → 25%


def _tier_pct(completion: float) -> float:
    """Return payout fraction for a model. Minimum is always 20% (0.20)."""
    for threshold, pct in PLAN_TIERS:
        if completion >= threshold:
            return pct
    return 0.20  # absolute floor


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

        # Plans for this period
        # Fetch use_retention setting
        setting_result = await db.execute(
            select(AppSetting.value).where(
                and_(AppSetting.tenant_id == tenant.id, AppSetting.key == "use_retention")
            )
        )
        setting_row = setting_result.scalar()
        use_retention = (setting_row or "1") == "1"

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

        # Revenue by model → compute tier per model
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

        # Tier per model based on its own plan completion
        # No plan or plan_amount=0 → DEFAULT_TIER (25%)
        model_tier: dict[str, float] = {}
        for model, plan_amount in plan_rows.items():
            if plan_amount > 0:
                completion = model_revenue.get(model, 0) / plan_amount
                model_tier[model] = _tier_pct(completion)
            else:
                model_tier[model] = DEFAULT_TIER

        # Revenue by chatter AND model to apply per-model tier
        chatter_model_result = await db.execute(
            select(
                Transaction.chatter,
                Transaction.model,
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
            .group_by(Transaction.chatter, Transaction.model)
        )
        chatter_model_rows = chatter_model_result.all()

        # Aggregate per chatter: sum revenue and payout across models
        # Models not in plan_rows → DEFAULT_TIER (25%)
        # Hard floor: no model tier can be below 20%
        chatter_data: dict[str, dict] = {}
        for r in chatter_model_rows:
            name = r.chatter or "Unknown"
            rev = float(r.revenue or 0)
            txns = int(r.txn_count or 0)
            tier = max(0.20, model_tier.get(r.model, DEFAULT_TIER))
            cut = rev * tier
            plan_amt = plan_rows.get(r.model, 0.0)
            plan_comp = (model_revenue.get(r.model, 0) / plan_amt * 100) if plan_amt > 0 else 0.0

            retention = cut * RETENTION_RATE if use_retention else 0.0
            net_cut = cut - retention

            breakdown_entry = ChatterModelBreakdown(
                model=r.model or "Unknown",
                revenue=round(rev, 2),
                tier_pct=round(tier * 100, 1),
                cut=round(cut, 2),
                retention=round(retention, 2),
                net_cut=round(net_cut, 2),
                plan_amount=round(plan_amt, 2),
                plan_completion=round(plan_comp, 1),
            )

            if name not in chatter_data:
                chatter_data[name] = {"revenue": 0.0, "txn_count": 0, "chatter_cut": 0.0, "models": []}
            chatter_data[name]["revenue"] += rev
            chatter_data[name]["txn_count"] += txns
            chatter_data[name]["chatter_cut"] += net_cut  # net after retention
            chatter_data[name]["models"].append(breakdown_entry)

        total_revenue = sum(d["revenue"] for d in chatter_data.values())

        # Build response rows sorted by revenue desc
        rows: list[ChatterRow] = []
        for name, d in sorted(chatter_data.items(), key=lambda x: -x[1]["revenue"]):
            rev = d["revenue"]
            txns = d["txn_count"]
            cut = d["chatter_cut"]
            rpc = round(rev / txns, 2) if txns > 0 else 0.0
            # Effective % = actual payout / revenue (blended across models)
            # If cut ended up at 0 (old data / no tier), recalculate with floor
            if cut <= 0 and rev > 0:
                cut = rev * DEFAULT_TIER
            effective_pct = round(cut / rev * 100, 1) if rev > 0 else 0.0

            if rev >= total_revenue * 0.20:
                status = "top"
            elif rpc >= 5.0:
                status = "ok"
            elif txns < 10:
                status = "risk"
            else:
                status = "miss"

            model_breakdown = sorted(
                chatter_data[name]["models"],
                key=lambda m: -m.revenue,
            )

            rows.append(
                ChatterRow(
                    name=name,
                    revenue=round(rev, 2),
                    transactions=txns,
                    rpc=rpc,
                    chatter_pct=effective_pct,
                    chatter_cut=round(cut, 2),
                    status=status,
                    models=model_breakdown,
                )
            )

        # Overall weighted completion for display
        nonzero_plans = {m: pa for m, pa in plan_rows.items() if pa > 0}
        total_plan = sum(nonzero_plans.values())
        if total_plan > 0:
            achieved = sum(model_revenue.get(m, 0) for m in nonzero_plans)
            weighted = achieved / total_plan
        else:
            weighted = 0.0

        return ChattersResponse(
            chatters=rows,
            total_revenue=round(total_revenue, 2),
            plan_completion=round(weighted * 100, 1),
        )

    except Exception as e:
        logger.error("chatters error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
