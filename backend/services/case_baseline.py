"""
Freeze baseline for KPI Admin cases.

Public API
----------
    freeze_baseline(db, tenant_id, om_user_id, metric_type)
        → tuple[Decimal, date, str] | None

    read_metric_at_date(db, tenant_id, om_user_id, metric_type, target_date)
        → Decimal | None
        Point-in-time read (no look-back).  Used by check_review_due_cases
        for guardrail baseline reconstruction.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.case_baseline")

# Days to scan backward from yesterday when freezing baseline at case creation
BASELINE_LOOKBACK_DAYS = 30

# Metrics stored directly in chatter_kpi_daily
_DAILY_COLS: frozenset[str] = frozenset({"ppv_open_rate", "apv", "total_chats"})


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _display_names(db: AsyncSession, tenant_id: int, om_user_id: str) -> list[str]:
    """Return all chatter display names for the given Onlymonster user ID."""
    row = await db.execute(
        text(
            "SELECT display_names FROM chatter_onlymonster_mapping "
            "WHERE tenant_id = :tid AND onlymonster_id = :uid "
            "LIMIT 1"
        ),
        {"tid": tenant_id, "uid": om_user_id},
    )
    raw = row.scalar_one_or_none()
    if not raw:
        return []
    return [n.strip() for n in str(raw).split(",") if n.strip()]


async def _daily_row(
    db: AsyncSession, tenant_id: int, om_user_id: str, d: date
) -> Optional[dict]:
    """Fetch ppv_open_rate / apv / total_chats from chatter_kpi_daily."""
    row = await db.execute(
        text(
            "SELECT ppv_open_rate, apv, total_chats "
            "FROM chatter_kpi_daily "
            "WHERE tenant_id = :tid AND om_user_id = :uid AND date = :d "
            "LIMIT 1"
        ),
        {"tid": tenant_id, "uid": om_user_id, "d": d},
    )
    r = row.fetchone()
    if r is None:
        return None
    return {"ppv_open_rate": r[0], "apv": r[1], "total_chats": r[2]}


async def _revenue_at(
    db: AsyncSession,
    tenant_id: int,
    display_names: list[str],
    d: date,
) -> Optional[Decimal]:
    """Sum transaction revenue for the given chatter display names on a date."""
    if not display_names:
        return None
    row = await db.execute(
        text(
            "SELECT COALESCE(SUM(amount), 0) "
            "FROM transactions "
            "WHERE tenant_id = :tid AND date = :d AND chatter = ANY(:names)"
        ),
        {"tid": tenant_id, "d": d, "names": display_names},
    )
    val = row.scalar_one_or_none()
    return Decimal(str(val)) if val is not None else None


async def _compute_metric(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    d: date,
    display_names: list[str],
) -> Optional[Decimal]:
    """
    Compute the metric value for a single exact date.
    Returns None when data is absent or the metric cannot be computed.
    """
    if metric_type in _DAILY_COLS:
        daily = await _daily_row(db, tenant_id, om_user_id, d)
        if daily is None:
            return None
        raw = daily.get(metric_type)
        return Decimal(str(raw)) if raw is not None else None

    if metric_type == "revenue":
        if not display_names:
            return None
        rev = await _revenue_at(db, tenant_id, display_names, d)
        # 0-revenue is not useful as a baseline
        return rev if (rev is not None and rev > 0) else None

    if metric_type == "rpc":
        daily = await _daily_row(db, tenant_id, om_user_id, d)
        if daily is None:
            return None
        chats = daily.get("total_chats")
        if not chats or Decimal(str(chats)) == 0:
            return None
        if not display_names:
            return None
        rev = await _revenue_at(db, tenant_id, display_names, d)
        if rev is None:
            return None
        return rev / Decimal(str(chats))

    logger.warning("case_baseline: unknown metric_type '%s'", metric_type)
    return None


# ── Public API ────────────────────────────────────────────────────────────────

async def read_metric_at_date(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date,
) -> Optional[Decimal]:
    """
    Point-in-time metric read for an exact date.
    Used for guardrail baseline reconstruction — no look-back.
    """
    names = await _display_names(db, tenant_id, om_user_id)
    return await _compute_metric(db, tenant_id, om_user_id, metric_type, target_date, names)


async def freeze_baseline(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
) -> tuple[Decimal, date, str] | None:
    """
    Find the most recent day with data, scanning from yesterday up to
    BASELINE_LOOKBACK_DAYS back.

    Returns
    -------
    (metric_value, snapshot_date, source) on success, or None if no data found.
    """
    names = await _display_names(db, tenant_id, om_user_id)

    for days_back in range(1, BASELINE_LOOKBACK_DAYS + 1):
        target = date.today() - timedelta(days=days_back)
        try:
            val = await _compute_metric(db, tenant_id, om_user_id, metric_type, target, names)
            if val is not None:
                logger.info(
                    "freeze_baseline: tenant=%s uid=%s metric=%s → %s @ %s (days_back=%s)",
                    tenant_id, om_user_id, metric_type, val, target, days_back,
                )
                return val, target, "system_from_daily"
        except Exception as exc:
            logger.warning(
                "freeze_baseline error tenant=%s uid=%s metric=%s date=%s: %s",
                tenant_id, om_user_id, metric_type, target, exc,
            )
            continue

    logger.warning(
        "freeze_baseline: no data in %s days — tenant=%s uid=%s metric=%s",
        BASELINE_LOOKBACK_DAYS, tenant_id, om_user_id, metric_type,
    )
    return None
