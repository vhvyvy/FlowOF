"""Личный кабинет чаттера — эндпоинты /api/v1/me/*."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_chatter
from economics import PLAN_TIERS, DEFAULT_TIER, RETENTION_RATE, load_settings, _norm_model_name
from models import AppSetting, ChatterKpi, Plan, Transaction, User
from team_helpers import list_teams, ensure_default_team

logger = logging.getLogger("flowof.chatter_portal")
router = APIRouter(prefix="/api/v1/me", tags=["chatter_portal"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _tier_pct(completion: float) -> float:
    for threshold, pct in PLAN_TIERS:
        if completion >= threshold:
            return pct
    return 0.20


async def _calc_salary(
    db: AsyncSession,
    tenant_id: int,
    chatter_catalog_id: int,
    year: int,
    month: int,
) -> float:
    """Зарплата конкретного чаттера за месяц по логике тиров агентства."""
    start, end = _month_range(year, month)

    settings = await load_settings(db, tenant_id)
    use_retention = settings.get("use_retention", "1") == "1"

    # Выручка чаттера по моделям
    chatter_model_result = await db.execute(
        select(Transaction.model, func.sum(Transaction.amount).label("rev"))
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.chatter_id == chatter_catalog_id,
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.model.isnot(None),
        ))
        .group_by(Transaction.model)
    )
    chatter_by_model: dict[str, float] = {
        _norm_model_name(r.model): float(r.rev or 0)
        for r in chatter_model_result.all()
    }
    if not chatter_by_model:
        return 0.0

    # Общая выручка по моделям (все чаттеры) — для расчёта тира
    total_model_result = await db.execute(
        select(Transaction.model, func.sum(Transaction.amount).label("rev"))
        .where(and_(
            Transaction.tenant_id == tenant_id,
            Transaction.date >= start,
            Transaction.date <= end,
        ))
        .group_by(Transaction.model)
    )
    total_by_model: dict[str, float] = {
        _norm_model_name(r.model): float(r.rev or 0)
        for r in total_model_result.all()
    }

    # Планы за месяц
    plan_result = await db.execute(
        select(Plan.model, Plan.plan_amount).where(
            and_(Plan.tenant_id == tenant_id, Plan.year == year, Plan.month == month)
        )
    )
    plan_map: dict[str, float] = {
        _norm_model_name(r.model): float(r.plan_amount or 0)
        for r in plan_result.all()
    }

    salary = 0.0
    for model, chatter_rev in chatter_by_model.items():
        plan_amt = plan_map.get(model, 0.0)
        total_rev = total_by_model.get(model, chatter_rev)
        if plan_amt > 0:
            tier = max(0.20, _tier_pct(total_rev / plan_amt))
        else:
            tier = DEFAULT_TIER
        net = chatter_rev * tier * (1 - RETENTION_RATE if use_retention else 1)
        salary += net

    return round(salary, 2)


# ─── Эндпоинты ───────────────────────────────────────────────────────────────

@router.get("/profile")
async def get_my_profile(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Профиль чаттера + название агентства."""
    result = await db.execute(
        text(
            """SELECT u.email, u.full_name,
                      c.name AS chatter_name,
                      t.agency_name, t.currency
               FROM users u
               JOIN chatters c ON u.chatter_id = c.id
               JOIN tenants t ON u.tenant_id = t.id
               WHERE u.id = :uid"""
        ),
        {"uid": user.id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return dict(row)


@router.get("/overview")
async def my_overview(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Главные метрики чаттера за месяц: выручка, зарплата, план, динамика."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Чаттер не привязан к аккаунту")

    start, end = _month_range(year, month)

    # Выручка и кол-во транзакций
    rev_result = await db.execute(
        select(
            func.coalesce(func.sum(Transaction.amount), 0).label("revenue"),
            func.count(Transaction.id).label("transactions"),
        ).where(and_(
            Transaction.tenant_id == user.tenant_id,
            Transaction.chatter_id == user.chatter_id,
            Transaction.date >= start,
            Transaction.date <= end,
        ))
    )
    rev_row = rev_result.one()
    revenue = float(rev_row.revenue)
    transactions = int(rev_row.transactions)

    # Зарплата с тирами
    salary = await _calc_salary(db, user.tenant_id, user.chatter_id, year, month)

    # Выполнение плана — планов нет в привязке к chatter_id в plans; ищем по имени чаттера
    # Считаем план по моделям, где работал этот чаттер
    chatter_models_result = await db.execute(
        select(Transaction.model)
        .where(and_(
            Transaction.tenant_id == user.tenant_id,
            Transaction.chatter_id == user.chatter_id,
            Transaction.date >= start,
            Transaction.date <= end,
        ))
        .group_by(Transaction.model)
    )
    my_models = {_norm_model_name(r.model) for r in chatter_models_result.all()}

    plan_result = await db.execute(
        select(Plan.model, Plan.plan_amount).where(
            and_(Plan.tenant_id == user.tenant_id, Plan.year == year, Plan.month == month)
        )
    )
    total_plan = sum(
        float(r.plan_amount or 0)
        for r in plan_result.all()
        if _norm_model_name(r.model) in my_models
    )

    plan_pct = round(revenue / total_plan * 100, 1) if total_plan > 0 else 0.0

    # Выручка по дням
    daily_result = await db.execute(
        select(
            Transaction.date.label("day"),
            func.sum(Transaction.amount).label("amount"),
        ).where(and_(
            Transaction.tenant_id == user.tenant_id,
            Transaction.chatter_id == user.chatter_id,
            Transaction.date >= start,
            Transaction.date <= end,
        ))
        .group_by(Transaction.date)
        .order_by(Transaction.date)
    )
    daily = [
        {"date": str(r.day), "amount": float(r.amount or 0)}
        for r in daily_result.all()
    ]

    # Последние 5 транзакций
    recent_result = await db.execute(
        text(
            """SELECT t.date, t.amount,
                      COALESCE(m.name, t.model, '') AS model_name,
                      COALESCE(sc.name, t.shift_name, '') AS shift_name
               FROM transactions t
               LEFT JOIN models m ON t.model_id = m.id
               LEFT JOIN shifts_catalog sc ON t.shift_catalog_id = sc.id
               WHERE t.tenant_id = :tid AND t.chatter_id = :cid
                 AND t.date >= :start AND t.date <= :end
               ORDER BY t.date DESC
               LIMIT 5"""
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "start": start, "end": end},
    )
    recent = [dict(r) for r in recent_result.mappings()]
    for r in recent:
        if r.get("date"):
            r["date"] = str(r["date"])
        r["amount"] = float(r["amount"] or 0)

    return {
        "revenue": revenue,
        "transactions": transactions,
        "salary": salary,
        "plan_amount": total_plan,
        "plan_pct": plan_pct,
        "daily_revenue": daily,
        "recent_transactions": recent,
    }


@router.get("/transactions")
async def my_transactions(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Список транзакций чаттера за месяц."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Чаттер не привязан к аккаунту")

    start, end = _month_range(year, month)

    result = await db.execute(
        text(
            """SELECT t.date, t.amount,
                      COALESCE(m.name, t.model, '') AS model_name,
                      COALESCE(sc.name, t.shift_name, '') AS shift_name
               FROM transactions t
               LEFT JOIN models m ON t.model_id = m.id
               LEFT JOIN shifts_catalog sc ON t.shift_catalog_id = sc.id
               WHERE t.tenant_id = :tid AND t.chatter_id = :cid
                 AND t.date >= :start AND t.date <= :end
               ORDER BY t.date DESC"""
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "start": start, "end": end},
    )
    items = []
    for row in result.mappings():
        items.append({
            "date": str(row["date"]),
            "amount": float(row["amount"] or 0),
            "model_name": row["model_name"] or "",
            "shift_name": row["shift_name"] or "",
        })
    return {"items": items}


@router.get("/kpi")
async def my_kpi(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """KPI чаттера из Onlymonster (только его метрики)."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Чаттер не привязан к аккаунту")

    # Получить имя чаттера из справочника
    chatter_name_result = await db.execute(
        text("SELECT name FROM chatters WHERE id = :cid"),
        {"cid": user.chatter_id},
    )
    row = chatter_name_result.mappings().first()
    chatter_name = row["name"] if row else None

    if not chatter_name:
        return {"kpi": None, "has_onlymonster_key": False}

    # Проверить наличие ключа Onlymonster у tenant
    tenant_result = await db.execute(
        text("SELECT onlymonster_key FROM tenants WHERE id = :tid"),
        {"tid": user.tenant_id},
    )
    tenant_row = tenant_result.mappings().first()
    has_om_key = bool(tenant_row and tenant_row.get("onlymonster_key"))

    # Поискать метрики в chatter_kpi_mt по имени
    kpi_result = await db.execute(
        select(ChatterKpi).where(
            and_(
                ChatterKpi.tenant_id == user.tenant_id,
                ChatterKpi.year == year,
                ChatterKpi.month == month,
                ChatterKpi.chatter == chatter_name,
            )
        )
    )
    kpi_row = kpi_result.scalar_one_or_none()

    if kpi_row is None:
        return {"kpi": None, "has_onlymonster_key": has_om_key}

    # Вернуть метрики
    ppv_or = float(kpi_row.ppv_open_rate) if kpi_row.ppv_open_rate is not None else None
    apv = float(kpi_row.apv) if kpi_row.apv is not None else None
    chats = int(kpi_row.total_chats) if kpi_row.total_chats is not None else None

    rpc = round(
        (lambda r, c: r / c if c and c > 0 else None)(
            0, chats  # placeholder — revenue не хранится в kpi_mt
        ) or 0,
        2,
    )

    return {
        "kpi": {
            "chatter": chatter_name,
            "ppv_open_rate": ppv_or,
            "apv": apv,
            "total_chats": chats,
        },
        "has_onlymonster_key": has_om_key,
    }
