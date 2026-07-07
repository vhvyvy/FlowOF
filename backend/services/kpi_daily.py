"""Daily Onlymonster KPI collection → chatter_kpi_daily table.

Public API:
    collect_daily_kpi(db, tenant_id, target_date) → dict
    backfill_daily_kpi(db, tenant_id, date_from, date_to) → dict

Capped at _MAX_BACKFILL_DAYS days per backfill call.
The monthly chatter_kpi_mt table is NOT touched here.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import Tenant
from services.kpi_service import load_mapping
from services.onlymonster import fetch_chatter_metrics

logger = logging.getLogger("flowof.kpi_daily")

_OM_API_URL = "https://omapi.onlymonster.ai"
_MAX_BACKFILL_DAYS = 180


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_tenant_om_key(db: AsyncSession, tenant_id: int) -> str | None:
    """Return Onlymonster API key for tenant, or None if not set."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    t = result.scalar_one_or_none()
    if t is None:
        return None
    return getattr(t, "onlymonster_key", None) or None


async def _upsert_rows(
    db: AsyncSession,
    tenant_id: int,
    target_date: date,
    rows: list[dict],
) -> int:
    """UPSERT rows into chatter_kpi_daily. Returns number of rows processed."""
    written = 0
    for row in rows:
        chatter = (row.get("chatter") or "").strip()
        if not chatter:
            continue
        await db.execute(
            text(
                """
                INSERT INTO chatter_kpi_daily
                    (tenant_id, chatter, om_user_id, date,
                     ppv_open_rate, apv, total_chats, source)
                VALUES
                    (:tid, :chatter, :om_user_id, :date,
                     :ppv_open_rate, :apv, :total_chats, :source)
                ON CONFLICT (tenant_id, chatter, date) DO UPDATE SET
                    om_user_id    = EXCLUDED.om_user_id,
                    ppv_open_rate = EXCLUDED.ppv_open_rate,
                    apv           = EXCLUDED.apv,
                    total_chats   = EXCLUDED.total_chats,
                    source        = EXCLUDED.source
                """
            ),
            {
                "tid":           tenant_id,
                "chatter":       chatter,
                "om_user_id":    row.get("om_user_id"),
                "date":          target_date,
                "ppv_open_rate": row.get("ppv_open_rate"),
                "apv":           row.get("apv"),
                "total_chats":   row.get("total_chats"),
                "source":        row.get("source", "api"),
            },
        )
        written += 1
    return written


# ── Public API ────────────────────────────────────────────────────────────────

async def collect_daily_kpi(
    db: AsyncSession,
    tenant_id: int,
    target_date: date,
) -> dict:
    """Fetch Onlymonster metrics for a single calendar day and upsert into chatter_kpi_daily.

    Flow:
      1. Check tenant has an OM key.
      2. Load ChatterMapping id_to_name (om_user_id → display name).
      3. Call fetch_chatter_metrics for target_date 00:00:00 → 23:59:59.
      4. Map each raw record: om_user_id → chatter display name (fallback: raw id).
      5. UPSERT into chatter_kpi_daily; commit.

    Returns dict: {date, records_fetched, records_written, error?}
    """
    summary: dict = {"date": str(target_date), "records_fetched": 0, "records_written": 0}

    # 1. API key
    om_key = await _get_tenant_om_key(db, tenant_id)
    if not om_key:
        summary["error"] = "Onlymonster API key not configured for this tenant"
        return summary

    # 2. Mapping
    id_to_name: dict[str, str] = {}
    try:
        id_to_name, _ = await load_mapping(db, tenant_id)
    except Exception as exc:
        logger.warning("kpi_daily: mapping load failed tenant=%s: %s", tenant_id, exc)
        try:
            await db.rollback()
        except Exception:
            pass

    # 3. Fetch from API
    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    end_dt   = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)
    try:
        raw = await fetch_chatter_metrics(_OM_API_URL, om_key, start_dt, end_dt)
    except Exception as exc:
        summary["error"] = str(exc)
        logger.warning(
            "kpi_daily: API error tenant=%s date=%s: %s", tenant_id, target_date, exc
        )
        return summary

    summary["records_fetched"] = len(raw)
    if not raw:
        logger.info("kpi_daily: 0 records from API tenant=%s date=%s", tenant_id, target_date)
        return summary

    # 4. Build rows with mapped chatter names
    rows_to_write: list[dict] = []
    for r in raw:
        om_id = str(r.get("user_id") or r.get("chatter") or "").strip()
        if not om_id:
            continue
        chatter_name = id_to_name.get(om_id) or om_id
        rows_to_write.append({
            "chatter":       chatter_name,
            "om_user_id":    om_id,
            "ppv_open_rate": r.get("ppv_open_rate"),
            "apv":           r.get("apv"),
            "total_chats":   r.get("total_chats"),
            "source":        "api",
        })

    # 5. UPSERT + commit
    try:
        written = await _upsert_rows(db, tenant_id, target_date, rows_to_write)
        await db.commit()
        summary["records_written"] = written
        logger.info(
            "kpi_daily: tenant=%s date=%s fetched=%s written=%s",
            tenant_id, target_date, summary["records_fetched"], written,
        )
    except Exception as exc:
        summary["error"] = str(exc)
        logger.error(
            "kpi_daily: upsert error tenant=%s date=%s: %s",
            tenant_id, target_date, exc, exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            pass

    return summary


async def backfill_daily_kpi(
    db: AsyncSession,
    tenant_id: int,
    date_from: date,
    date_to: date,
) -> dict:
    """Collect daily KPI for each day in [date_from, date_to] (inclusive).

    Cap: _MAX_BACKFILL_DAYS (180). Errors per day are logged and skipped —
    the rest of the range continues.

    Returns:
        {date_from, date_to, days_requested, days_ok, days_error, errors[]}
    """
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    total_days = (date_to - date_from).days + 1
    if total_days > _MAX_BACKFILL_DAYS:
        # Clamp: start from date_to - MAX so we always cover the most recent end
        date_from  = date_to - timedelta(days=_MAX_BACKFILL_DAYS - 1)
        total_days = _MAX_BACKFILL_DAYS
        logger.warning(
            "kpi_daily backfill: capped to %d days, starting from %s",
            _MAX_BACKFILL_DAYS, date_from,
        )

    days_ok     = 0
    days_error  = 0
    errors: list[str] = []

    current = date_from
    while current <= date_to:
        try:
            result = await collect_daily_kpi(db, tenant_id, current)
            if result.get("error"):
                days_error += 1
                errors.append(f"{current}: {result['error']}")
                logger.warning(
                    "kpi_daily backfill: day error tenant=%s date=%s: %s",
                    tenant_id, current, result["error"],
                )
            else:
                days_ok += 1
        except Exception as exc:
            days_error += 1
            errors.append(f"{current}: {exc}")
            logger.error(
                "kpi_daily backfill: unexpected error tenant=%s date=%s: %s",
                tenant_id, current, exc,
            )
            try:
                await db.rollback()
            except Exception:
                pass
        current += timedelta(days=1)

    logger.info(
        "kpi_daily backfill DONE tenant=%s %s→%s: ok=%s error=%s",
        tenant_id, date_from, date_to, days_ok, days_error,
    )
    return {
        "date_from":      str(date_from),
        "date_to":        str(date_to),
        "days_requested": total_days,
        "days_ok":        days_ok,
        "days_error":     days_error,
        "errors":         errors[:20],  # cap so the HTTP response stays sane
    }
