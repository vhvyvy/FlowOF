"""Личный кабинет чаттера — эндпоинты /api/v1/me/*."""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_chatter
from economics import PLAN_TIERS, DEFAULT_TIER, RETENTION_RATE, load_settings, _norm_model_name
from models import AppSetting, ChatterKpi, Plan, Transaction, User
from team_helpers import list_teams, ensure_default_team
from routers.kpi import _load_kpi_data, _load_mapping, _resolve_kpi

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
            """SELECT u.email, u.full_name, u.avatar_base64,
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


class AvatarPayload(BaseModel):
    avatar_base64: str | None = None  # None = удалить


@router.put("/avatar")
async def update_avatar(
    payload: AvatarPayload,
    user: User = Depends(require_chatter),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить или удалить аватарку (base64 JPEG/PNG ≤ ~700KB строки)."""
    data = payload.avatar_base64
    if data is not None and len(data) > 720_000:
        raise HTTPException(status_code=413, detail="Аватарка слишком большая (макс ~500 КБ)")
    await db.execute(
        text("UPDATE users SET avatar_base64 = :av WHERE id = :uid"),
        {"av": data, "uid": user.id},
    )
    await db.commit()
    return {"success": True}


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

    # ── Анкеты чаттера: определяем модели по кол-ву его транзакций ───────────
    # Используем chatter_id только чтобы понять на каких анкетах он работал
    # и выбрать основную. Выручку и план — берём по всей модели (агентская цифра).
    chatter_profile_result = await db.execute(
        text(
            """SELECT
                   COALESCE(m.name, t.model, '') AS model_name,
                   COUNT(t.id)                   AS shift_count
               FROM transactions t
               LEFT JOIN models m ON m.id = t.model_id
               WHERE t.tenant_id = :tid
                 AND t.chatter_id = :cid
                 AND t.date >= :start AND t.date <= :end
               GROUP BY COALESCE(m.name, t.model, '')
               ORDER BY COUNT(t.id) DESC, SUM(t.amount) DESC"""
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "start": start, "end": end},
    )
    chatter_profile_rows = list(chatter_profile_result.mappings())
    # names the chatter worked on, ordered by shift count
    chatter_model_names: list[str] = [r["model_name"] for r in chatter_profile_rows]

    # Plans for this month (all models)
    plans_result = await db.execute(
        select(Plan.model, Plan.plan_amount).where(
            and_(Plan.tenant_id == user.tenant_id, Plan.year == year, Plan.month == month)
        )
    )
    plan_map: dict[str, float] = {
        _norm_model_name(r.model): float(r.plan_amount or 0)
        for r in plans_result.all()
        if r.plan_amount
    }

    # Total revenue per model for the month (all chatters, not just this one)
    model_rev_result = await db.execute(
        text(
            """SELECT
                   COALESCE(m.name, t.model, '') AS model_name,
                   SUM(t.amount)                 AS revenue
               FROM transactions t
               LEFT JOIN models m ON m.id = t.model_id
               WHERE t.tenant_id = :tid
                 AND t.date >= :start AND t.date <= :end
               GROUP BY COALESCE(m.name, t.model, '')"""
        ),
        {"tid": user.tenant_id, "start": start, "end": end},
    )
    total_model_revenue: dict[str, float] = {
        r["model_name"]: float(r["revenue"] or 0)
        for r in model_rev_result.mappings()
    }

    def _profile_entry(model_name: str) -> dict:
        rev  = total_model_revenue.get(model_name, 0.0)
        plan = plan_map.get(_norm_model_name(model_name), 0.0)
        pct  = round(rev / plan * 100, 1) if plan > 0 else None
        return {"name": model_name, "plan_amount": plan, "revenue_on_it": round(rev, 2), "performance_pct": pct}

    main_profile: dict | None = None
    other_profiles: list[dict] = []
    if chatter_model_names:
        main_profile = _profile_entry(chatter_model_names[0])
        other_profiles = [_profile_entry(n) for n in chatter_model_names[1:]]
        other_profiles.sort(key=lambda x: -x["revenue_on_it"])

    # Legacy plan_pct for salary calc compatibility
    total_plan = sum(e["plan_amount"] for e in ([main_profile] + other_profiles if main_profile else []))
    plan_pct   = round(revenue / total_plan * 100, 1) if total_plan > 0 else 0.0

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

    # Авансы и штрафы за месяц
    adj_result = await db.execute(
        text(
            """SELECT a.id, a.type, a.amount, a.description, a.date
               FROM chatter_adjustments a
               WHERE a.tenant_id = :tid AND a.chatter_id = :cid
                 AND EXTRACT(MONTH FROM a.date) = :month
                 AND EXTRACT(YEAR  FROM a.date) = :year
               ORDER BY a.date DESC, a.id DESC
               LIMIT 10"""
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "month": month, "year": year},
    )
    adjustments_list = []
    advances_total = 0.0
    penalties_total = 0.0
    for r in adj_result.mappings():
        amt = float(r["amount"] or 0)
        entry = {
            "id": r["id"],
            "type": r["type"],
            "amount": amt,
            "description": r["description"],
            "date": str(r["date"]),
        }
        adjustments_list.append(entry)
        if r["type"] == "advance":
            advances_total += amt
        elif r["type"] == "penalty":
            penalties_total += amt

    to_pay = round(salary - penalties_total - advances_total, 2)

    return {
        "revenue": revenue,
        "transactions": transactions,
        "salary": salary,
        "plan_amount": total_plan,
        "plan_pct": plan_pct,
        "main_profile": main_profile,
        "other_profiles": other_profiles,
        "daily_revenue": daily,
        "recent_transactions": recent,
        "advances_total": round(advances_total, 2),
        "penalties_total": round(penalties_total, 2),
        "to_pay": to_pay,
        "adjustments": adjustments_list,
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
    """KPI чаттера из Onlymonster — переиспользует ту же логику что owner /api/v1/kpi."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Чаттер не привязан к аккаунту")

    # ── Имя чаттера из справочника ────────────────────────────────────────────
    chatter_name_result = await db.execute(
        text("SELECT name FROM chatters WHERE id = :cid"),
        {"cid": user.chatter_id},
    )
    name_row = chatter_name_result.mappings().first()
    chatter_name = (name_row["name"] or "").strip() if name_row else ""

    if not chatter_name:
        logger.warning("KPI /me/kpi: no name for chatter_id=%s", user.chatter_id)
        return {"kpi": None, "has_onlymonster_key": False}

    # ── Наличие ключа Onlymonster ─────────────────────────────────────────────
    tenant_result = await db.execute(
        text("SELECT onlymonster_key FROM tenants WHERE id = :tid"),
        {"tid": user.tenant_id},
    )
    tenant_row = tenant_result.mappings().first()
    has_om_key = bool(tenant_row and tenant_row.get("onlymonster_key"))

    # ── Загрузить KPI за месяц (тот же источник что owner-эндпоинт) ──────────
    kpi_data = await _load_kpi_data(db, user.tenant_id, year, month)
    id_to_name, name_to_id = await _load_mapping(db, user.tenant_id)

    logger.info(
        "KPI /me/kpi: chatter_id=%s name=%r month=%s/%s, "
        "kpi_data keys=%s, name_to_id keys=%s",
        user.chatter_id, chatter_name, month, year,
        list(kpi_data.keys())[:20],
        list(name_to_id.keys())[:20],
    )

    # ── Разрешить метрики через _resolve_kpi (multi-strategy fuzzy match) ─────
    om_metrics, om_id = _resolve_kpi(chatter_name, kpi_data, name_to_id)

    logger.info(
        "KPI /me/kpi: resolved om_id=%s metrics=%s",
        om_id, om_metrics,
    )

    if not om_metrics:
        return {"kpi": None, "has_onlymonster_key": has_om_key}

    ppv_or  = om_metrics.get("ppv_open_rate")
    apv     = om_metrics.get("apv")
    chats   = om_metrics.get("total_chats")

    return {
        "kpi": {
            "chatter": chatter_name,
            "onlymonster_id": om_id,
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
    event_type: str | None = Query(None, description="finance | kpi | all"),
    offset: int = Query(0, ge=0),
    limit: int = Query(14, ge=1, le=60),
):
    """MMR-события чаттера, сгруппированные по дням. Каждый день — отдельный объект."""
    if not user.chatter_id:
        raise HTTPException(status_code=400, detail="Chatter not linked")

    # Normalise filter
    filter_type = event_type if event_type in ("finance", "kpi") else None

    # 1. Find distinct dates that match the filter (pagination by date)
    date_filter = "AND me.event_type = :etype" if filter_type else ""
    date_params: dict = {"tid": user.tenant_id, "cid": user.chatter_id,
                         "lim": limit, "off": offset}
    if filter_type:
        date_params["etype"] = filter_type

    dates_result = await db.execute(
        text(
            f"SELECT DISTINCT me.event_date "
            f"FROM mmr_events me "
            f"WHERE me.tenant_id = :tid AND me.chatter_id = :cid {date_filter} "
            f"ORDER BY me.event_date DESC "
            f"LIMIT :lim OFFSET :off"
        ),
        date_params,
    )
    dates = [r["event_date"] for r in dates_result.mappings()]
    if not dates:
        return {"days": [], "offset": offset, "limit": limit}

    # 2. Fetch all events for those dates (no event_type filter — we need both for full day)
    events_result = await db.execute(
        text(
            "SELECT me.event_date, me.event_type, me.category, me.points, "
            "       me.description, "
            "       m.name AS model_name, sc.name AS shift_name "
            "FROM mmr_events me "
            "LEFT JOIN models m ON me.model_id = m.id "
            "LEFT JOIN shifts_catalog sc ON me.shift_id = sc.id "
            "WHERE me.tenant_id = :tid AND me.chatter_id = :cid "
            "  AND me.event_date = ANY(:dates) "
            "ORDER BY me.event_date DESC, me.id ASC"
        ),
        {"tid": user.tenant_id, "cid": user.chatter_id, "dates": dates},
    )
    raw_events = list(events_result.mappings())

    # 3. Group by date
    from collections import defaultdict
    day_events: dict = defaultdict(lambda: {"finance": [], "kpi": []})
    for r in raw_events:
        dt = str(r["event_date"])
        etype = r["event_type"]
        if etype not in ("finance", "kpi"):
            etype = "finance"  # season_carry etc. → treat as finance
        day_events[dt][etype].append(r)

    # 4. Build response
    def _parse_description(desc: str) -> dict:
        """Try to extract plan/revenue/pct from description like 'Plan $117, revenue $148 (127%)'."""
        import re
        out: dict = {"plan": None, "revenue": None, "performance_pct": None}
        if not desc:
            return out
        m = re.search(r"Plan \$?([\d.]+)", desc)
        if m:
            out["plan"] = float(m.group(1))
        m = re.search(r"revenue \$?([\d.]+)", desc)
        if m:
            out["revenue"] = float(m.group(1))
        m = re.search(r"\((\d+)%\)", desc)
        if m:
            out["performance_pct"] = int(m.group(1))
        return out

    def _parse_kpi_description(desc: str) -> dict:
        """Extract metric name, value and avg from 'PPV OR: 18.10 (среднее 25.34, -44%)'."""
        import re
        out: dict = {"name": None, "value": None, "avg": None, "pct": None}
        if not desc:
            return out
        # 'PPV OR: 18.10 (среднее 25.34, -44%)'
        m = re.match(r"^(.+?):\s*([\d.]+)\s*\(среднее ([\d.]+),\s*([+-]?\d+)%\)", desc.strip())
        if m:
            out["name"] = m.group(1).strip()
            out["value"] = float(m.group(2))
            out["avg"] = float(m.group(3))
            out["pct"] = int(m.group(4))
        else:
            out["name"] = desc[:40]
        return out

    days_out = []
    for dt in sorted(day_events.keys(), reverse=True):
        if str(dates[0]) < dt or str(dates[-1]) > dt:
            continue  # skip dates outside our page
        fin_rows = day_events[dt]["finance"]
        kpi_rows = day_events[dt]["kpi"]

        # Apply event_type filter to what we include (the dates were already filtered)
        finance_events = []
        if filter_type != "kpi":
            for r in fin_rows:
                parsed = _parse_description(r["description"] or "")
                finance_events.append({
                    "model_name": r["model_name"],
                    "shift_name": r["shift_name"],
                    "plan": parsed["plan"],
                    "revenue": parsed["revenue"],
                    "performance_pct": parsed["performance_pct"],
                    "points": int(r["points"]),
                    "category": r["category"],
                    "description": r["description"] or "",
                })

        kpi_summary = None
        if filter_type != "finance" and kpi_rows:
            kpi_metrics = []
            kpi_total = 0
            for r in kpi_rows:
                parsed = _parse_kpi_description(r["description"] or "")
                pts = int(r["points"])
                kpi_total += pts
                kpi_metrics.append({
                    "name": parsed["name"],
                    "value": parsed["value"],
                    "avg": parsed["avg"],
                    "pct": parsed["pct"],
                    "points": pts,
                    "direction": "up" if pts > 0 else "down",
                    "category": r["category"],
                })
            kpi_summary = {"metrics": kpi_metrics, "kpi_total": kpi_total}

        total_fin = sum(int(r["points"]) for r in fin_rows) if filter_type != "kpi" else 0
        total_kpi = (kpi_summary["kpi_total"] if kpi_summary else 0) if filter_type != "finance" else 0

        days_out.append({
            "date": dt,
            "total_points": total_fin + total_kpi,
            "finance_events": finance_events,
            "kpi_summary": kpi_summary,
        })

    return {"days": days_out, "offset": offset, "limit": limit}


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
            "       cm.calibration_complete, u.avatar_base64, "
            "       ROW_NUMBER() OVER (ORDER BY cm.current_mmr DESC) AS rank "
            "FROM chatter_mmr cm "
            "JOIN chatters c ON cm.chatter_id = c.id "
            "LEFT JOIN users u ON u.chatter_id = c.id AND u.tenant_id = cm.tenant_id "
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
            "avatar_base64": r.get("avatar_base64"),
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
