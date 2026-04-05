import logging
from datetime import date
from calendar import monthrange

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense, Team
from schemas import OverviewResponse, DailyRevenue, EconomicBreakdown, OverviewTeamSlice
from economics import load_settings, compute_economics, compute_actual_chatter_cut, safe_float_setting
from team_helpers import list_teams, ensure_default_team, team_transaction_clause, team_inherits_global_economics
from team_economics import sum_revenue, aggregate_teams

logger = logging.getLogger("flowof.overview")
router = APIRouter(prefix="/api/v1", tags=["overview"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


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
    team_id: int | None = Query(None, description="Filter metrics to one team"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)
        settings = await load_settings(db, tenant.id)
        await ensure_default_team(db, tenant.id)
        teams = await list_teams(db, tenant.id)
        default_team_id = teams[0].id

        ur = settings.get("use_retention", "1") == "1"
        db_expenses = await _monthly_db_expenses(db, tenant.id, year, month)

        selected_team: Team | None = None
        if team_id is not None:
            r = await db.execute(
                select(Team).where(and_(Team.id == team_id, Team.tenant_id == tenant.id))
            )
            selected_team = r.scalar_one_or_none()
            if selected_team is None:
                raise HTTPException(status_code=404, detail="Команда не найдена")

        teams_breakdown: list[OverviewTeamSlice] = []

        if selected_team is not None:
            clause = team_transaction_clause(selected_team.id, default_team_id)
            revenue = await sum_revenue(db, tenant.id, start, end, clause)
            revenue_full = await sum_revenue(db, tenant.id, start, end, None)
            db_exp_use = (
                db_expenses * (revenue / revenue_full) if revenue_full > 0 else 0.0
            )

            sel_inherit = team_inherits_global_economics(selected_team)
            if sel_inherit:
                cap = None
                dfrac = None
            else:
                cap = (
                    float(selected_team.chatter_max_pct) / 100
                    if selected_team.chatter_max_pct
                    else None
                )
                dfrac = (
                    float(selected_team.default_chatter_pct) / 100
                    if selected_team.default_chatter_pct
                    else cap
                )

            chatter_gross, chatter_net = await compute_actual_chatter_cut(
                db, tenant.id, year, month, ur,
                team_id=selected_team.id,
                default_team_id=default_team_id,
                tier_cap=cap if not sel_inherit else None,
                default_chatter_frac=dfrac if not sel_inherit else None,
            )
            if sel_inherit:
                ap = safe_float_setting(settings, "admin_percent", "9") / 100
            else:
                ap = float(selected_team.admin_percent_total or 0) / 100
            admin_override = revenue * ap

            eco = compute_economics(
                revenue,
                db_exp_use,
                settings,
                actual_chatter_gross=chatter_gross,
                actual_chatter_net=chatter_net,
                admin_cut_override=admin_override,
            )
        else:
            revenue, chatter_gross, chatter_net, admin_sum, teams_breakdown = await aggregate_teams(
                db, tenant.id, year, month, settings, teams, default_team_id, ur
            )
            eco = compute_economics(
                revenue,
                db_expenses,
                settings,
                actual_chatter_gross=chatter_gross,
                actual_chatter_net=chatter_net,
                admin_cut_override=admin_sum,
            )

        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_start, prev_end = _month_range(prev_year, prev_month)
        prev_db_exp = await _monthly_db_expenses(db, tenant.id, prev_year, prev_month)

        if selected_team is not None:
            p_clause = team_transaction_clause(selected_team.id, default_team_id)
            prev_rev = await sum_revenue(db, tenant.id, prev_start, prev_end, p_clause)
            prev_full = await sum_revenue(db, tenant.id, prev_start, prev_end, None)
            prev_db_use = prev_db_exp * (prev_rev / prev_full) if prev_full > 0 else 0.0
            if sel_inherit:
                p_cap = None
                p_dfrac = None
            else:
                p_cap = (
                    float(selected_team.chatter_max_pct) / 100
                    if selected_team.chatter_max_pct
                    else None
                )
                p_dfrac = (
                    float(selected_team.default_chatter_pct) / 100
                    if selected_team.default_chatter_pct
                    else p_cap
                )
            prev_cg, prev_cn = await compute_actual_chatter_cut(
                db, tenant.id, prev_year, prev_month, ur,
                team_id=selected_team.id,
                default_team_id=default_team_id,
                tier_cap=p_cap if not sel_inherit else None,
                default_chatter_frac=p_dfrac if not sel_inherit else None,
            )
            if sel_inherit:
                pap = safe_float_setting(settings, "admin_percent", "9") / 100
            else:
                pap = float(selected_team.admin_percent_total or 0) / 100
            prev_admin = prev_rev * pap
            prev_eco = compute_economics(
                prev_rev,
                prev_db_use,
                settings,
                actual_chatter_gross=prev_cg,
                actual_chatter_net=prev_cn,
                admin_cut_override=prev_admin,
            )
        else:
            _, prev_cg, prev_cn, prev_admin, _ = await aggregate_teams(
                db, tenant.id, prev_year, prev_month, settings, teams, default_team_id, ur
            )
            prev_rev = await sum_revenue(db, tenant.id, prev_start, prev_end, None)
            prev_eco = compute_economics(
                prev_rev,
                prev_db_exp,
                settings,
                actual_chatter_gross=prev_cg,
                actual_chatter_net=prev_cn,
                admin_cut_override=prev_admin,
            )

        revenue_delta = (
            round((revenue - prev_rev) / prev_rev * 100, 1) if prev_rev > 0 else 0.0
        )
        profit_delta = (
            round((eco["profit"] - prev_eco["profit"]) / abs(prev_eco["profit"]) * 100, 1)
            if prev_eco["profit"] != 0
            else 0.0
        )

        today = date.today()
        is_current_month = year == today.year and month == today.month
        revenue_forecast: float | None = None
        profit_forecast: float | None = None
        if is_current_month and revenue > 0:
            days_elapsed = today.day
            days_in_month = monthrange(year, month)[1]
            daily_rate = revenue / days_elapsed
            revenue_forecast = round(daily_rate * days_in_month, 2)
            if revenue > 0:
                profit_forecast = round(revenue_forecast * (eco["profit"] / revenue), 2)

        tx_cond = [
            Transaction.tenant_id == tenant.id,
            Transaction.date >= start,
            Transaction.date <= end,
        ]
        if selected_team is not None:
            tc = team_transaction_clause(selected_team.id, default_team_id)
            if tc is not None:
                tx_cond.append(tc)
        cnt_result = await db.execute(
            select(func.count(Transaction.id)).where(and_(*tx_cond))
        )
        transactions_count = cnt_result.scalar() or 0

        daily_cond = [
            Transaction.tenant_id == tenant.id,
            Transaction.date >= start,
            Transaction.date <= end,
        ]
        if selected_team is not None:
            dtc = team_transaction_clause(selected_team.id, default_team_id)
            if dtc is not None:
                daily_cond.append(dtc)
        daily_result = await db.execute(
            select(Transaction.date, func.sum(Transaction.amount).label("amount"))
            .where(and_(*daily_cond))
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
            is_current_month=is_current_month,
            revenue_forecast=revenue_forecast,
            profit_forecast=profit_forecast,
            teams_breakdown=teams_breakdown,
            selected_team_id=selected_team.id if selected_team else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("overview error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
