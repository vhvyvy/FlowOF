"""
KPI Admin Cabinet — case management service.

Public API
----------
    create_case(db, tenant_id, admin_id, om_user_id, chatter_display_name,
                metric_type, diagnosis_text, action_plan, priority='normal',
                case_type='quantitative', category=None)
        → AdminCase
        Quantitative: validate uniqueness, freeze baseline, create case.
        Qualitative: category required, no baseline, limit 5 open per admin.

    transition_stage(db, case_id, new_stage, *, user, changed_by, actor_id,
                     notes, comment, result, force, expected_from_stage)
        Validate FSM + permissions, update stage, append history.
        Owner transitions for qualitative awaiting_review. No commit.

    close_case(db, case_id, result, result_notes, changed_by, *, actor_id)
        Quantitative only. Mark closed_at / result, record ledger points.

Invariants enforced here
------------------------
- One open quantitative case per (tenant, om_user_id, metric_type).
- One open qualitative case per (tenant, om_user_id, category).
- Max 5 open qualitative cases per admin.
- Baseline always frozen by the system for quantitative (never supplied).
- tenant_id always comes from the server-side call, never from request body.
- case_ledger is append-only (no update/delete functions exist).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import is_admin, is_owner
from models import AdminCase, BaselineSnapshot, CaseLedger, CaseStageHistory, KpiConfig
from schema_patch import seed_default_kpi_config
from services.case_activities import create_activity
from services.case_baseline import BASELINE_LOOKBACK_DAYS, freeze_baseline
from services.case_ledger import record_event

if TYPE_CHECKING:
    from models import User

logger = logging.getLogger("flowof.admin_cases")

# ── Points constants (move to DB / kpi_config later) ─────────────────────────
CASE_POINTS: dict[str, float] = {
    "success_normal": 10.0,
    "success_high":   15.0,
    "failed":         -3.0,
    "cancelled":      -1.0,
    "guardrail":      -5.0,
    "qualitative_success": 5.0,
    "qualitative_failed":  -2.0,
}

QUALITATIVE_OPEN_LIMIT = 5
_COMMENT_MIN_LEN = 10
_COMMENT_MAX_LEN = 500
_CATEGORY_MAX_LEN = 100

# ── FSM per case type ─────────────────────────────────────────────────────────
_FSM_QUANTITATIVE: dict[str, list[str]] = {
    "detected":    ["in_progress", "cancelled"],
    "in_progress": ["hold", "cancelled"],
    "hold":        ["review_due", "cancelled"],
    "review_due":  ["closed"],
    "closed":      [],
    "cancelled":   [],
}

_FSM_QUALITATIVE: dict[str, list[str]] = {
    "detected":        ["in_progress", "cancelled"],
    "in_progress":     ["hold", "cancelled"],
    "hold":            ["awaiting_review", "cancelled"],
    "awaiting_review": ["closed", "in_progress"],
    "closed":          [],
    "cancelled":       [],
}

# ── Stages that represent "open" (block duplicate case creation) ──────────────
_OPEN_STAGES_QUANT: tuple[str, ...] = ("detected", "in_progress", "hold", "review_due")
_OPEN_STAGES_QUAL: tuple[str, ...] = ("detected", "in_progress", "hold", "awaiting_review")
_CLOSED_STAGES: frozenset[str] = frozenset({"closed", "cancelled"})

# ── Ledger event mapping for close results ────────────────────────────────────
_CLOSE_EVENT: dict[str, str] = {
    "success":   "case_closed_success",
    "failed":    "case_closed_failed",
    "cancelled": "case_cancelled",
    "guardrail": "guardrail_triggered",
}

_DB_RESULT: dict[str, str] = {
    "success":   "success",
    "failed":    "failed",
    "cancelled": "cancelled",
    "guardrail": "failed",
}


class StageConflictError(Exception):
    """Current stage does not match expected — map to HTTP 409."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fsm_for(case_type: str) -> dict[str, list[str]]:
    if case_type == "qualitative":
        return _FSM_QUALITATIVE
    return _FSM_QUANTITATIVE


def _open_stages_for(case_type: str) -> tuple[str, ...]:
    if case_type == "qualitative":
        return _OPEN_STAGES_QUAL
    return _OPEN_STAGES_QUANT


def _normalize_category(category: str) -> str:
    cleaned = (category or "").strip()
    if not cleaned or len(cleaned) > _CATEGORY_MAX_LEN:
        raise ValueError(
            f"Категория обязательна для качественного кейса "
            f"(1–{_CATEGORY_MAX_LEN} символов после обрезки пробелов)"
        )
    return cleaned


def _normalize_comment(comment: str) -> str:
    cleaned = (comment or "").strip()
    if len(cleaned) < _COMMENT_MIN_LEN or len(cleaned) > _COMMENT_MAX_LEN:
        raise ValueError(
            f"Комментарий обязателен ({_COMMENT_MIN_LEN}–{_COMMENT_MAX_LEN} символов)"
        )
    return cleaned


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


