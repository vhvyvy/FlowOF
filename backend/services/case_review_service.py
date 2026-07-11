"""
KPI Admin Cabinet — daily HOLD review processor.

Public API
----------
    check_review_due_cases(db, tenant_id) → dict
        Process all cases with review_date <= today AND stage='hold'.
        Each case is handled in its own try/except so one failure
        never blocks the others.

Decision table per case
-----------------------
    1. No current data         → extend review_date +3 days (stay in hold)
    2. Guardrail metric dropped → close_case(result='guardrail')
    3. change_pct > 2×noise     → close_case(result='success'), priority='high' points
    4. change_pct > noise       → close_case(result='success'), priority='normal' points
    5. abs(change_pct) < noise  → move to review_due + result snapshot (noise, admin decides)
    6. change_pct < -noise      → move to review_due + result snapshot (fail, admin decides)

Points are awarded by close_case via case_ledger.record_event.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AdminCase, BaselineSnapshot, KpiConfig
from schema_patch import seed_default_kpi_config
from services.admin_cases import close_case, transition_stage
from services.case_baseline import freeze_baseline, read_metric_at_date

# Short window for HOLD review: current metric, not historical baseline search
REVIEW_LOOKBACK_DAYS = 7

logger = logging.getLogger("flowof.case_review")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_cfg(db: AsyncSession, tenant_id: int, metric_type: str) -> Optional[KpiConfig]:
    row = (
        await db.execute(
            select(KpiConfig).where(
                KpiConfig.tenant_id == tenant_id,
                KpiConfig.metric_type == metric_type,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        await seed_default_kpi_config(db, tenant_id)
        row = (
            await db.execute(
                select(KpiConfig).where(
                    KpiConfig.tenant_id == tenant_id,
                    KpiConfig.metric_type == metric_type,
                )
            )
        ).scalar_one_or_none()
    return row


async def _baseline_snapshot_value(
    db: AsyncSession, case_id: int, metric_type: str
) -> Optional[tuple[Decimal, date]]:
    """Return (metric_value, snapshot_date) for the 'baseline' snapshot of a case."""
    row = (
        await db.execute(
            select(BaselineSnapshot).where(
                BaselineSnapshot.case_id == case_id,
                BaselineSnapshot.snapshot_type == "baseline",
                BaselineSnapshot.metric_type == metric_type,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return Decimal(str(row.metric_value)), row.snapshot_date


async def _add_result_snapshot(
    db: AsyncSession, case: AdminCase, current_value: Decimal
) -> None:
    """Attach a 'result' snapshot to the case so the admin can see current state."""
    snap = BaselineSnapshot(
        case_id=case.id,
        snapshot_type="result",
        metric_type=case.metric_type,
        metric_value=current_value,
        snapshot_date=date.today(),
        source="system_from_daily",
    )
    db.add(snap)
    await db.flush()


def _change_pct(current: Decimal, baseline: Decimal) -> Decimal:
    """(current - baseline) / baseline * 100, or 0 when baseline is zero."""
    if baseline == 0:
        return Decimal("0")
    return ((current - baseline) / baseline * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _check_guardrails(
    db: AsyncSession,
    case: AdminCase,
    baseline_date: date,
    guardrail_metrics: list[str],
) -> bool:
    """
    Return True if any guardrail metric has dropped more than its own
    noise_threshold_pct compared to the baseline value on baseline_date.
    """
    for g_metric in guardrail_metrics:
        try:
            # Try to find a stored baseline snapshot for this guardrail metric
            g_baseline_row = await _baseline_snapshot_value(db, case.id, g_metric)
            if g_baseline_row is not None:
                g_baseline, g_snap_date = g_baseline_row
            else:
                # Fall back to point-in-time read for the original baseline date
                g_val = await read_metric_at_date(
                    db, case.tenant_id, case.om_user_id, g_metric, baseline_date
                )
                if g_val is None:
                    logger.debug(
                        "guardrail check skipped: no baseline for metric=%s case=%s",
                        g_metric, case.id,
                    )
                    continue
                g_baseline = g_val
                g_snap_date = baseline_date

            # Current guardrail metric value
            g_current_result = await freeze_baseline(
                db, case.tenant_id, case.om_user_id, g_metric,
                lookback_days=REVIEW_LOOKBACK_DAYS,
            )
            if g_current_result is None:
                logger.debug(
                    "guardrail check skipped: no current data for metric=%s case=%s",
                    g_metric, case.id,
                )
                continue
            g_current, *_ = g_current_result

            # Load noise threshold for the guardrail metric
            g_cfg = await _load_cfg(db, case.tenant_id, g_metric)
            g_noise = Decimal(str(g_cfg.noise_threshold_pct)) if g_cfg else Decimal("5")

            change = _change_pct(g_current, g_baseline)
            if change < -g_noise:
                logger.info(
                    "guardrail triggered: case=%s g_metric=%s change=%s noise=%s",
                    case.id, g_metric, change, g_noise,
                )
                return True

        except Exception as exc:
            logger.warning(
                "guardrail check error: case=%s g_metric=%s: %s", case.id, g_metric, exc
            )

    return False


# ── Public API ────────────────────────────────────────────────────────────────

async def check_review_due_cases(db: AsyncSession, tenant_id: int) -> dict:
    """
    Process all cases with review_date <= today AND stage='hold'.

    Each case runs in its own try/except with rollback on failure so
    one bad case never blocks the rest.

    Returns
    -------
    {
        "processed":       int,
        "closed_success":  int,
        "guardrail":       int,
        "extended":        int,   # extended review_date because no current data
        "needs_review":    int,   # moved to review_due, admin must decide
        "errors":          list[str],
    }
    """
    today = date.today()

    due_cases_result = await db.execute(
        select(AdminCase).where(
            AdminCase.tenant_id == tenant_id,
            AdminCase.case_type == "quantitative",
            AdminCase.stage == "hold",
            AdminCase.review_date <= today,
        )
    )
    due_cases: list[AdminCase] = list(due_cases_result.scalars().all())

    stats = {
        "processed":      0,
        "closed_success": 0,
        "guardrail":      0,
        "extended":       0,
        "needs_review":   0,
        "errors":         [],
    }

    for case in due_cases:
        stats["processed"] += 1
        try:
            # 1. Load baseline snapshot
            base = await _baseline_snapshot_value(db, case.id, case.metric_type)
            if base is None:
                raise ValueError(
                    f"No baseline snapshot for case={case.id} metric={case.metric_type}"
                )
            baseline_value, baseline_date = base

            # 2. Current metric value
            current_result = await freeze_baseline(
                db, case.tenant_id, case.om_user_id, case.metric_type,
                lookback_days=REVIEW_LOOKBACK_DAYS,
            )

            # 3. No current data in review window → review_due, admin decides
            if current_result is None:
                logger.warning(
                    "check_review: case=%s no metric data in %s-day window → review_due",
                    case.id, REVIEW_LOOKBACK_DAYS,
                )
                await transition_stage(
                    db, case.id, "review_due",
                    changed_by="system",
                    notes=(
                        f"Нет данных метрики за последние {REVIEW_LOOKBACK_DAYS} дней. "
                        "Требует решения администратора."
                    ),
                )
                await db.commit()
                stats["needs_review"] += 1
                continue

            current_value, *_ = current_result

            # 4. Load kpi_config
            cfg = await _load_cfg(db, case.tenant_id, case.metric_type)
            if cfg is None:
                raise ValueError(
                    f"kpi_config missing for tenant={case.tenant_id} metric={case.metric_type}"
                )
            noise = Decimal(str(cfg.noise_threshold_pct))
            guardrail_list: list[str] = cfg.guardrail_metrics or []

            # 5. Change in %
            change_pct = _change_pct(current_value, baseline_value)

            # 6. Guardrail check (highest priority — run before success check)
            if guardrail_list:
                triggered = await _check_guardrails(
                    db, case, baseline_date, guardrail_list
                )
                if triggered:
                    await close_case(
                        db, case.id,
                        result="guardrail",
                        result_notes=(
                            f"Guardrail triggered. Метрика {case.metric_type}: "
                            f"baseline={baseline_value} current={current_value} "
                            f"change={change_pct}%"
                        ),
                        changed_by="system",
                    )
                    await db.commit()
                    stats["guardrail"] += 1
                    continue

            # 7-8. Decision by change magnitude
            if change_pct > 2 * noise:
                # Clear success — high points
                # Temporarily mark priority=high so close_case awards +15
                case.priority = "high"
                await db.flush()
                await close_case(
                    db, case.id,
                    result="success",
                    result_notes=(
                        f"Значительное улучшение: {change_pct}% "
                        f"(порог {2 * noise}%)"
                    ),
                    changed_by="system",
                )
                await db.commit()
                stats["closed_success"] += 1

            elif change_pct > noise:
                # Normal success
                case.priority = "normal"
                await db.flush()
                await close_case(
                    db, case.id,
                    result="success",
                    result_notes=(
                        f"Улучшение: {change_pct}% (порог {noise}%)"
                    ),
                    changed_by="system",
                )
                await db.commit()
                stats["closed_success"] += 1

            elif change_pct > -noise:
                # Within noise band — move to review_due, admin decides
                await _add_result_snapshot(db, case, current_value)
                await transition_stage(
                    db, case.id, "review_due",
                    changed_by="system",
                    notes=(
                        f"Шум: изменение {change_pct}% в пределах порога {noise}%. "
                        "Требует решения администратора."
                    ),
                )
                await db.commit()
                stats["needs_review"] += 1

            else:
                # Negative change beyond noise — move to review_due, admin decides
                await _add_result_snapshot(db, case, current_value)
                await transition_stage(
                    db, case.id, "review_due",
                    changed_by="system",
                    notes=(
                        f"Ухудшение: {change_pct}% (порог -{noise}%). "
                        "Требует решения администратора."
                    ),
                )
                await db.commit()
                stats["needs_review"] += 1

        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass
            err_msg = f"case={case.id}: {exc}"
            stats["errors"].append(err_msg)
            logger.exception("check_review: error processing %s", err_msg)

    logger.info(
        "check_review_due_cases: tenant=%s %s",
        tenant_id, {k: v for k, v in stats.items() if k != "errors"},
    )
    return stats
