import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Plan, Transaction
from schemas import PlanUpsert, PlanOut, PlansResponse

logger = logging.getLogger("skynet.plans")
router = APIRouter(prefix="/api/v1", tags=["plans"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.get("/plans", response_model=PlansResponse)
async def get_plans(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        # Plans from DB
        plan_result = await db.execute(
            select(Plan).where(
                and_(
                    Plan.tenant_id == tenant.id,
                    Plan.year == year,
                    Plan.month == month,
                )
            )
        )
        db_plans = {p.model: float(p.plan_amount) for p in plan_result.scalars().all()}

        # Actual revenue by model
        rev_result = await db.execute(
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
        actuals = {r.model: float(r.rev or 0) for r in rev_result.all()}

        # Merge all models (plans + actuals)
        all_models = set(db_plans.keys()) | set(actuals.keys())
        rows: list[PlanOut] = []
        total_plan = 0.0
        weighted_num = 0.0

        for model in sorted(all_models):
            plan_amt = db_plans.get(model, 0.0)
            actual = actuals.get(model, 0.0)
            completion = round(actual / plan_amt * 100, 1) if plan_amt > 0 else 0.0
            rows.append(
                PlanOut(
                    model=model,
                    plan_amount=round(plan_amt, 2),
                    actual=round(actual, 2),
                    completion_pct=completion,
                )
            )
            total_plan += plan_amt
            if plan_amt > 0:
                weighted_num += actual

        weighted = round(weighted_num / total_plan * 100, 1) if total_plan > 0 else 0.0

        return PlansResponse(plans=rows, weighted_completion=weighted)

    except Exception as e:
        logger.error("plans get error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки планов")


@router.put("/plans/{year}/{month}", status_code=204)
async def upsert_plan(
    year: int,
    month: int,
    body: PlanUpsert,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = (
            pg_insert(Plan)
            .values(
                tenant_id=tenant.id,
                year=year,
                month=month,
                model=body.model.strip(),
                plan_amount=body.plan_amount,
            )
            .on_conflict_do_update(
                constraint="uq_plans_tenant_period_model",
                set_={"plan_amount": body.plan_amount},
            )
        )
        await db.execute(stmt)
        await db.commit()
    except Exception as e:
        logger.error("plans upsert error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка сохранения плана")
