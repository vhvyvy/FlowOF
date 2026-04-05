import logging
import math
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense, Team
from schemas import FinanceResponse, PnlRow, WaterfallItem, EconomicBreakdown
from economics import load_settings, compute_economics, compute_actual_chatter_cut, safe_float_setting
from team_helpers import list_teams, ensure_default_team, team_transaction_clause, team_inherits_global_economics
from team_economics import sum_revenue, aggregate_teams

logger = logging.getLogger("skynet.finance")
router = APIRouter(prefix="/api/v1", tags=["finance"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _finite(x) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _sanitize_eco(eco: dict) -> dict:
    """JSON не допускает NaN/inf — иначе FastAPI отдаёт 500 при сериализации ответа."""
    out = dict(eco)
    for k, v in list(out.items()):
        if k in ("use_withdraw", "use_retention"):
            out[k] = bool(v)
            continue
        if isinstance(v, bool):
            continue
        out[k] = _finite(v)
    return out


def _http_error_detail(exc: BaseException, max_len: int = 520) -> str:
    """Краткий текст для JSON detail — виден в Network → Response без env vars."""
    name = type(exc).__name__
    msg = str(exc).strip() or repr(exc)
    return f"{name}: {msg}"[:max_len]


def _economic_breakdown(eco: dict) -> EconomicBreakdown:
    """Явная сборка — без KeyError при рассинхроне Pydantic / полей eco."""
    return EconomicBreakdown(
        model_cut=_finite(eco.get("model_cut")),
        chatter_cut=_finite(eco.get("chatter_cut")),
        admin_cut=_finite(eco.get("admin_cut")),
        withdraw=_finite(eco.get("withdraw")),
        retention=_finite(eco.get("retention")),
        total_payouts=_finite(eco.get("total_payouts")),
        db_expenses=_finite(eco.get("db_expenses")),
        total_costs=_finite(eco.get("total_costs")),
        model_pct=_finite(eco.get("model_pct")),
        chatter_pct=_finite(eco.get("chatter_pct")),
        admin_pct=_finite(eco.get("admin_pct")),
        withdraw_pct=_finite(eco.get("withdraw_pct")),
        use_withdraw=bool(eco.get("use_withdraw")),
        use_retention=bool(eco.get("use_retention")),
    )


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
        if not teams:
            await ensure_default_team(db, tenant.id)
            teams = await list_teams(db, tenant.id)
        if not teams:
            raise HTTPException(
                status_code=500,
                detail="Нет команд для агентства — обратитесь в поддержку",
            )
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
            fin_inherit = team_inherits_global_economics(selected_team)
            if fin_inherit:
                cap = None
                dfrac = None
            else:
                try:
                    cm = (
                        float(selected_team.chatter_max_pct)
                        if selected_team.chatter_max_pct is not None
                        else None
                    )
                    cm = cm if cm is not None and math.isfinite(cm) else None
                except (TypeError, ValueError):
                    cm = None
                try:
                    cd = (
                        float(selected_team.default_chatter_pct)
                        if selected_team.default_chatter_pct is not None
                        else None
                    )
                    cd = cd if cd is not None and math.isfinite(cd) else None
                except (TypeError, ValueError):
                    cd = None
                cap = cm / 100 if cm is not None else None
                dfrac = cd / 100 if cd is not None else cap
            chatter_gross, chatter_net = await compute_actual_chatter_cut(
                db, tenant.id, year, month, ur,
                team_id=selected_team.id,
                default_team_id=default_team_id,
                tier_cap=cap if not fin_inherit else None,
                default_chatter_frac=dfrac if not fin_inherit else None,
            )
            if fin_inherit:
                ap = safe_float_setting(settings, "admin_percent", "9") / 100
            else:
                try:
                    ap_t = float(selected_team.admin_percent_total or 0)
                    ap_t = ap_t if math.isfinite(ap_t) else 0.0
                except (TypeError, ValueError):
                    ap_t = 0.0
                ap = ap_t / 100
            admin_override = total_revenue * ap
            eco = _sanitize_eco(
                compute_economics(
                    total_revenue,
                    db_exp_use,
                    settings,
                    actual_chatter_gross=chatter_gross,
                    actual_chatter_net=chatter_net,
                    admin_cut_override=admin_override,
                )
            )
        else:
            total_revenue, chatter_gross, chatter_net, admin_sum, _ = await aggregate_teams(
                db, tenant.id, year, month, settings, teams, default_team_id, ur
            )
            eco = _sanitize_eco(
                compute_economics(
                    total_revenue,
                    db_expenses,
                    settings,
                    actual_chatter_gross=chatter_gross,
                    actual_chatter_net=chatter_net,
                    admin_cut_override=admin_sum,
                )
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
        revenue_delta = _finite(revenue_delta)
        total_revenue = _finite(total_revenue)

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
            total_expenses=_finite(eco["total_costs"]),
            total_profit=_finite(eco["profit"]),
            margin=_finite(eco["margin"]),
            revenue_delta=revenue_delta,
            pnl_rows=pnl_rows,
            waterfall=waterfall,
            expenses_by_category=expenses_by_category,
            economic=_economic_breakdown(eco),
        )

    except HTTPException:
        raise
    except ProgrammingError as e:
        logger.exception("finance SQL tenant=%d", tenant.id)
        raise HTTPException(status_code=500, detail=_http_error_detail(e)) from e
    except Exception as e:
        logger.exception("finance error tenant=%d", tenant.id)
        raise HTTPException(status_code=500, detail=_http_error_detail(e)) from e
