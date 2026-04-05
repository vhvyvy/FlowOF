import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense, Team
from schemas import FinanceResponse, PnlRow, WaterfallItem, EconomicBreakdown
from economics import load_settings, compute_economics, compute_actual_chatter_cut
from team_helpers import list_teams, ensure_default_team, team_transaction_clause
from team_economics import sum_revenue, aggregate_teams

logger = logging.getLogger("skynet.finance")
router = APIRouter(prefix="/api/v1", tags=["finance"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/finance", response_model=FinanceResponse)
async def get_finance(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    team_id: int | None = Query(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        settings = await load_settings(db, tenant.id)
        await ensure_default_team(db, tenant.id)
        teams = await list_teams(db, tenant.id)
        default_team_id = teams[0].id

        selected_team: Team | None = None
        if team_id is not None:
            tr = await db.execute(
                select(Team).where(and_(Team.id == team_id, Team.tenant_id == tenant.id))
            )
            selected_team = tr.scalar_one_or_none()
            if selected_team is None:
                raise HTTPException(status_code=404, detail="Команда не найдена")

        model_cond = [
            Transaction.tenant_id == tenant.id,
            Transaction.date >= start,
            Transaction.date <= end,
        ]
        if selected_team is not None:
            tc = team_transaction_clause(selected_team.id, default_team_id)
            if tc is not None:
                model_cond.append(tc)

        model_rev_result = await db.execute(
            select(Transaction.model, func.sum(Transaction.amount).label("amount"))
            .where(and_(*model_cond))
            .group_by(Transaction.model)
            .order_by(func.sum(Transaction.amount).desc())
        )
        model_rows = model_rev_result.all()

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
        db_expenses = sum(float(r.amount or 0) for r in cat_rows)

        ur = settings.get("use_retention", "1") == "1"

        if selected_team is not None:
            clause = team_transaction_clause(selected_team.id, default_team_id)
            total_revenue = await sum_revenue(db, tenant.id, start, end, clause)
            revenue_full = await sum_revenue(db, tenant.id, start, end, None)
            db_exp_use = (
                db_expenses * (total_revenue / revenue_full) if revenue_full > 0 else 0.0
            )
            if selected_team.inherit_economics:
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
                tier_cap=cap if not selected_team.inherit_economics else None,
                default_chatter_frac=dfrac if not selected_team.inherit_economics else None,
            )
            if selected_team.inherit_economics:
                ap = float(settings.get("admin_percent", "9")) / 100
            else:
                ap = float(selected_team.admin_percent_total or 0) / 100
            admin_override = total_revenue * ap
            eco = compute_economics(
                total_revenue,
                db_exp_use,
                settings,
                actual_chatter_gross=chatter_gross,
                actual_chatter_net=chatter_net,
                admin_cut_override=admin_override,
            )
        else:
            total_revenue, chatter_gross, chatter_net, admin_sum, _ = await aggregate_teams(
                db, tenant.id, year, month, settings, teams, default_team_id, ur
            )
            eco = compute_economics(
                total_revenue,
                db_expenses,
                settings,
                actual_chatter_gross=chatter_gross,
                actual_chatter_net=chatter_net,
                admin_cut_override=admin_sum,
            )

        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_start, prev_end = _month_range(prev_year, prev_month)

        if selected_team is not None:
            pc = team_transaction_clause(selected_team.id, default_team_id)
            prev_revenue = await sum_revenue(db, tenant.id, prev_start, prev_end, pc)
            prev_full = await sum_revenue(db, tenant.id, prev_start, prev_end, None)
        else:
            prev_revenue = await sum_revenue(db, tenant.id, prev_start, prev_end, None)
        revenue_delta = (
            round((total_revenue - prev_revenue) / prev_revenue * 100, 1)
            if prev_revenue > 0
            else 0.0
        )

        # ── Build P&L rows ────────────────────────────────────────────────────
        pnl_rows: list[PnlRow] = [
            PnlRow(label="Выручка", amount=round(total_revenue, 2), is_total=True),
        ]
        for r in model_rows:
            pnl_rows.append(PnlRow(label=f"  {r.model or 'Unknown'}", amount=round(float(r.amount or 0), 2)))

        pnl_rows.append(PnlRow(label="Выплаты (расчётные)", amount=eco["total_payouts"], is_total=True))
        pnl_rows.append(PnlRow(label=f"  Моделям ({eco['model_pct']:.0f}%)",   amount=eco["model_cut"]))
        pnl_rows.append(PnlRow(label=f"  Чаттерам ({eco['chatter_pct']:.0f}%)", amount=eco["chatter_cut"]))
        pnl_rows.append(PnlRow(label=f"  Адмнам ({eco['admin_pct']:.0f}%)",    amount=eco["admin_cut"]))
        if eco["use_withdraw"]:
            pnl_rows.append(PnlRow(label=f"  Вывод ({eco['withdraw_pct']:.0f}%)", amount=eco["withdraw"]))
        if eco["use_retention"] and eco["retention"] > 0:
            pnl_rows.append(PnlRow(label="  Ретеншн +2.5% (возврат)", amount=eco["retention"], is_positive=True))

        if db_expenses > 0:
            pnl_rows.append(PnlRow(label="Прочие расходы", amount=db_expenses, is_total=True))
            for r in cat_rows:
                pnl_rows.append(PnlRow(label=f"  {r.category or 'Other'}", amount=round(float(r.amount or 0), 2)))

        pnl_rows.append(PnlRow(label="Прибыль агентства", amount=eco["profit"], is_total=True))

        # ── Waterfall ─────────────────────────────────────────────────────────
        waterfall: list[WaterfallItem] = [
            WaterfallItem(name="Выручка",   value=round(total_revenue, 2),  type="revenue"),
            WaterfallItem(name=f"Моделям",  value=eco["model_cut"],          type="expense"),
            WaterfallItem(name="Чаттерам",  value=eco["chatter_cut"],        type="expense"),
            WaterfallItem(name="Адмнам",    value=eco["admin_cut"],          type="expense"),
        ]
        if eco["use_withdraw"]:
            waterfall.append(WaterfallItem(name="Вывод", value=eco["withdraw"], type="expense"))
        if eco["use_retention"] and eco["retention"] > 0:
            waterfall.append(WaterfallItem(name="Ретеншн", value=eco["retention"], type="retention"))
        for r in cat_rows:
            waterfall.append(
                WaterfallItem(name=r.category or "Other", value=round(float(r.amount or 0), 2), type="expense")
            )
        waterfall.append(WaterfallItem(name="Прибыль", value=eco["profit"], type="result"))

        expenses_by_category = [
            {"category": r.category or "Other", "amount": round(float(r.amount or 0), 2)}
            for r in cat_rows
        ]

        return FinanceResponse(
            total_revenue=round(total_revenue, 2),
            total_expenses=eco["total_costs"],
            total_profit=eco["profit"],
            margin=eco["margin"],
            revenue_delta=revenue_delta,
            pnl_rows=pnl_rows,
            waterfall=waterfall,
            expenses_by_category=expenses_by_category,
            economic=EconomicBreakdown(**{k: eco[k] for k in EconomicBreakdown.model_fields}),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("finance error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
