"""
Shared economic model helpers.
All percentage-based cost calculations derived from app_settings_mt.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from models import AppSetting

RETENTION_RATE = 0.025  # 2.5%

DEFAULTS: dict[str, str] = {
    "model_percent":   "23",
    "chatter_percent": "25",
    "admin_percent":   "9",
    "withdraw_percent": "6",
    "use_withdraw":    "1",
    "use_retention":   "1",
}


async def load_settings(db: AsyncSession, tenant_id: int) -> dict[str, str]:
    result = await db.execute(
        select(AppSetting).where(AppSetting.tenant_id == tenant_id)
    )
    rows = result.scalars().all()
    return {**DEFAULTS, **{r.key: r.value for r in rows}}


def compute_economics(
    revenue: float,
    db_expenses: float,
    settings: dict[str, str],
) -> dict:
    """
    Returns a full economic breakdown dict.

    Costs charged against revenue (as fractions):
      model_cut      = revenue × model_percent%
      chatter_cut    = revenue × chatter_percent%
      admin_cut      = revenue × admin_percent%
      withdraw       = revenue × withdraw_percent%  (if use_withdraw)

    Retention bonus (returned to agency):
      retention      = (model_cut + chatter_cut) × 2.5%  (if use_retention)

    agency_net = revenue − model_cut − chatter_cut − admin_cut − withdraw
                 + retention − db_expenses
    """
    m_pct  = float(settings.get("model_percent",   "23")) / 100
    c_pct  = float(settings.get("chatter_percent", "25")) / 100
    a_pct  = float(settings.get("admin_percent",   "9"))  / 100
    w_pct  = float(settings.get("withdraw_percent","6"))  / 100
    uw     = settings.get("use_withdraw",  "1") == "1"
    ur     = settings.get("use_retention", "1") == "1"

    model_cut   = revenue * m_pct
    chatter_cut = revenue * c_pct
    admin_cut   = revenue * a_pct
    withdraw    = revenue * w_pct if uw else 0.0
    retention   = (model_cut + chatter_cut) * RETENTION_RATE if ur else 0.0

    total_payouts = model_cut + chatter_cut + admin_cut + withdraw - retention
    total_costs   = total_payouts + db_expenses
    profit        = revenue - total_costs
    margin        = round(profit / revenue * 100, 1) if revenue > 0 else 0.0

    return {
        "model_cut":     round(model_cut, 2),
        "chatter_cut":   round(chatter_cut, 2),
        "admin_cut":     round(admin_cut, 2),
        "withdraw":      round(withdraw, 2),
        "retention":     round(retention, 2),
        "total_payouts": round(total_payouts, 2),
        "db_expenses":   round(db_expenses, 2),
        "total_costs":   round(total_costs, 2),
        "profit":        round(profit, 2),
        "margin":        margin,
        # pct helpers for display
        "model_pct":     float(settings.get("model_percent",   "23")),
        "chatter_pct":   float(settings.get("chatter_percent", "25")),
        "admin_pct":     float(settings.get("admin_percent",   "9")),
        "withdraw_pct":  float(settings.get("withdraw_percent","6")),
        "use_withdraw":  uw,
        "use_retention": ur,
    }
