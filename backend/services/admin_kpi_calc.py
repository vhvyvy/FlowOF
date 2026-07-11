"""
KPI Admin Cabinet — monthly KPI snapshot calculator.

Public API
----------
    recalc_admin_kpi_snapshot(db, tenant_id, admin_id, year, month)
        Recompute admin_kpi_snapshot for the given period from ledger data.
        UPSERTs the result.  Commits.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import extract, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import AdminKpiSnapshot, CaseLedger, KpiConfig

logger = logging.getLogger("flowof.admin_kpi_calc")


async def recalc_admin_kpi_snapshot(
    db: AsyncSession,
    tenant_id: int,
    admin_id: int,
    year: int,
    month: int,
) -> AdminKpiSnapshot:
    """
    Aggregate ledger data for (tenant_id, admin_id, year, month) and
    UPSERT into admin_kpi_snapshot.

    Steps
    -----
    1. Count opened/closed-success/closed-failed/cancelled/guardrail events.
    2. Sum total ledger points for the period.
    3. detect_result_ratio = cases_opened / max(cases_closed_success, 1).
    4. If ratio > kpi_config.detect_to_result_ratio_min (revenue config):
       halve total_points (anti-farming penalty).
    5. is_calibration = first month AND first ledger event was < calibration_days ago.
    6. UPSERT admin_kpi_snapshot.
    7. Commit.
    """
    # ── 1. Aggregate event counts for the period ──────────────────────────────
    period_q = (
        select(CaseLedger)
        .where(
            CaseLedger.tenant_id == tenant_id,
            CaseLedger.admin_id == admin_id,
            extract("year",  CaseLedger.created_at) == year,
            extract("month", CaseLedger.created_at) == month,
        )
    )
    period_rows = (await db.execute(period_q)).scalars().all()

    counts: dict[str, int] = {
        "case_opened":           0,
        "case_closed_success":   0,
        "case_closed_failed":    0,
        "case_cancelled":        0,
        "guardrail_triggered":   0,
    }
    for row in period_rows:
        if row.event_type in counts:
            counts[row.event_type] += 1

    cases_opened         = counts["case_opened"]
    cases_closed_success = counts["case_closed_success"]
    cases_closed_failed  = counts["case_closed_failed"]
    cases_cancelled      = counts["case_cancelled"]
    guardrail_hits       = counts["guardrail_triggered"]

    # ── 2. Sum points ─────────────────────────────────────────────────────────
    total_points_raw: Decimal = sum(
        Decimal(str(r.points)) for r in period_rows
    )

    # ── 3. detect-to-result ratio ─────────────────────────────────────────────
    detect_result_ratio = Decimal(cases_opened) / max(Decimal(cases_closed_success), Decimal("1"))

    # ── 4. Anti-farming penalty ───────────────────────────────────────────────
    # Use kpi_config for 'revenue' metric to obtain detect_to_result_ratio_min
    cfg_row = (
        await db.execute(
            select(KpiConfig).where(
                KpiConfig.tenant_id == tenant_id,
                KpiConfig.metric_type == "revenue",
            )
        )
    ).scalar_one_or_none()

    ratio_min: int = cfg_row.detect_to_result_ratio_min if cfg_row else 15
    total_points = total_points_raw
    if detect_result_ratio > ratio_min:
        total_points = (total_points_raw / 2).quantize(Decimal("0.01"))
        logger.info(
            "recalc_kpi: anti-farming penalty tenant=%s admin=%s ratio=%.2f > %s → points halved",
            tenant_id, admin_id, detect_result_ratio, ratio_min,
        )

    # ── 5. is_calibration ────────────────────────────────────────────────────
    # First month = no earlier snapshots AND first ledger event < calibration_days ago
    calibration_days: int = cfg_row.calibration_days if cfg_row else 30

    earlier_snapshot = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == tenant_id,
                AdminKpiSnapshot.admin_id == admin_id,
                # Strictly earlier period
                (AdminKpiSnapshot.period_year * 100 + AdminKpiSnapshot.period_month)
                < (year * 100 + month),
            )
        )
    ).scalar_one_or_none()

    is_calibration = False
    if earlier_snapshot is None:
        # No earlier snapshot — check if admin's first ledger event is recent
        first_event_q = (
            select(CaseLedger.created_at)
            .where(
                CaseLedger.tenant_id == tenant_id,
                CaseLedger.admin_id == admin_id,
            )
            .order_by(CaseLedger.created_at.asc())
            .limit(1)
        )
        first_ts = (await db.execute(first_event_q)).scalar_one_or_none()
        if first_ts is not None:
            days_since_first = (datetime.utcnow() - first_ts).days
            is_calibration = days_since_first < calibration_days

    # ── 6. UPSERT ─────────────────────────────────────────────────────────────
    await db.execute(
        text(
            """
            INSERT INTO admin_kpi_snapshot
                (tenant_id, admin_id, period_year, period_month,
                 cases_opened, cases_closed_success, cases_closed_failed,
                 cases_cancelled, guardrail_hits, total_points,
                 detect_result_ratio, is_calibration)
            VALUES
                (:tid, :aid, :yr, :mo,
                 :opened, :cs, :cf,
                 :cc, :gh, :tp,
                 :dr, :ic)
            ON CONFLICT (tenant_id, admin_id, period_year, period_month)
            DO UPDATE SET
                cases_opened         = EXCLUDED.cases_opened,
                cases_closed_success = EXCLUDED.cases_closed_success,
                cases_closed_failed  = EXCLUDED.cases_closed_failed,
                cases_cancelled      = EXCLUDED.cases_cancelled,
                guardrail_hits       = EXCLUDED.guardrail_hits,
                total_points         = EXCLUDED.total_points,
                detect_result_ratio  = EXCLUDED.detect_result_ratio,
                is_calibration       = EXCLUDED.is_calibration
            """
        ),
        {
            "tid":    tenant_id,
            "aid":    admin_id,
            "yr":     year,
            "mo":     month,
            "opened": cases_opened,
            "cs":     cases_closed_success,
            "cf":     cases_closed_failed,
            "cc":     cases_cancelled,
            "gh":     guardrail_hits,
            "tp":     float(total_points),
            "dr":     float(detect_result_ratio),
            "ic":     is_calibration,
        },
    )
    await db.commit()

    logger.info(
        "recalc_admin_kpi_snapshot: tenant=%s admin=%s %04d-%02d "
        "opened=%s success=%s failed=%s cancelled=%s guardrail=%s "
        "points=%s ratio=%.2f calibration=%s",
        tenant_id, admin_id, year, month,
        cases_opened, cases_closed_success, cases_closed_failed,
        cases_cancelled, guardrail_hits,
        total_points, float(detect_result_ratio), is_calibration,
    )

    # Return a fresh snapshot object for the caller
    snap = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == tenant_id,
                AdminKpiSnapshot.admin_id == admin_id,
                AdminKpiSnapshot.period_year == year,
                AdminKpiSnapshot.period_month == month,
            )
        )
    ).scalar_one()
    return snap


async def nightly_recalc_all_tenant_snapshots() -> dict:
    """
    Recalc current-month admin_kpi_snapshot for every active admin in every
    tenant that has at least one is_admin user.  Used by scheduler cron.
    """
    import time
    from datetime import date

    from database import AsyncSessionLocal
    from models import User

    today = date.today()
    year, month = today.year, today.month
    totals = {"tenants": 0, "admins": 0, "errors": []}

    async with AsyncSessionLocal() as db:
        tenant_ids = list(
            (
                await db.execute(
                    select(User.tenant_id)
                    .where(User.is_admin == True)  # noqa: E712
                    .distinct()
                )
            ).scalars().all()
        )

    for tid in tenant_ids:
        t0 = time.monotonic()
        async with AsyncSessionLocal() as db:
            admins = (
                await db.execute(
                    select(User).where(
                        User.tenant_id == tid,
                        User.is_admin == True,  # noqa: E712
                        User.active == True,  # noqa: E712
                    )
                )
            ).scalars().all()

        n_done = 0
        for admin in admins:
            try:
                async with AsyncSessionLocal() as db:
                    await recalc_admin_kpi_snapshot(db, tid, admin.id, year, month)
                n_done += 1
            except Exception as exc:
                logger.exception(
                    "nightly_kpi_recalc failed tenant=%s admin=%s", tid, admin.id
                )
                totals["errors"].append(
                    {"tenant_id": tid, "admin_id": admin.id, "error": str(exc)}
                )

        elapsed = time.monotonic() - t0
        logger.info(
            "Nightly KPI recalc: tenant=%s, admins=%s, done in %.1fs",
            tid, n_done, elapsed,
        )
        totals["tenants"] += 1
        totals["admins"] += n_done

    return totals