async def _assert_qualitative_limit(
    db: AsyncSession, admin_id: int
) -> None:
    """Raise ValueError (→ 422) if admin already has 5 open qualitative cases."""
    count = (
        await db.execute(
            select(func.count())
            .select_from(AdminCase)
            .where(
                AdminCase.admin_id == admin_id,
                AdminCase.case_type == "qualitative",
                AdminCase.stage.notin_(list(_CLOSED_STAGES)),
            )
        )
    ).scalar_one()
    if count >= QUALITATIVE_OPEN_LIMIT:
        raise ValueError(
            "Достигнут лимит: 5 открытых качественных кейсов. "
            "Закройте существующие перед созданием новых."
        )


async def _assert_no_open_quant_case(
    db: AsyncSession, tenant_id: int, om_user_id: str, metric_type: str
) -> None:
    existing = (
        await db.execute(
            select(AdminCase).where(
                AdminCase.tenant_id == tenant_id,
                AdminCase.om_user_id == om_user_id,
                AdminCase.metric_type == metric_type,
                AdminCase.case_type == "quantitative",
                AdminCase.stage.in_(list(_OPEN_STAGES_QUANT)),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            f"Уже есть открытый кейс (id={existing.id}, stage={existing.stage}) "
            f"по чаттеру {om_user_id!r} и метрике {metric_type!r}"
        )


async def _assert_no_open_qual_case(
    db: AsyncSession, tenant_id: int, om_user_id: str, category: str
) -> None:
    existing = (
        await db.execute(
            select(AdminCase).where(
                AdminCase.tenant_id == tenant_id,
                AdminCase.om_user_id == om_user_id,
                AdminCase.category == category,
                AdminCase.case_type == "qualitative",
                AdminCase.stage.in_(list(_OPEN_STAGES_QUAL)),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(
            f"Уже есть открытый качественный кейс (id={existing.id}, stage={existing.stage}) "
            f"по чаттеру {om_user_id!r} и категории {category!r}"
        )


def _build_notes(
    chatter_display_name: str,
    diagnosis_text: str,
    action_plan: str,
) -> Optional[str]:
    parts: list[str] = []
    if chatter_display_name:
        parts.append(f"Чаттер: {chatter_display_name}")
    if diagnosis_text:
        parts.append(f"Диагноз: {diagnosis_text}")
    if action_plan:
        parts.append(f"План: {action_plan}")
    return "\n".join(parts) or None


async def _append_history(
    db: AsyncSession,
    case_id: int,
    from_stage: Optional[str],
    to_stage: str,
    changed_by: str,
    notes: Optional[str] = None,
) -> None:
    history = CaseStageHistory(
        case_id=case_id,
        from_stage=from_stage,
        to_stage=to_stage,
        changed_at=datetime.utcnow(),
        changed_by=changed_by,
        notes=notes,
    )
    db.add(history)
    await db.flush()


# ── Public API ────────────────────────────────────────────────────────────────

async def create_case(
    db: AsyncSession,
    tenant_id: int,
    admin_id: int,
    om_user_id: str,
    chatter_display_name: str,
    diagnosis_text: str,
    action_plan: str,
    priority: str = "normal",
    hold_days: int = 21,
    *,
    case_type: str = "quantitative",
    category: Optional[str] = None,
    metric_type: Optional[str] = None,
) -> AdminCase:
    """
    Open a new KPI case in a single transaction.

    Quantitative: metric_type required, baseline frozen, uniqueness by metric.
    Qualitative: category required, no baseline, limit 5 open, uniqueness by category.
    """
    if case_type not in ("quantitative", "qualitative"):
        raise ValueError(f"Invalid case_type {case_type!r}")

    review_date = date.today() + timedelta(days=hold_days)
    notes = _build_notes(chatter_display_name, diagnosis_text, action_plan)

    if case_type == "qualitative":
        # Limit check BEFORE uniqueness / INSERT
        await _assert_qualitative_limit(db, admin_id)
        cat = _normalize_category(category or "")
        await _assert_no_open_qual_case(db, tenant_id, om_user_id, cat)

        case = AdminCase(
            tenant_id=tenant_id,
            admin_id=admin_id,
            om_user_id=om_user_id,
            case_type="qualitative",
            category=cat,
            metric_type=None,
            stage="detected",
            priority=priority,
            review_date=review_date,
            baseline_value=None,
            notes=notes,
        )
        db.add(case)
        await db.flush()

        await _append_history(db, case.id, None, "detected", "admin")
        await record_event(
            db,
            tenant_id=tenant_id,
            admin_id=admin_id,
            event_type="case_opened",
            points=0,
            case_id=case.id,
            notes=f"Качественный кейс: {cat}",
        )
        await db.commit()
        await db.refresh(case)
        logger.info(
            "create_case qualitative: tenant=%s admin=%s case=%s category=%s review=%s",
            tenant_id, admin_id, case.id, cat, review_date,
        )
        return case

    # ── quantitative ──────────────────────────────────────────────────────────
    if not metric_type:
        raise ValueError("metric_type обязателен для количественного кейса")
    if category:
        raise ValueError("category допустима только для качественных кейсов")

    await _assert_no_open_quant_case(db, tenant_id, om_user_id, metric_type)
    await _load_kpi_config(db, tenant_id, metric_type)

    baseline_result = await freeze_baseline(db, tenant_id, om_user_id, metric_type)
    if baseline_result is None:
        chatter_name = (chatter_display_name or "").strip() or om_user_id
        raise ValueError(
            f"Недостаточно данных для baseline: за последние {BASELINE_LOOKBACK_DAYS} дней "
            f"нет ни одной записи метрики {metric_type!r} у чаттера {chatter_name!r}. "
            f"Возможно, чаттер давно не работал или проблема с синком Onlymonster."
        )
    baseline_value, snapshot_date, snapshot_source = baseline_result

    case = AdminCase(
        tenant_id=tenant_id,
        admin_id=admin_id,
        om_user_id=om_user_id,
        case_type="quantitative",
        category=None,
        metric_type=metric_type,
        stage="detected",
        priority=priority,
        review_date=review_date,
        baseline_value=baseline_value,
        notes=notes,
    )
    db.add(case)
    await db.flush()

    snap = BaselineSnapshot(
        case_id=case.id,
        snapshot_type="baseline",
        metric_type=metric_type,
        metric_value=baseline_value,
        snapshot_date=snapshot_date,
        source=snapshot_source,
    )
    db.add(snap)
    await _append_history(db, case.id, None, "detected", "admin")
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
        "create_case quantitative: tenant=%s admin=%s case=%s metric=%s baseline=%s review=%s",
        tenant_id, admin_id, case.id, metric_type, baseline_value, review_date,
    )
    return case


async def transition_stage(
    db: AsyncSession,
    case_id: int,
    new_stage: str,
    *,
    user: Optional["User"] = None,
    changed_by: Optional[str] = None,
    actor_id: Optional[int] = None,
    notes: Optional[str] = None,
    comment: Optional[str] = None,
    result: Optional[str] = None,
    force: bool = False,
    expected_from_stage: Optional[str] = None,
) -> None:
    """
    Validate FSM + actor permissions, update stage, append CaseStageHistory.
    Does NOT commit.

    Pass ``user`` for admin/owner transitions (role from user, not case.admin_id).
    Pass ``changed_by='system'`` for cron (no user required).

    ``expected_from_stage``: if set and case.stage differs → StageConflictError (409).
    """
    case = await db.get(AdminCase, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    old_stage = case.stage
    case_type = case.case_type or "quantitative"

    if expected_from_stage is not None and old_stage != expected_from_stage:
        raise StageConflictError(
            f"Кейс {case_id} в стадии {old_stage!r}, ожидалась {expected_from_stage!r}"
        )

    # ── Resolve actor (owner branches set changed_by inline) ──────────────────
    history_changed_by: str
    if user is not None:
        if user.tenant_id != case.tenant_id:
            raise PermissionError("Доступ к кейсу другого агентства запрещён")
    elif changed_by == "system":
        history_changed_by = "system"
    elif changed_by == "admin":
        history_changed_by = "admin"
        if actor_id is None or actor_id != case.admin_id:
            raise PermissionError(
                f"Admin {actor_id} cannot move case {case_id} "
                f"belonging to admin {case.admin_id}"
            )
    elif changed_by == "owner":
        raise PermissionError("Owner transitions require user= argument")
    else:
        raise ValueError(f"Invalid changed_by {changed_by!r}")

    def _require_case_admin() -> None:
        if user is None or not is_admin(user) or user.id != case.admin_id:
            raise PermissionError(
                f"Admin {getattr(user, 'id', None)} cannot move case {case_id} "
                f"belonging to admin {case.admin_id}"
            )
        nonlocal history_changed_by
        history_changed_by = "admin"

    # ── Owner: qualitative awaiting_review → closed ───────────────────────────
    if (
        case_type == "qualitative"
        and old_stage == "awaiting_review"
        and new_stage == "closed"
    ):
        if user is None or not is_owner(user):
            raise PermissionError("Только владелец может закрыть качественный кейс на оценке")
        history_changed_by = "owner"
        if result not in ("success", "failed"):
            raise ValueError("result обязателен: 'success' или 'failed'")

        case.closed_at = datetime.utcnow()
        case.result = _DB_RESULT[result]
        case.stage = "closed"
        await db.flush()

        event_type = "qualitative_success" if result == "success" else "qualitative_failed"
        points = CASE_POINTS[event_type]
        await record_event(
            db,
            tenant_id=case.tenant_id,
            admin_id=case.admin_id,
            event_type=event_type,
            points=points,
            case_id=case_id,
            notes=notes or f"Оценка владельца: {result}",
        )
        await _append_history(
            db, case_id, old_stage, "closed", history_changed_by,
            notes=notes or f"result={result}",
        )
        logger.info(
            "transition_stage qualitative close: case=%s result=%s points=%+g",
            case_id, result, points,
        )
        return

    # ── Owner: qualitative awaiting_review → in_progress (return) ─────────────
    if (
        case_type == "qualitative"
        and old_stage == "awaiting_review"
        and new_stage == "in_progress"
    ):
        if user is None or not is_owner(user):
            raise PermissionError("Только владелец может вернуть кейс на доработку")
        history_changed_by = "owner"
        body = _normalize_comment(comment or "")

        case.stage = "in_progress"
        await db.flush()

        await record_event(
            db,
            tenant_id=case.tenant_id,
            admin_id=case.admin_id,
            event_type="returned_for_revision",
            points=0,
            case_id=case_id,
            notes=body,
        )
        await _append_history(
            db, case_id, old_stage, "in_progress", history_changed_by, notes=body,
        )
        await create_activity(
            db,
            tenant_id=case.tenant_id,
            case_id=case_id,
            admin_id=user.id,
            activity_type="note",
            text=f"Возврат на доработку от владельца: {body}",
            system_note=True,
        )
        logger.info("transition_stage qualitative return: case=%s", case_id)
        return

    # ── Admin: qualitative hold → awaiting_review ─────────────────────────────
    if (
        case_type == "qualitative"
        and old_stage == "hold"
        and new_stage == "awaiting_review"
    ):
        _require_case_admin()
        today = date.today()
        if case.review_date is None or today < case.review_date:
            raise ValueError(
                "Дождитесь окончания HOLD-периода перед отправкой на оценку"
            )

    # ── Admin-only transitions (quant + qual admin paths) ─────────────────────
    if user is not None:
        _require_case_admin()

    # ── FSM check ─────────────────────────────────────────────────────────────
    if not force:
        allowed = _fsm_for(case_type).get(old_stage, [])
        if new_stage not in allowed:
            if old_stage == new_stage:
                raise StageConflictError(
                    f"Кейс {case_id} уже в стадии {old_stage!r}"
                )
            raise ValueError(
                f"Transition {old_stage!r} → {new_stage!r} is not allowed. "
                f"Valid next stages: {allowed}"
            )

    case.stage = new_stage
    await db.flush()
    await _append_history(
        db, case_id, old_stage, new_stage, history_changed_by, notes=notes,
    )
    logger.info(
        "transition_stage: case=%s %s → %s by=%s actor=%s",
        case_id, old_stage, new_stage, history_changed_by,
        user.id if user else actor_id,
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
    Close a quantitative case with the given result.  Does NOT commit.
    Qualitative cases must use transition_stage (awaiting_review → closed).
    """
    valid_results = frozenset({"success", "failed", "cancelled", "guardrail"})
    if result not in valid_results:
        raise ValueError(f"Invalid result {result!r}. Must be one of {sorted(valid_results)}")

    case = await db.get(AdminCase, case_id)
    if case is None:
        raise ValueError(f"Case {case_id} not found")

    if (case.case_type or "quantitative") == "qualitative":
        raise ValueError(
            "Качественные кейсы закрываются только через оценку владельца "
            "(awaiting_review → closed)"
        )

    closeable_stages = frozenset({"detected", "in_progress", "hold", "review_due"})
    if case.stage not in closeable_stages:
        raise ValueError(
            f"Cannot close case {case_id}: current stage is {case.stage!r}"
        )

    if result_notes:
        sep = "\n---\n" if case.notes else ""
        case.notes = f"{case.notes or ''}{sep}Закрытие: {result_notes}"

    case.closed_at = datetime.utcnow()
    case.result = _DB_RESULT[result]
    await db.flush()

    needs_force = case.stage != "review_due"
    await transition_stage(
        db, case_id, "closed",
        changed_by=changed_by,
        actor_id=actor_id,
        notes=f"Closed with result={result}",
        force=needs_force,
    )

    cfg_q = select(KpiConfig).where(
        KpiConfig.tenant_id == case.tenant_id,
        KpiConfig.metric_type == case.metric_type,
    )
    cfg = (await db.execute(cfg_q)).scalar_one_or_none()

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


# Backward-compatible alias for routers importing _OPEN_STAGES
_OPEN_STAGES = _OPEN_STAGES_QUANT
