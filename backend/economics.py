"""
Shared economic model helpers.
All percentage-based cost calculations derived from app_settings_mt.
Chatter payout uses per-model tier based on plan completion.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from models import AppSetting, Transaction, Plan

# ── Tier table (matches chatters.py) ──────────────────────────────────────────

PLAN_TIERS = [
    (1.00, 0.25),
    (0.90, 0.24),
    (0.80, 0.23),
    (0.70, 0.22),
    (0.60, 0.21),
    (0.00, 0.20),  # floor
]
DEFAULT_TIER  = 0.25   # no plan → 25%
RETENTION_RATE = 0.025  # 2.5%

DEFAULTS: dict[str, str] = {
    "model_percent":    "23",
    "chatter_percent":  "25",
    "admin_percent":    "9",
    "withdraw_percent": "6",
    "use_withdraw":     "1",
    "use_retention":    "1",
}


def _tier_pct(completion: float) -> float:
    for threshold, pct in PLAN_TIERS:
        if completion >= threshold:
            return pct
    return 0.20


async def load_settings(db: AsyncSession, tenant_id: int) -> dict[str, str]:
    result = await db.execute(
        select(AppSetting).where(AppSetting.tenant_id == tenant_id)
    )
    rows = result.scalars().all()
    return {**DEFAULTS, **{r.key: r.value for r in rows}}


async def compute_actual_chatter_cut(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
    use_retention: bool,
) -> tuple[float, float]:
    """
    Returns (gross_chatter_cut, net_chatter_cut) using per-model plan tiers.
    Models without a plan → DEFAULT_TIER (25%).
    Floor is 20% for models with a plan.
    """
    last_day = monthrange(year, month)[1]
    start = date(year, month, 1)
    end   = date(year, month, last_day)

    # Revenue by model
    model_rev_result = await db.execute(
        select(Transaction.model, func.sum(Transaction.amount).label("rev"))
        .where(and_(Transaction.tenant_id == tenant_id, Transaction.date >= start, Transaction.date <= end))
        .group_by(Transaction.model)
    )
    model_revenue = {r.model: float(r.rev or 0) for r in model_rev_result.all()}

    # Plans
    plan_result = await db.execute(
        select(Plan.model, Plan.plan_amount).where(
            and_(Plan.tenant_id == tenant_id, Plan.year == year, Plan.month == month)
        )
    )
    plan_rows = {r.model: float(r.plan_amount or 0) for r in plan_result.all()}

    # Sum chatter cut per model
    gross = 0.0
    for model, rev in model_revenue.items():
        plan_amt = plan_rows.get(model, 0.0)
        if plan_amt > 0:
            tier = max(0.20, _tier_pct(rev / plan_amt))
        else:
            tier = DEFAULT_TIER
        gross += rev * tier

    net = gross * (1 - RETENTION_RATE) if use_retention else gross
    return round(gross, 2), round(net, 2)


def compute_economics(
    revenue: float,
    db_expenses: float,
    settings: dict[str, str],
    actual_chatter_gross: float | None = None,
    actual_chatter_net: float | None = None,
) -> dict:
    """
    Returns full economic breakdown.

    If actual_chatter_gross/net provided (from plan-based tier calc), uses those.
    Otherwise falls back to flat chatter_percent from settings.
    """
    m_pct  = float(settings.get("model_percent",    "23")) / 100
    c_pct  = float(settings.get("chatter_percent",  "25")) / 100
    a_pct  = float(settings.get("admin_percent",    "9"))  / 100
    w_pct  = float(settings.get("withdraw_percent", "6"))  / 100
    uw     = settings.get("use_withdraw",  "1") == "1"
    ur     = settings.get("use_retention", "1") == "1"

    model_cut   = revenue * m_pct
    admin_cut   = revenue * a_pct
    withdraw    = revenue * w_pct if uw else 0.0

    # Chatter cut: plan-based tiers if available, else flat setting
    if actual_chatter_gross is not None:
        chatter_gross = actual_chatter_gross
        chatter_net   = actual_chatter_net if actual_chatter_net is not None else actual_chatter_gross
    else:
        chatter_gross = revenue * c_pct
        chatter_net   = chatter_gross * (1 - RETENTION_RATE) if ur else chatter_gross

    # Retention: 2.5% of (model_cut + chatter_gross) returned to agency
    retention = (model_cut + chatter_gross) * RETENTION_RATE if ur else 0.0

    # Effective chatter % for display
    eff_chatter_pct = round(chatter_net / revenue * 100, 1) if revenue > 0 else 0.0

    total_payouts = model_cut + chatter_net + admin_cut + withdraw - retention
    total_costs   = total_payouts + db_expenses
    profit        = revenue - total_costs
    margin        = round(profit / revenue * 100, 1) if revenue > 0 else 0.0

    return {
        "model_cut":          round(model_cut, 2),
        "chatter_cut":        round(chatter_net, 2),
        "chatter_cut_gross":  round(chatter_gross, 2),
        "admin_cut":          round(admin_cut, 2),
        "withdraw":           round(withdraw, 2),
        "retention":          round(retention, 2),
        "total_payouts":      round(total_payouts, 2),
        "db_expenses":        round(db_expenses, 2),
        "total_costs":        round(total_costs, 2),
        "profit":             round(profit, 2),
        "margin":             margin,
        "model_pct":          float(settings.get("model_percent",    "23")),
        "chatter_pct":        eff_chatter_pct,   # actual effective %
        "admin_pct":          float(settings.get("admin_percent",    "9")),
        "withdraw_pct":       float(settings.get("withdraw_percent", "6")),
        "use_withdraw":       uw,
        "use_retention":      ur,
    }
