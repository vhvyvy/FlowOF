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


# ── MMR — личный рейтинг ──────────────────────────────────────────────────────

def _next_league_info(mmr: int) -> tuple[str | None, int | None]:
    """Вернуть (следующая_лига, сколько_MMR_до_неё)."""
    from services.mmr_service import LEAGUE_THRESHOLDS
    for name, threshold in LEAGUE_THRESHOLDS:
        if threshold > mmr:
            return name, threshold - mmr
    return None, None  # Grandmaster — максимум


@router.get("/mmr")
async def my_mmr(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Главная страница рейтинга чаттера."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    logger.info("[MMR] /me/mmr called: user_id=%s chatter_id=%s tenant_id=%s",
                user.id, user.chatter_id, user.tenant_id)

    # ── Шаг 1: ищем запись чаттера по последнему сезону (без фильтра is_active)
    mmr_result = await db.execute(
        text(
            "SELECT cm.current_mmr, cm.peak_mmr, cm.current_league, "
            "       cm.calibration_complete, cm.days_active, cm.season_id "
            "FROM chatter_mmr cm "
            "WHERE cm.tenant_id = :tid AND cm.chatter_id = :cid "
            "ORDER BY cm.season_id DESC LIMIT 1"
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id},
    )
    mmr_row = mmr_result.mappings().first()

    logger.info("[MMR] chatter_mmr row: %s", dict(mmr_row) if mmr_row else None)

    # Если в chatter_mmr вообще нет записи — рейтинг не запущен
    if mmr_row is None:
        return {
            "has_season": False,
            "current_mmr": 0, "peak_mmr": 0,
            "current_league": None, "calibration_complete": False,
        }

    season_id = mmr_row["season_id"]

    # ── Шаг 2: загружаем инфо о сезоне (по season_id из chatter_mmr)
    season_result = await db.execute(
        text("SELECT * FROM mmr_seasons WHERE id = :sid"),
        {"sid": season_id},
    )
    season = season_result.mappings().first()

    logger.info("[MMR] season row: %s", dict(season) if season else None)

    # mmr_row is guaranteed non-None here (we returned early if it was None)
    current_mmr = int(mmr_row["current_mmr"] or 0)
    peak_mmr = int(mmr_row["peak_mmr"] or 0)
    current_league = mmr_row["current_league"]
    calibrated = bool(mmr_row["calibration_complete"])
    days_active = int(mmr_row["days_active"] or 0)

    logger.info("[MMR] parsed: current_mmr=%s peak_mmr=%s league=%s calibrated=%s days_active=%s",
                current_mmr, peak_mmr, current_league, calibrated, days_active)

    # Настройки MMR (для calibration_days и призов)
    cfg_result = await db.execute(
        text("SELECT calibration_days, prize_1st, prize_2nd, prize_3rd FROM mmr_settings WHERE tenant_id = :tid"),
        {"tid": user.tenant_id},
    )
    cfg = cfg_result.mappings().first()

    def _cfg_int(key: str, default: int) -> int:
        if cfg is None:
            return default
        v = cfg.get(key)
        return int(v) if v is not None else default

    def _cfg_float(key: str, default: float) -> float:
        if cfg is None:
            return default
        v = cfg.get(key)
        return float(v) if v is not None else default

    calibration_days = _cfg_int("calibration_days", 14)
    prize_info = {
        "1st": _cfg_float("prize_1st", 200.0),
        "2nd": _cfg_float("prize_2nd", 150.0),
        "3rd": _cfg_float("prize_3rd", 100.0),
    }

    # Ранг чаттера в агентстве (по текущему сезону)
    rank_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM chatter_mmr "
            "WHERE tenant_id = :tid AND season_id = :sid "
            "  AND current_mmr > :mmr"
        ),
        {"tid": user.tenant_id, "sid": season_id, "mmr": current_mmr},
    )
    rank = int(rank_result.scalar() or 0) + 1

    total_result = await db.execute(
        text("SELECT COUNT(*) FROM chatter_mmr WHERE tenant_id = :tid AND season_id = :sid"),
        {"tid": user.tenant_id, "sid": season_id},
    )
    total_chatters = int(total_result.scalar() or 0)

    next_league, mmr_to_next = _next_league_info(current_mmr)

    # Дней до конца сезона (season может быть None если запись удалена)
    from datetime import date as _date
    season_name = season["name"] if season else f"Сезон #{season_id}"
    season_end_date = season["end_date"] if season else None
    days_left = max(0, (season_end_date - _date.today()).days) if season_end_date else None

    logger.info("[MMR] season_name=%s days_left=%s rank=%s/%s", season_name, days_left, rank, total_chatters)

    return {
        "has_season": True,
        "season_name": season_name,
        "season_end_date": str(season_end_date) if season_end_date else None,
        "season_days_left": days_left,
        "current_mmr": current_mmr,
        "peak_mmr": peak_mmr,
        "current_league": current_league,
        "calibration_complete": calibrated,
        "calibration_days": calibration_days,
        "calibration_days_left": max(0, calibration_days - days_active) if not calibrated else 0,
        "days_active": days_active,
        "rank": rank,
        "total_chatters": total_chatters,
        "next_league": next_league,
        "mmr_to_next": mmr_to_next,
        "prize_info": prize_info,
    }


