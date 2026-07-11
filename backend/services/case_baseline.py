"""
Freeze baseline for KPI Admin cases.

Public API
----------
    find_baseline_value(db, tenant_id, om_user_id, metric_type, lookback_days=30)
        → tuple[Decimal, date] | None   # read-only search, no DB writes

    freeze_baseline(db, tenant_id, om_user_id, metric_type, lookback_days=30)
        → tuple[Decimal, date, str] | None   # wraps find_baseline_value + logs

    read_metric_at_date(db, tenant_id, om_user_id, metric_type, target_date)
        → Decimal | None
        Point-in-time read (no look-back).  Used by check_review_due_cases
        for guardrail baseline reconstruction.

    collect_baseline_snapshot_v2(db, tenant_id, om_user_id, metric_type, target_date)
        → BaselineSnapshotV2Result | None
        Collects 4 values + create-time flags at case creation.

    collect_metric_snapshot_v2 / collect_review_snapshot_v2
        → MetricSnapshotV2Values | None
        Shared 4-value collection for baseline and HOLD review.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.kpi_service import get_chatter_kpi

logger = logging.getLogger("flowof.case_baseline")

# Days to scan backward from yesterday when freezing baseline at case creation
BASELINE_LOOKBACK_DAYS = 30

# Metrics stored directly in chatter_kpi_daily
_DAILY_COLS: frozenset[str] = frozenset({"ppv_open_rate", "apv", "total_chats"})

_METRIC_KPI_ATTR: dict[str, str] = {
    "ppv_open_rate": "ppv_open_rate",
    "apv": "apv",
    "rpc": "rpc",
    "total_chats": "total_chats",
    "revenue": "revenue",
}


@dataclass
class MetricSnapshotV2Values:
    """Four metric values at a single point in time (no create-time flags)."""

    daily_value: Decimal | None
    daily_date: date | None
    week_avg_value: Decimal | None
    month_current_value: Decimal | None
    prev_month_value: Decimal | None
    snapshot_as_of: date


@dataclass
class BaselineSnapshotV2Result:
    """Four-value baseline snapshot collected at case creation."""

    daily_value: Decimal | None
    daily_date: date | None
    week_avg_value: Decimal | None
    month_current_value: Decimal | None
    prev_month_value: Decimal | None
    snapshot_as_of: date
    is_early_month: bool
    is_new_chatter: bool


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


async def _find_daily_at_anchor(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date,
    *,
    lookback_days: int = BASELINE_LOOKBACK_DAYS,
) -> tuple[Decimal, date] | None:
    """Most recent daily point scanning backward from target_date - 1 day."""
    names = await _display_names(db, tenant_id, om_user_id)

    for days_back in range(1, lookback_days + 1):
        d = target_date - timedelta(days=days_back)
        try:
            val = await _compute_metric(db, tenant_id, om_user_id, metric_type, d, names)
            if val is not None:
                return val, d
        except Exception as exc:
            logger.warning(
                "_find_daily_at_anchor error tenant=%s uid=%s metric=%s date=%s: %s",
                tenant_id, om_user_id, metric_type, d, exc,
            )
            continue

    return None


async def _week_avg_at_anchor(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date,
    *,
    days: int = 7,
) -> Decimal | None:
    """Average of non-null daily metric values for the `days` days before target_date."""
    names = await _display_names(db, tenant_id, om_user_id)
    vals: list[Decimal] = []

    for days_back in range(1, days + 1):
        d = target_date - timedelta(days=days_back)
        try:
            val = await _compute_metric(db, tenant_id, om_user_id, metric_type, d, names)
            if val is not None:
                vals.append(val)
        except Exception as exc:
            logger.warning(
                "_week_avg_at_anchor error tenant=%s uid=%s metric=%s date=%s: %s",
                tenant_id, om_user_id, metric_type, d, exc,
            )

    if not vals:
        return None
    return sum(vals) / Decimal(len(vals))


async def _monthly_metric_from_kpi(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    year: int,
    month: int,
) -> Decimal | None:
    """
    Monthly aggregate for one chatter — same source as get_case month_metric
    (get_chatter_kpi → chatter_kpi_mt + transactions).
    """
    attr = _METRIC_KPI_ATTR.get(metric_type)
    if not attr:
        return None
    try:
        kpi_rows, _, _, _ = await get_chatter_kpi(db, tenant_id, year, month)
        row = next((r for r in kpi_rows if r.onlymonster_id == om_user_id), None)
        if row is None:
            return None
        raw = getattr(row, attr, None)
        return Decimal(str(raw)) if raw is not None else None
    except Exception as exc:
        logger.warning(
            "_monthly_metric_from_kpi error tenant=%s uid=%s metric=%s %s-%s: %s",
            tenant_id, om_user_id, metric_type, year, month, exc,
        )
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


async def find_baseline_value(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    *,
    lookback_days: int = BASELINE_LOOKBACK_DAYS,
) -> tuple[Decimal, date] | None:
    """
    Find the most recent day with metric data, scanning from yesterday up to
    lookback_days back. Read-only — does not write to the database.
    """
    names = await _display_names(db, tenant_id, om_user_id)

    for days_back in range(1, lookback_days + 1):
        target = date.today() - timedelta(days=days_back)
        try:
            val = await _compute_metric(db, tenant_id, om_user_id, metric_type, target, names)
            if val is not None:
                return val, target
        except Exception as exc:
            logger.warning(
                "find_baseline_value error tenant=%s uid=%s metric=%s date=%s: %s",
                tenant_id, om_user_id, metric_type, target, exc,
            )
            continue

    logger.warning(
        "find_baseline_value: no data in %s days — tenant=%s uid=%s metric=%s",
        lookback_days, tenant_id, om_user_id, metric_type,
    )
    return None


async def freeze_baseline(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    *,
    lookback_days: int = BASELINE_LOOKBACK_DAYS,
) -> tuple[Decimal, date, str] | None:
    """
    Find baseline via find_baseline_value and return with source tag for snapshots.
    """
    result = await find_baseline_value(
        db, tenant_id, om_user_id, metric_type, lookback_days=lookback_days
    )
    if result is None:
        return None
    val, target = result
    logger.info(
        "freeze_baseline: tenant=%s uid=%s metric=%s → %s @ %s",
        tenant_id, om_user_id, metric_type, val, target,
    )
    return val, target, "system_from_daily"


async def collect_metric_snapshot_v2(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date,
) -> MetricSnapshotV2Values | None:
    """
    Collect 4 metric values anchored to target_date.
    Returns None when daily_value cannot be found (30-day lookback).
    Shared by baseline (create) and review (HOLD check) flows.
    """
    daily_result = await _find_daily_at_anchor(
        db, tenant_id, om_user_id, metric_type, target_date
    )
    daily_value: Decimal | None = None
    daily_date: date | None = None
    if daily_result is not None:
        daily_value, daily_date = daily_result

    if daily_value is None:
        logger.warning(
            "collect_metric_snapshot_v2: no daily data — tenant=%s uid=%s metric=%s as_of=%s",
            tenant_id, om_user_id, metric_type, target_date,
        )
        return None

    week_avg_value = await _week_avg_at_anchor(
        db, tenant_id, om_user_id, metric_type, target_date
    )

    year, month = target_date.year, target_date.month
    month_current_value = await _monthly_metric_from_kpi(
        db, tenant_id, om_user_id, metric_type, year, month
    )

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    prev_month_value = await _monthly_metric_from_kpi(
        db, tenant_id, om_user_id, metric_type, prev_year, prev_month
    )

    return MetricSnapshotV2Values(
        daily_value=daily_value,
        daily_date=daily_date,
        week_avg_value=week_avg_value,
        month_current_value=month_current_value,
        prev_month_value=prev_month_value,
        snapshot_as_of=target_date,
    )


async def collect_baseline_snapshot_v2(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date,
) -> BaselineSnapshotV2Result | None:
    """
    Collect 4 baseline values anchored to target_date.
    Returns None when daily_value cannot be found (30-day lookback).
    """
    values = await collect_metric_snapshot_v2(
        db, tenant_id, om_user_id, metric_type, target_date
    )
    if values is None:
        return None

    is_early_month = target_date.day <= 7
    is_new_chatter = values.prev_month_value is None

    logger.info(
        "collect_baseline_snapshot_v2: tenant=%s uid=%s metric=%s as_of=%s "
        "daily=%s week_avg=%s month=%s prev_month=%s early=%s new=%s",
        tenant_id, om_user_id, metric_type, target_date,
        values.daily_value, values.week_avg_value, values.month_current_value,
        values.prev_month_value, is_early_month, is_new_chatter,
    )

    return BaselineSnapshotV2Result(
        daily_value=values.daily_value,
        daily_date=values.daily_date,
        week_avg_value=values.week_avg_value,
        month_current_value=values.month_current_value,
        prev_month_value=values.prev_month_value,
        snapshot_as_of=values.snapshot_as_of,
        is_early_month=is_early_month,
        is_new_chatter=is_new_chatter,
    )


async def collect_review_snapshot_v2(
    db: AsyncSession,
    tenant_id: int,
    om_user_id: str,
    metric_type: str,
    target_date: date | None = None,
) -> MetricSnapshotV2Values | None:
    """Symmetric 4-value snapshot at review time (same helpers as baseline v2)."""
    as_of = target_date or date.today()
    result = await collect_metric_snapshot_v2(
        db, tenant_id, om_user_id, metric_type, as_of
    )
    if result is not None:
        logger.info(
            "collect_review_snapshot_v2: tenant=%s uid=%s metric=%s as_of=%s "
            "daily=%s week_avg=%s month=%s prev_month=%s",
            tenant_id, om_user_id, metric_type, as_of,
            result.daily_value, result.week_avg_value,
            result.month_current_value, result.prev_month_value,
        )
    return result
