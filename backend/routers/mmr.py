"""
MMR-роутер: все owner-эндпоинты рейтинговой системы.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner
from models import User
from services.mmr_service import MMRService
from services.season_service import SeasonService

router = APIRouter(prefix="/api/v1/mmr", tags=["mmr"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecalculateRequest(BaseModel):
    date: date


class RecalculateRangeRequest(BaseModel):
    date_from: date
    date_to: date


class MmrSettingsUpdate(BaseModel):
    fin_overperform_threshold: Optional[float] = None
    fin_underperform_threshold: Optional[float] = None
    fin_overperform_points: Optional[int] = None
    fin_perform_points: Optional[int] = None
    fin_underperform_points: Optional[int] = None
    fin_empty_shift_points: Optional[int] = None
    kpi_threshold_high: Optional[float] = None
    kpi_threshold_low: Optional[float] = None
    kpi_high_points: Optional[int] = None
    kpi_low_points: Optional[int] = None
    kpi_enabled: Optional[bool] = None
    season_carry_over: Optional[float] = None
    prize_1st: Optional[float] = None
    prize_2nd: Optional[float] = None
    prize_3rd: Optional[float] = None
    calibration_days: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_active_season_id(tenant_id: int, db: AsyncSession) -> Optional[int]:
    result = await db.execute(
        text(
            """SELECT id FROM mmr_seasons
               WHERE tenant_id = :tid AND is_active = TRUE
               ORDER BY start_date DESC LIMIT 1"""
        ),
        {"tid": tenant_id},
    )
    row = result.mappings().first()
    return row["id"] if row else None


# ── Ручной пересчёт ───────────────────────────────────────────────────────────

@router.post("/recalculate")
async def recalculate_day(
    body: RecalculateRequest,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Ручной пересчёт MMR за конкретный день (идемпотентен)."""
    try:
        service = MMRService(db)
        result = await service.process_day(owner.tenant_id, body.date)
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/recalculate-range")
async def recalculate_range(
    body: RecalculateRangeRequest,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Пересчёт MMR за диапазон дат. Максимум 90 дней за раз."""
    import logging
    logger = logging.getLogger("flowof.mmr")

    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="date_from должна быть ≤ date_to")

    delta = (body.date_to - body.date_from).days + 1
    if delta > 90:
        raise HTTPException(status_code=400, detail=f"Максимум 90 дней за раз, запрошено {delta}")

    service = MMRService(db)
    days_processed = 0
    total_events = 0
    errors: list[str] = []

    current = body.date_from
    while current <= body.date_to:
        try:
            logger.info("MMR range: processing tenant=%s date=%s (%d/%d)",
                        owner.tenant_id, current, days_processed + 1, delta)
            result = await service.process_day(owner.tenant_id, current)
            total_events += result.get("events_created", 0)
            days_processed += 1
        except Exception as exc:
            err_msg = f"{current}: {exc}"
            logger.error("MMR range error: %s", err_msg)
            errors.append(err_msg)
        current += timedelta(days=1)

    logger.info("MMR range done: tenant=%s days=%d events=%d errors=%d",
                owner.tenant_id, days_processed, total_events, len(errors))
    return {
        "success": len(errors) == 0,
        "days_processed": days_processed,
        "total_days": delta,
        "total_events": total_events,
        "errors": errors[:10],  # cap to avoid huge responses
    }


# ── Лидерборд ─────────────────────────────────────────────────────────────────

@router.get("/leaderboard")
async def leaderboard(
    season_id: Optional[int] = Query(None),
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Лидерборд агентства за сезон (по умолчанию — активный)."""
    sid = season_id or await _get_active_season_id(owner.tenant_id, db)
    if not sid:
        return {"season": None, "rows": []}

    # Данные сезона
    season_result = await db.execute(
        text("SELECT * FROM mmr_seasons WHERE id = :sid"),
        {"sid": sid},
    )
    season_row = dict(season_result.mappings().first() or {})
    if season_row.get("start_date"):
        season_row["start_date"] = str(season_row["start_date"])
    if season_row.get("end_date"):
        season_row["end_date"] = str(season_row["end_date"])

    # Лидерборд
    result = await db.execute(
        text(
            """SELECT
                 cm.chatter_id,
                 c.name,
                 cm.current_mmr,
                 cm.peak_mmr,
                 cm.current_league,
                 cm.days_active,
                 cm.calibration_complete,
                 ROW_NUMBER() OVER (ORDER BY cm.current_mmr DESC) AS rank
               FROM chatter_mmr cm
               JOIN chatters c ON cm.chatter_id = c.id
               WHERE cm.tenant_id = :tid AND cm.season_id = :sid
               ORDER BY cm.current_mmr DESC"""
        ),
        {"tid": owner.tenant_id, "sid": sid},
    )
    rows = [dict(r) for r in result.mappings()]
    return {"season": season_row, "rows": rows}


# ── История событий ───────────────────────────────────────────────────────────

@router.get("/events")
async def events(
    chatter_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """История MMR-событий за последние N дней."""
    since = date.today() - timedelta(days=days)
    params: dict = {"tid": owner.tenant_id, "since": since}
    extra = ""
    if chatter_id:
        extra = " AND e.chatter_id = :cid"
        params["cid"] = chatter_id

    result = await db.execute(
        text(
            f"""SELECT
                  e.id, e.event_date, e.event_type, e.category,
                  e.points, e.description,
                  c.name AS chatter_name,
                  mo.name AS model_name,
                  sc.name AS shift_name
                FROM mmr_events e
                JOIN chatters c ON e.chatter_id = c.id
                LEFT JOIN models mo ON e.model_id = mo.id
                LEFT JOIN shifts_catalog sc ON e.shift_id = sc.id
                WHERE e.tenant_id = :tid AND e.event_date >= :since{extra}
                ORDER BY e.event_date DESC, e.id DESC
                LIMIT 500"""
        ),
        params,
    )
    rows = []
    for r in result.mappings():
        row = dict(r)
        if row.get("event_date"):
            row["event_date"] = str(row["event_date"])
        rows.append(row)
    return {"events": rows}


# ── Настройки ─────────────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Текущие настройки MMR агентства."""
    result = await db.execute(
        text("SELECT * FROM mmr_settings WHERE tenant_id = :tid"),
        {"tid": owner.tenant_id},
    )
    row = result.mappings().first()
    if not row:
        # Создать дефолтные
        await db.execute(
            text("INSERT INTO mmr_settings (tenant_id) VALUES (:tid) ON CONFLICT DO NOTHING"),
            {"tid": owner.tenant_id},
        )
        await db.commit()
        result = await db.execute(
            text("SELECT * FROM mmr_settings WHERE tenant_id = :tid"),
            {"tid": owner.tenant_id},
        )
        row = result.mappings().first()
    return dict(row) if row else {}


@router.put("/settings")
async def update_settings(
    data: MmrSettingsUpdate,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Обновить настройки MMR агентства."""
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Нет полей для обновления")

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["tid"] = owner.tenant_id

    await db.execute(
        text(
            f"""INSERT INTO mmr_settings (tenant_id) VALUES (:tid)
                ON CONFLICT (tenant_id) DO UPDATE SET {set_clause}, updated_at = NOW()"""
        ),
        updates,
    )
    await db.commit()
    return {"success": True}


# ── Сезоны ────────────────────────────────────────────────────────────────────

@router.get("/seasons")
async def list_seasons(
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Список всех сезонов агентства (активный первым)."""
    result = await db.execute(
        text(
            """SELECT id, name, start_date, end_date, is_active, closed_at, created_at
               FROM mmr_seasons
               WHERE tenant_id = :tid
               ORDER BY is_active DESC, start_date DESC"""
        ),
        {"tid": owner.tenant_id},
    )
    rows = []
    for r in result.mappings():
        row = dict(r)
        for f in ("start_date", "end_date"):
            if row.get(f):
                row[f] = str(row[f])
        rows.append(row)
    return {"seasons": rows}


@router.get("/seasons/{season_id}/results")
async def season_results(
    season_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Результаты закрытого сезона с призами и именами чаттеров."""
    # Проверить принадлежность сезона tenant
    season_row = await db.execute(
        text("SELECT * FROM mmr_seasons WHERE id = :sid AND tenant_id = :tid"),
        {"sid": season_id, "tid": owner.tenant_id},
    )
    season = season_row.mappings().first()
    if not season:
        raise HTTPException(status_code=404, detail="Сезон не найден")

    result = await db.execute(
        text(
            """SELECT
                 sr.rank, sr.final_mmr, sr.final_league,
                 sr.prize_amount, sr.prize_paid, sr.prize_paid_at,
                 c.name AS chatter_name, sr.chatter_id
               FROM season_results sr
               JOIN chatters c ON sr.chatter_id = c.id
               WHERE sr.season_id = :sid
               ORDER BY sr.rank"""
        ),
        {"sid": season_id},
    )
    rows = []
    for r in result.mappings():
        row = dict(r)
        row["prize_amount"] = float(row["prize_amount"] or 0)
        if row.get("prize_paid_at"):
            row["prize_paid_at"] = str(row["prize_paid_at"])
        rows.append(row)

    season_dict = dict(season)
    for f in ("start_date", "end_date"):
        if season_dict.get(f):
            season_dict[f] = str(season_dict[f])

    return {"season": season_dict, "results": rows}


@router.post("/seasons/{season_id}/mark-prize-paid/{chatter_id}")
async def mark_prize_paid(
    season_id: int,
    chatter_id: int,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Owner отмечает выплату приза чаттеру."""
    result = await db.execute(
        text(
            """UPDATE season_results
               SET prize_paid = TRUE, prize_paid_at = NOW()
               WHERE season_id = :sid AND chatter_id = :cid
                 AND tenant_id = :tid
               RETURNING id"""
        ),
        {"sid": season_id, "cid": chatter_id, "tid": owner.tenant_id},
    )
    if not result.mappings().first():
        raise HTTPException(status_code=404, detail="Запись не найдена")
    await db.commit()
    return {"success": True}
