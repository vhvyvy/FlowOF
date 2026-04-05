"""Multi-team revenue aggregation and chatter/admin splits for a month."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from economics import compute_actual_chatter_cut
from models import Transaction
from schemas import OverviewTeamSlice
from team_helpers import team_transaction_clause


def month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


async def sum_revenue(
    db: AsyncSession,
    tenant_id: int,
    start: date,
    end: date,
    team_clause,
) -> float:
    cond = [
        Transaction.tenant_id == tenant_id,
        Transaction.date >= start,
        Transaction.date <= end,
    ]
    if team_clause is not None:
        cond.append(team_clause)
    r = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(and_(*cond))
    )
    return float(r.scalar() or 0)


async def aggregate_teams(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
    settings: dict,
    teams: list,
    default_team_id: int,
    ur: bool,
) -> tuple[float, float, float, float, list[OverviewTeamSlice]]:
    start, end = month_range(year, month)
    m_pct = float(settings.get("model_percent", "23")) / 100
    w_pct = float(settings.get("withdraw_percent", "6")) / 100
    uw = settings.get("use_withdraw", "1") == "1"

    total_rev = await sum_revenue(db, tenant_id, start, end, None)

    gross_sum = 0.0
    net_sum = 0.0
    admin_sum = 0.0
    slices: list[OverviewTeamSlice] = []

    for team in teams:
        clause = team_transaction_clause(team.id, default_team_id)
        rev_t = await sum_revenue(db, tenant_id, start, end, clause)

        if team.inherit_economics:
            cap = None
            dfrac = None
        else:
            cap = float(team.chatter_max_pct) / 100 if team.chatter_max_pct else None
            dfrac = float(team.default_chatter_pct) / 100 if team.default_chatter_pct else cap

        cg, cn = await compute_actual_chatter_cut(
            db, tenant_id, year, month, ur,
            team_id=team.id,
            default_team_id=default_team_id,
            tier_cap=cap if not team.inherit_economics else None,
            default_chatter_frac=dfrac if not team.inherit_economics else None,
        )
        gross_sum += cg
        net_sum += cn

        if team.inherit_economics:
            ap = float(settings.get("admin_percent", "9")) / 100
        else:
            ap = float(team.admin_percent_total or 0) / 100
        adm = rev_t * ap
        admin_sum += adm

        mc = rev_t * m_pct
        wt = rev_t * w_pct if uw else 0
        prof = rev_t - mc - cn - adm - wt
        margin = round(prof / rev_t * 100, 1) if rev_t > 0 else 0.0
        slices.append(
            OverviewTeamSlice(
                team_id=team.id,
                name=team.name,
                revenue=round(rev_t, 2),
                chatter_cut=round(cn, 2),
                admin_cut=round(adm, 2),
                profit=round(prof, 2),
                margin=margin,
            )
        )

    return total_rev, gross_sum, net_sum, admin_sum, slices
