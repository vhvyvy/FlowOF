import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Plan, Expense
from schemas import StructureResponse, ModelShare, ChatterShare, ChatterInModel, EconomicBreakdown
from economics import load_settings, compute_economics

logger = logging.getLogger("skynet.structure")
router = APIRouter(prefix="/api/v1", tags=["structure"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/structure", response_model=StructureResponse)
async def get_structure(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)
        settings = await load_settings(db, tenant.id)

        # Revenue by model
        model_result = await db.execute(
            select(Transaction.model, func.sum(Transaction.amount).label("revenue"))
            .where(and_(Transaction.tenant_id == tenant.id, Transaction.date >= start, Transaction.date <= end))
            .group_by(Transaction.model)
            .order_by(func.sum(Transaction.amount).desc())
        )
        model_rows = model_result.all()
        total_revenue = sum(float(r.revenue or 0) for r in model_rows)

        # Revenue by model AND chatter (for hierarchical treemap)
        model_chatter_result = await db.execute(
            select(
                Transaction.model,
                Transaction.chatter,
                func.sum(Transaction.amount).label("revenue"),
            )
            .where(and_(
                Transaction.tenant_id == tenant.id,
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.chatter.isnot(None),
            ))
            .group_by(Transaction.model, Transaction.chatter)
            .order_by(Transaction.model, func.sum(Transaction.amount).desc())
        )
        model_chatter_rows = model_chatter_result.all()

        # Build chatter-per-model index
        from collections import defaultdict
        chatters_by_model: dict[str, list[ChatterInModel]] = defaultdict(list)
        for r in model_chatter_rows:
            chatters_by_model[r.model or "Unknown"].append(
                ChatterInModel(chatter=r.chatter or "Unknown", revenue=round(float(r.revenue or 0), 2))
            )

        # Plans for this period
        plan_result = await db.execute(
            select(Plan.model, Plan.plan_amount).where(
                and_(Plan.tenant_id == tenant.id, Plan.year == year, Plan.month == month)
            )
        )
        plans = {r.model: float(r.plan_amount or 0) for r in plan_result.all()}

        models = []
        for r in model_rows:
            rev = float(r.revenue or 0)
            plan_amt = plans.get(r.model, 0.0)
            completion = round(rev / plan_amt * 100, 1) if plan_amt > 0 else 0.0
            model_name = r.model or "Unknown"
            models.append(ModelShare(
                model=model_name,
                revenue=round(rev, 2),
                share_pct=round(rev / total_revenue * 100, 1) if total_revenue > 0 else 0.0,
                plan_amount=plan_amt,
                plan_completion=completion,
                chatters=chatters_by_model.get(model_name, []),
            ))

        # Revenue by chatter
        chatter_result = await db.execute(
            select(
                Transaction.chatter,
                func.sum(Transaction.amount).label("revenue"),
                func.count(Transaction.id).label("txn_count"),
            )
            .where(and_(
                Transaction.tenant_id == tenant.id,
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.chatter.isnot(None),
            ))
            .group_by(Transaction.chatter)
            .order_by(func.sum(Transaction.amount).desc())
        )
        chatter_rows = chatter_result.all()

        chatters = [
            ChatterShare(
                chatter=r.chatter or "Unknown",
                revenue=round(float(r.revenue or 0), 2),
                share_pct=round(float(r.revenue or 0) / total_revenue * 100, 1) if total_revenue > 0 else 0.0,
                transactions=int(r.txn_count or 0),
            )
            for r in chatter_rows
        ]

        # DB expenses for economic model
        exp_result = await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                and_(Expense.tenant_id == tenant.id, Expense.date >= start, Expense.date <= end)
            )
        )
        db_expenses = float(exp_result.scalar() or 0)
        eco = compute_economics(total_revenue, db_expenses, settings)

        return StructureResponse(
            total_revenue=round(total_revenue, 2),
            models=models,
            chatters=chatters,
            economic=EconomicBreakdown(**{k: eco[k] for k in EconomicBreakdown.model_fields}),
        )

    except Exception as e:
        logger.error("structure error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных")