@router.get("/mmr/events")
async def my_mmr_events(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
    event_type: str | None = Query(None, description="finance | kpi — фильтр по типу"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """MMR-события чаттера с JOIN на модели и смены, пагинацией и фильтром."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    type_filter = "AND me.event_type = :etype" if event_type else ""
    params: dict = {"tid": user.tenant_id, "cid": user.chatter_id,
                    "lim": limit, "off": offset}
    if event_type:
        params["etype"] = event_type

    result = await db.execute(
        text(
            f"SELECT me.event_date, me.event_type, me.category, me.points, "
            f"       me.description, me.model_id, me.shift_id, "
            f"       m.name AS model_name, sc.name AS shift_name "
            f"FROM mmr_events me "
            f"LEFT JOIN models m ON me.model_id = m.id "
            f"LEFT JOIN shifts_catalog sc ON me.shift_id = sc.id "
            f"WHERE me.tenant_id = :tid AND me.chatter_id = :cid {type_filter} "
            f"ORDER BY me.event_date DESC, me.id DESC "
            f"LIMIT :lim OFFSET :off"
        ),
        params,
    )
    events = []
    for r in result.mappings():
        events.append({
            "event_date": str(r["event_date"]),
            "event_type": r["event_type"],
            "category": r["category"],
            "points": int(r["points"]),
            "description": r["description"] or "",
            "model_name": r["model_name"],
            "shift_name": r["shift_name"],
        })
    return {"events": events, "offset": offset, "limit": limit}


@router.get("/mmr/history")
async def my_mmr_history(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """График накопительного MMR по дням за текущий сезон."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    season_result = await db.execute(
        text(
            "SELECT id FROM mmr_seasons "
            "WHERE tenant_id = :tid AND is_active IS NOT FALSE "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"tid": user.tenant_id},
    )
    season_row = season_result.mappings().first()
    if not season_row:
        return {"history": []}

    result = await db.execute(
        text(
            "SELECT event_date, SUM(points) AS daily_points "
            "FROM mmr_events "
            "WHERE tenant_id = :tid AND chatter_id = :cid AND season_id = :sid "
            "GROUP BY event_date ORDER BY event_date ASC"
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "sid": season_row["id"]},
    )
    history = []
    cumulative = 0
    for r in result.mappings():
        cumulative = max(0, cumulative + int(r["daily_points"]))
        history.append({"date": str(r["event_date"]), "mmr": cumulative})
    return {"history": history}


@router.get("/mmr/leaderboard")
async def my_mmr_leaderboard(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Лидерборд агентства глазами чаттера. Без финансов других чаттеров."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    season_result = await db.execute(
        text(
            "SELECT id FROM mmr_seasons "
            "WHERE tenant_id = :tid AND is_active IS NOT FALSE "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"tid": user.tenant_id},
    )
    season_row = season_result.mappings().first()
    if not season_row:
        return {"rows": [], "my_rank": None}

    result = await db.execute(
        text(
            "SELECT cm.chatter_id, c.name AS chatter_name, "
            "       cm.current_mmr, cm.current_league, cm.days_active, "
            "       cm.calibration_complete, "
            "       ROW_NUMBER() OVER (ORDER BY cm.current_mmr DESC) AS rank "
            "FROM chatter_mmr cm "
            "JOIN chatters c ON cm.chatter_id = c.id "
            "WHERE cm.tenant_id = :tid AND cm.season_id = :sid "
            "ORDER BY cm.current_mmr DESC"
        ),
        {"tid": user.tenant_id, "sid": season_row["id"]},
    )
    all_rows = list(result.mappings())

    my_rank = None
    rows_out = []
    for r in all_rows:
        rank = int(r["rank"])
        is_me = r["chatter_id"] == user.chatter_id
        if is_me:
            my_rank = rank
        rows_out.append({
            "rank": rank,
            "chatter_id": r["chatter_id"],
            "chatter_name": r["chatter_name"],
            "current_mmr": int(r["current_mmr"]),
            "current_league": r["current_league"],
            "days_active": int(r["days_active"]),
            "calibration_complete": bool(r["calibration_complete"]),
            "is_me": is_me,
        })

    return {"rows": rows_out, "my_rank": my_rank}


@router.get("/mmr/seasons-history")
async def my_seasons_history(
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """История прошлых сезонов чаттера из season_results."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    result = await db.execute(
        text(
            "SELECT sr.rank, sr.final_mmr, sr.final_league, "
            "       sr.prize_amount, sr.prize_paid, "
            "       s.name AS season_name, s.start_date, s.end_date "
            "FROM season_results sr "
            "JOIN mmr_seasons s ON sr.season_id = s.id "
            "WHERE sr.tenant_id = :tid AND sr.chatter_id = :cid "
            "ORDER BY s.end_date DESC"
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id},
    )
    rows = []
    for r in result.mappings():
        rows.append({
            "season_name": r["season_name"],
            "start_date": str(r["start_date"]) if r["start_date"] else None,
            "end_date": str(r["end_date"]) if r["end_date"] else None,
            "rank": r["rank"],
            "final_mmr": r["final_mmr"],
            "final_league": r["final_league"],
            "prize_amount": float(r["prize_amount"] or 0),
            "prize_paid": bool(r["prize_paid"]),
        })
    return {"history": rows}
