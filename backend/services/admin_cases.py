"""
KPI Admin Cabinet — case management service.

Public API
----------
    create_case(db, tenant_id, admin_id, om_user_id, chatter_display_name,
                metric_type, diagnosis_text, action_plan, priority='normal')
        → AdminCase
        Full pipeline: validate uniqueness, freeze baseline, create case +
        baseline snapshot + history entry + ledger entry, commit.

    transition_stage(db, case_id, new_stage, changed_by, *, actor_id, notes, force)
        Validate FSM + permissions, update stage, append history.
        No commit — caller's responsibility.

    close_case(db, case_id, result, result_notes, changed_by, *, actor_id)
        Mark closed_at / result, move stage → 'closed', record ledger points.
        No commit — caller's responsibility.

Invariants enforced here
------------------------
- One open case per (tenant, om_user_id, metric_type).
- Baseline always frozen by the system (never supplied by caller).
- tenant_id always comes from the server-side call, never from request body.
- case_ledger is append-only (no update/delete functions exist).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AdminCase, BaselineSnapshot, CaseLedger, CaseStageHistory, KpiConfig
from schema_patch import seed_default_kpi_config
from services.case_baseline import freeze_baseline
from services.case_ledger import record_event

logger = logging.getLogger("flowof.admin_cases")

# ── Points constants (move to DB / kpi_config later) ─────────────────────────
CASE_POINTS: dict[str, float] = {
    "success_normal": 10.0,
    "success_high":   15.0,
    "failed":         -3.0,
    "cancelled":      -1.0,
    "guardrail":      -5.0,
}

# ── FSM: allowed transitions per source stage ────────────────────────────────
_FSM: dict[str, list[str]] = {
    "detected":    ["in_progress", "cancelled"],
    "in_progress": ["hold", "cancelled"],
    "hold":        ["review_due", "cancelled"],
    "review_due":  ["closed"],
    "closed":      [],
    "cancelled":   [],
}

# ── Stages that represent "open" (block duplicate case creation) ──────────────
_OPEN_STAGES: tuple[str, ...] = ("detected", "in_progress", "hold", "review_due")

# ── Ledger event mapping for close results ────────────────────────────────────
_CLOSE_EVENT: dict[str, str] = {
    "success":   "case_closed_success",
    "failed":    "case_closed_failed",
    "cancelled": "case_cancelled",
    "guardrail": "guardrail_triggered",
}

# When storing guardrail result in the DB, map to a valid case_result enum value
_DB_RESULT: dict[str, str] = {
    "success":   "success",
    "failed":    "failed",
    "cancelled": "cancelled",
    "guardrail": "failed",   # guardrail is differentiated only by ledger event_type
}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _load_kpi_config(
    db: AsyncSession, tenant_id: int, metric_type: str
) -> KpiConfig:
    """Return KpiConfig for the metric; seed defaults if missing."""
    q = select(KpiConfig).where(
        KpiConfig.tenant_id == tenant_id,
        KpiConfig.metric_type == metric_type,
    )
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        await seed_default_kpi_config(db, tenant_id)
        row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        raise RuntimeError(
            f"kpi_config missing for tenant={tenant_id} metric={metric_type} "
            "even after seeding defaults"
        )
    return row


async def _assert_no_open_case(
    db: AsyncSession, tenant_id: int, om_user_id: str, metric_type: str
) -> None:
    """Raise ValueError if an open case already exists."""
    existing = (
        await db.execute(
            select(AdminCase).where(
                AdminCase.tenant_id == tenant_id,
                AdminCase.om_user_id == om_user_id,
                AdminCase.metric_type == metric_type,
                AdminCase.stage.in_(list(_OPEN_STAGES)),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            f"Уже есть открытый кейс (id={existing.id}, stage={existing.stage}) "
            f"по чаттеру {om_user_id!r} и метрике {metric_type!r}"
        )


# ── Public API ────────────────────────────────────────────────────────────────

async def create_case(
    db: AsyncSession,
    tenant_id: int,
    admin_id: int,
    om_user_id: str,
    chatter_display_name: str,
    metric_type: str,
    diagnosis_text: str,
    action_plan: str,
    priority: str = "normal",
    hold_days: int = 21,
) -> AdminCase:
    """
    Open a new KPI case in a single transaction.

    Steps
    -----
    1. Validate uniqueness — raise ValueError (→ 409) if open case exists.
    2. Load kpi_config; seed defaults if absent.
    3. Freeze baseline — raise ValueError (→ 422) if no data in 7 days.
    4. Compute review_date = today + hold_days.
    5. Create AdminCase (stage='detected').
    6. Attach BaselineSnapshot.
    7. Insert CaseStageHistory (from_stage=None → 'detected').
    8. Insert CaseLedger event_type='case_opened', points=0.
    9. Commit.
    """
    # 1. Uniqueness check
    await _assert_no_open_case(db, tenant_id, om_user_id, metric_type)

    # 2. KPI config
    cfg = await _load_kpi_config(db, tenant_id, metric_type)

    # 3. Freeze baseline
    baseline_result = await freeze_baseline(db, tenant_id, om_user_id, metric_type)
    if baseline_result is None:
        raise ValueError(
            f"Недостаточно данных для baseline: "
            f"за последние 7 дней нет метрики {metric_type!r} у чаттера {om_user_id!r}"
        )
    baseline_value, snapshot_date, snapshot_source = baseline_result

    # 4. review_date — set by caller (admin's choice), kpi_config.hold_days is UI default only
    review_date = date.today() + timedelta(days=hold_days)

    # 5. Build notes from diagnosis + action plan
    parts: list[str] = []
    if chatter_display_name:
        parts.append(f"Чаттер: {chatter_display_name}")
    if diagnosis_text:
        parts.append(f"Диагноз: {diagnosis_text}")
    if action_plan:
        parts.append(f"План: {action_plan}")
    notes = "\n".join(parts) or None

    # 6. Create case
    case = AdminCase(
        tenant_id=tenant_id,
        admin_id=admin_id,
        om_user_id=om_user_id,
        metric_type=metric_type,
        stage="detected",
        priority=priority,
        review_date=review_date,
        baseline_value=baseline_value,
        notes=notes,
    )
    db.add(case)
    await db.flush()  # populate case.id

    # 7. Baseline snapshot
    snap = BaselineSnapshot(
        case_id=case.id,
        snapshot_type="baseline",
        metric_type=metric_type,
        metric_value=baseline_value,
        snapshot_date=snapshot_date,
        source=snapshot_source,
    )
    db.add(snap)

    # 8. Stage history
    history = CaseStageHistory(
        case_id=case.id,
        from_stage=None,
        to_stage="detected",
        changed_by="admin",
        notes=None,
    )
    db.add(history)

    # 9. Ledger
    await record_event(
        db,
        tenant_id=tenant_id,
        admin_id=admin_id,
        event_type="case_opened",
        points=0,
        case_id=case.id,
        notes=f"Диагноз: {metric_type}",
    )

    await db.commit()
    await db.refresh(case)
    logger.info(
        "create_case: tenant=%s admin=%s case=%s metric=%s baseline=%s review=%s",
        tenant_id, admin_id, case.id, metric_type, baseline_value, review_date,
    )
    return case


async def transition_stage(
    db: AsyncSession,
    case_id: int,
    new_stage: str,
    changed_by: str,
    *,
    actor_id: Optional[int] = None,
    notes: Optional[str] = None,
    force: bool = False,
) -> None:
    """
    Validate FSM + actor permissions, update stage, append CaseStageHistory.
    Does NOT commit.

    Parameters
    ----------
    force : bool
        If True, skip FSM reachability check (used by close_case when
        closing directly from 'in_progress' or 'hold').
    """
    case = await db.get(AdminCase, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    old_stage = case.stage

    # Permission check
    if changed_by == "owner":
        raise PermissionError("Owner cannot move case stages")

    if changed_by == "admin":
        if actor_id is None or actor_id != case.admin_id:
            raise PermissionError(
                f"Admin {actor_id} cannot move case {case_id} "
                f"belonging to admin {case.admin_id}"
            )

    # FSM check
    if not force:
        allowed = _FSM.get(old_stage, [])
        if new_stage not in allowed:
            raise ValueError(
                f"Transition {old_stage!r} → {new_stage!r} is not allowed. "
                f"Valid next stages: {allowed}"
            )

    case.stage = new_stage
    await db.flush()

    history = CaseStageHistory(
        case_id=case_id,
        from_stage=old_stage,
        to_stage=new_stage,
        changed_at=datetime.utcnow(),
        changed_by=changed_by,
        notes=notes,
    )
    db.add(history)
    await db.flush()

    logger.info(
        "transition_stage: case=%s %s → %s by=%s actor=%s",
        case_id, old_stage, new_stage, changed_by, actor_id,
    )


async def close_case(
    db: AsyncSession,
    case_id: int,
    result: str,
    result_notes: str,
    changed_by: str,
    *,
    actor_id: Optional[int] = None,
) -> AdminCase:
    """
    Close a case with the given result.  Does NOT commit.

    Parameters
    ----------
    result : str
        One of 'success', 'failed', 'cancelled', 'guardrail'.
    """
    valid_results = frozenset({"success", "failed", "cancelled", "guardrail"})
    if result not in valid_results:
        raise ValueError(f"Invalid result {result!r}. Must be one of {sorted(valid_results)}")

    case = await db.get(AdminCase, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    closeable_stages = frozenset({"detected", "in_progress", "hold", "review_due"})
    if case.stage not in closeable_stages:
        raise ValueError(
            f"Cannot close case {case_id}: current stage is {case.stage!r}"
        )

    # Append result notes to existing notes
    if result_notes:
        sep = "\n---\n" if case.notes else ""
        case.notes = f"{case.notes or ''}{sep}Закрытие: {result_notes}"

    case.closed_at = datetime.utcnow()
    case.result = _DB_RESULT[result]
    await db.flush()

    # Move stage → 'closed'
    # FSM only allows review_due → closed directly; force for other stages
    needs_force = case.stage != "review_due"
    await transition_stage(
        db, case_id, "closed", changed_by,
        actor_id=actor_id,
        notes=f"Closed with result={result}",
        force=needs_force,
    )

    # Load kpi_config for this metric to resolve points variant
    cfg_q = select(KpiConfig).where(
        KpiConfig.tenant_id == case.tenant_id,
        KpiConfig.metric_type == case.metric_type,
    )
    cfg = (await db.execute(cfg_q)).scalar_one_or_none()

    # Determine points
    if result == "success":
        variant = "success_high" if case.priority == "high" else "success_normal"
        points = CASE_POINTS[variant]
    else:
        points = CASE_POINTS[result]

    event_type = _CLOSE_EVENT[result]
    await record_event(
        db,
        tenant_id=case.tenant_id,
        admin_id=case.admin_id,
        event_type=event_type,
        points=points,
        case_id=case_id,
        notes=result_notes or None,
    )

    logger.info(
        "close_case: case=%s result=%s points=%+g event=%s",
        case_id, result, points, event_type,
    )
    return case
