"""
Admins Review — обзор работы администраторов для владельца агентства.

Prefix  : /api/v1/dashboard/admins-review
Auth    : require_owner (User.role = 'owner')
tenant_id из user.tenant_id.

Эндпоинты
---------
GET  /admins                            — список админов + текущий KPI
GET  /admins/{admin_id}/cases           — кейсы конкретного админа
GET  /admins/{admin_id}/ledger          — ledger конкретного админа
GET  /admins/{admin_id}/kpi-history     — история снапшотов по месяцам
GET  /kpi-config                        — конфиг метрик
PUT  /kpi-config/{metric_type}          — обновить конфиг метрики
GET  /cases/{case_id}                   — детали качественного кейса (овнер)
GET  /cases/{case_id}/activities        — лента активностей кейса (read-only)
GET  /pending-qualitative               — качественные кейсы на оценке
POST /cases/{case_id}/close-qualitative — закрыть качественный кейс (success/failed)
POST /cases/{case_id}/return-for-revision — вернуть на доработку
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner
from models import (
    AdminCase, AdminKpiSnapshot, CaseActivity, CaseLedger,
    CaseStageHistory, ChatterMapping, KpiConfig, User,
)
from schemas import ActivityListOut
from schema_patch import seed_default_kpi_config
from services import admin_cases as svc_cases
from services import case_activities as svc_activities
from services import case_ledger as svc_ledger
from services.case_activities import CaseActivityNotFound, CaseActivityValidation
from services.admin_kpi_calc import recalc_admin_kpi_snapshot
from routers.admin_portal import (
    _activity_list_out,
    _build_activity_filters,
    _map_activity_err,
    _resolve_chatter_display_name,
    _svc_err,
)

logger = logging.getLogger("flowof.admins_review")
router = APIRouter(prefix="/api/v1/dashboard/admins-review", tags=["admins_review"])

MetricTypeLiteral = Literal["ppv_open_rate", "rpc", "apv", "total_chats", "revenue"]

_OPEN_STAGES = ("detected", "in_progress", "hold", "review_due", "awaiting_review")


# ── Owner qualitative case schemas ────────────────────────────────────────────

class CloseQualitativeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["success", "failed"]


class CloseQualitativeResponse(BaseModel):
    case_id: int
    new_stage: str
    result: str
    ledger_event: str
    points: float


class ReturnForRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=10, max_length=500)


class ReturnForRevisionResponse(BaseModel):
    case_id: int
    new_stage: str
    ledger_event: str = "returned_for_revision"
    activity_id: int


class PendingQualitativeAdmin(BaseModel):
    id: int
    name: str


class PendingQualitativeItem(BaseModel):
    id: int
    om_user_id: str
    chatter_display_name: str
    category: str
    diagnosis_text: str
    action_plan: str
    priority: str
    admin: PendingQualitativeAdmin
    hold_start_date: Optional[date] = None
    hold_end_date: Optional[date] = None
    sent_for_review_at: datetime
    activities_count: int


class PendingQualitativeList(BaseModel):
    items: list[PendingQualitativeItem]
    total: int


class StageHistoryItem(BaseModel):
    id: int
    from_stage: Optional[str]
    to_stage: str
    changed_at: datetime
    changed_by: str
    notes: Optional[str]

    @classmethod
    def from_orm(cls, h: CaseStageHistory) -> "StageHistoryItem":
        return cls(
            id=h.id,
            from_stage=h.from_stage,
            to_stage=h.to_stage,
            changed_at=h.changed_at,
            changed_by=h.changed_by,
            notes=h.notes,
        )


class OwnerQualitativeCaseDetail(BaseModel):
    id: int
    om_user_id: str
    chatter_display_name: str
    category: str
    diagnosis_text: str
    action_plan: str
    priority: str
    stage: str
    result: Optional[str]
    admin: PendingQualitativeAdmin
    hold_start_date: Optional[date] = None
    hold_end_date: Optional[date] = None
    sent_for_review_at: Optional[datetime] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    history: list[StageHistoryItem]
    ledger_points: Optional[float] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_case_notes(notes: Optional[str]) -> tuple[str, str]:
    diagnosis = ""
    plan = ""
    for line in (notes or "").split("\n"):
        if line.startswith("Диагноз: "):
            diagnosis = line[len("Диагноз: "):]
        elif line.startswith("План: "):
            plan = line[len("План: "):]
    return diagnosis, plan


async def _get_owner_case(
    db: AsyncSession, tenant_id: int, case_id: int
) -> AdminCase:
    """404 если кейс не в tenant (не раскрываем чужие кейсы)."""
    case = await db.get(AdminCase, case_id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кейс не найден")
    return case


async def _stage_entered_at(
    db: AsyncSession, case_id: int, stage: str
) -> Optional[datetime]:
    return (
        await db.execute(
            select(CaseStageHistory.changed_at)
            .where(
                CaseStageHistory.case_id == case_id,
                CaseStageHistory.to_stage == stage,
            )
            .order_by(CaseStageHistory.changed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _latest_ledger_for_case(
    db: AsyncSession, case_id: int, event_types: tuple[str, ...]
) -> Optional[CaseLedger]:
    return (
        await db.execute(
            select(CaseLedger)
            .where(
                CaseLedger.case_id == case_id,
                CaseLedger.event_type.in_(event_types),
            )
            .order_by(CaseLedger.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AdminKpiSummary(BaseModel):
    cases_opened: int = 0
    cases_closed_success: int = 0
    cases_closed_failed: int = 0
    cases_cancelled: int = 0
    guardrail_hits: int = 0
    total_points: float = 0.0
    detect_result_ratio: Optional[float] = None
    is_calibration: bool = False


class AdminListItem(BaseModel):
    id: int
    name: Optional[str]
    email: str
    admin_shift_id: Optional[int]
    shift_name: Optional[str]
    current_month_kpi: AdminKpiSummary
    open_cases_count: int


class CaseOut(BaseModel):
    id: int
    admin_id: int
    om_user_id: str
    metric_type: str
    stage: str
    priority: str
    result: Optional[str]
    opened_at: date
    closed_at: Optional[date]
    review_date: Optional[date]
    baseline_value: Optional[float]
    result_value: Optional[float]
    notes: Optional[str]

    @classmethod
    def from_orm(cls, c: AdminCase) -> "CaseOut":
        return cls(
            id=c.id,
            admin_id=c.admin_id,
            om_user_id=c.om_user_id,
            metric_type=c.metric_type,
            stage=c.stage,
            priority=c.priority,
            result=c.result,
            opened_at=c.opened_at.date() if hasattr(c.opened_at, "date") else c.opened_at,
            closed_at=c.closed_at.date() if c.closed_at and hasattr(c.closed_at, "date") else c.closed_at,
            review_date=c.review_date,
            baseline_value=float(c.baseline_value) if c.baseline_value is not None else None,
            result_value=float(c.result_value) if c.result_value is not None else None,
            notes=c.notes,
        )


class KpiConfigOut(BaseModel):
    id: int
    metric_type: str
    noise_threshold_pct: float
    guardrail_metrics: list[str]
    hold_days: int
    detect_to_result_ratio_min: int
    calibration_days: int

    @classmethod
    def from_orm(cls, k: KpiConfig) -> "KpiConfigOut":
        gm = k.guardrail_metrics
        if isinstance(gm, str):
            import json
            try:
                gm = json.loads(gm)
            except Exception:
                gm = []
        return cls(
            id=k.id,
            metric_type=k.metric_type,
            noise_threshold_pct=float(k.noise_threshold_pct),
            guardrail_metrics=gm or [],
            hold_days=k.hold_days,
            detect_to_result_ratio_min=k.detect_to_result_ratio_min,
            calibration_days=k.calibration_days,
        )


class KpiConfigUpdate(BaseModel):
    noise_threshold_pct: float = Field(gt=0, le=100)
    guardrail_metrics: list[str] = []
    hold_days: int = Field(gt=0)
    detect_to_result_ratio_min: int = Field(gt=0)
    calibration_days: int = Field(gt=0)


class KpiSnapshotHistoryItem(BaseModel):
    period_year: int
    period_month: int
    cases_opened: int
    cases_closed_success: int
    cases_closed_failed: int
    cases_cancelled: int
    guardrail_hits: int
    total_points: float
    detect_result_ratio: Optional[float]
    is_calibration: bool

    @classmethod
    def from_orm(cls, s: AdminKpiSnapshot) -> "KpiSnapshotHistoryItem":
        return cls(
            period_year=s.period_year,
            period_month=s.period_month,
            cases_opened=s.cases_opened,
            cases_closed_success=s.cases_closed_success,
            cases_closed_failed=s.cases_closed_failed,
            cases_cancelled=s.cases_cancelled,
            guardrail_hits=s.guardrail_hits,
            total_points=float(s.total_points),
            detect_result_ratio=float(s.detect_result_ratio) if s.detect_result_ratio is not None else None,
            is_calibration=s.is_calibration,
        )


# ── GET /admins ───────────────────────────────────────────────────────────────

@router.get("/admins", response_model=list[AdminListItem])
async def list_admins(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """
    Список всех администраторов агентства с KPI текущего месяца и
    количеством открытых кейсов.
    """
    tid = current_user.tenant_id
    today = date.today()
    year, month = today.year, today.month

    # All admins in this tenant
    admins = (
        await db.execute(
            select(User).where(
                User.tenant_id == tid,
                User.is_admin == True,  # noqa: E712
                User.active == True,    # noqa: E712
            )
        )
    ).scalars().all()

    if not admins:
        return []

    admin_ids = [a.id for a in admins]

    # Current month KPI snapshots
    snaps_rows = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == tid,
                AdminKpiSnapshot.admin_id.in_(admin_ids),
                AdminKpiSnapshot.period_year == year,
                AdminKpiSnapshot.period_month == month,
            )
        )
    ).scalars().all()
    snaps: dict[int, AdminKpiSnapshot] = {s.admin_id: s for s in snaps_rows}

    # Open case counts per admin
    open_counts_rows = (
        await db.execute(
            text(
                """
                SELECT admin_id, COUNT(*) AS cnt
                FROM admin_cases
                WHERE tenant_id = :tid
                  AND admin_id = ANY(:ids)
                  AND stage = ANY(:stages)
                GROUP BY admin_id
                """
            ),
            {"tid": tid, "ids": admin_ids, "stages": list(_OPEN_STAGES)},
        )
    ).fetchall()
    open_counts: dict[int, int] = {r[0]: int(r[1]) for r in open_counts_rows}

    # Shift names via shift catalog
    shift_names_rows = (
        await db.execute(
            text("SELECT id, name FROM shifts_catalog WHERE tenant_id = :tid"),
            {"tid": tid},
        )
    ).fetchall()
    shift_map: dict[int, str] = {r[0]: r[1] for r in shift_names_rows}

    items: list[AdminListItem] = []
    for admin in admins:
        snap = snaps.get(admin.id)
        kpi = AdminKpiSummary(
            cases_opened=snap.cases_opened if snap else 0,
            cases_closed_success=snap.cases_closed_success if snap else 0,
            cases_closed_failed=snap.cases_closed_failed if snap else 0,
            cases_cancelled=snap.cases_cancelled if snap else 0,
            guardrail_hits=snap.guardrail_hits if snap else 0,
            total_points=float(snap.total_points) if snap else 0.0,
            detect_result_ratio=float(snap.detect_result_ratio) if snap and snap.detect_result_ratio is not None else None,
            is_calibration=snap.is_calibration if snap else False,
        )
        admin_shift_id = getattr(admin, "admin_shift_id", None)
        items.append(
            AdminListItem(
                id=admin.id,
                name=admin.full_name,
                email=admin.email,
                admin_shift_id=admin_shift_id,
                shift_name=shift_map.get(admin_shift_id) if admin_shift_id else None,
                current_month_kpi=kpi,
                open_cases_count=open_counts.get(admin.id, 0),
            )
        )

    return items


# ── GET /admins/{admin_id}/cases ──────────────────────────────────────────────

@router.get("/admins/{admin_id}/cases", response_model=list[CaseOut])
async def admin_cases(
    admin_id: int,
    stage: Optional[str] = Query(None),
    include_closed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Все кейсы конкретного администратора (только чтение)."""
    tid = current_user.tenant_id

    q = select(AdminCase).where(
        AdminCase.tenant_id == tid,
        AdminCase.admin_id == admin_id,
    )
    if stage:
        q = q.where(AdminCase.stage == stage)
    elif not include_closed:
        q = q.where(AdminCase.stage.in_(list(_OPEN_STAGES)))
    q = q.order_by(AdminCase.opened_at.desc())

    rows = (await db.execute(q)).scalars().all()
    return [CaseOut.from_orm(c) for c in rows]


# ── GET /admins/{admin_id}/ledger ─────────────────────────────────────────────

@router.get("/admins/{admin_id}/ledger")
async def admin_ledger(
    admin_id: int,
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Ledger конкретного администратора."""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    return await svc_ledger.get_admin_ledger(
        db, current_user.tenant_id, admin_id, year, month
    )


# ── GET /admins/{admin_id}/kpi-history ────────────────────────────────────────

@router.get("/admins/{admin_id}/kpi-history", response_model=list[KpiSnapshotHistoryItem])
async def admin_kpi_history(
    admin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """История KPI-снапшотов администратора по месяцам."""
    rows = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == current_user.tenant_id,
                AdminKpiSnapshot.admin_id == admin_id,
            ).order_by(
                AdminKpiSnapshot.period_year.desc(),
                AdminKpiSnapshot.period_month.desc(),
            )
        )
    ).scalars().all()
    return [KpiSnapshotHistoryItem.from_orm(r) for r in rows]


# ── GET /pending-qualitative ──────────────────────────────────────────────────

@router.get("/pending-qualitative", response_model=PendingQualitativeList)
async def pending_qualitative(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Качественные кейсы в awaiting_review для бейджа и списка овнера."""
    tid = current_user.tenant_id

    sent_at_sq = (
        select(
            CaseStageHistory.case_id.label("case_id"),
            func.max(CaseStageHistory.changed_at).label("sent_at"),
        )
        .where(CaseStageHistory.to_stage == "awaiting_review")
        .group_by(CaseStageHistory.case_id)
        .subquery()
    )

    base = (
        select(AdminCase, sent_at_sq.c.sent_at)
        .outerjoin(sent_at_sq, AdminCase.id == sent_at_sq.c.case_id)
        .where(
            AdminCase.tenant_id == tid,
            AdminCase.case_type == "qualitative",
            AdminCase.stage == "awaiting_review",
        )
    )

    total = (
        await db.execute(
            select(func.count()).select_from(
                select(AdminCase.id)
                .where(
                    AdminCase.tenant_id == tid,
                    AdminCase.case_type == "qualitative",
                    AdminCase.stage == "awaiting_review",
                )
                .subquery()
            )
        )
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(
                func.coalesce(sent_at_sq.c.sent_at, AdminCase.created_at).desc()
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    if not rows:
        return PendingQualitativeList(items=[], total=total)

    cases: list[AdminCase] = [r[0] for r in rows]
    sent_map: dict[int, Optional[datetime]] = {r[0].id: r[1] for r in rows}
    case_ids = [c.id for c in cases]
    om_ids = list({c.om_user_id for c in cases})
    admin_ids = list({c.admin_id for c in cases})

    mapping_rows = (
        await db.execute(
            select(ChatterMapping.onlymonster_id, ChatterMapping.display_names).where(
                ChatterMapping.tenant_id == tid,
                ChatterMapping.onlymonster_id.in_(om_ids),
            )
        )
    ).all()
    name_map = {r[0]: r[1] for r in mapping_rows}

    admin_rows = (
        await db.execute(select(User).where(User.id.in_(admin_ids)))
    ).scalars().all()
    admin_map = {u.id: u for u in admin_rows}

    act_counts_rows = (
        await db.execute(
            select(CaseActivity.case_id, func.count())
            .where(CaseActivity.case_id.in_(case_ids))
            .group_by(CaseActivity.case_id)
        )
    ).all()
    act_counts = {r[0]: int(r[1]) for r in act_counts_rows}

    items: list[PendingQualitativeItem] = []
    for case in cases:
        diagnosis, plan = _parse_case_notes(case.notes)
        raw_name = name_map.get(case.om_user_id)
        admin_user = admin_map.get(case.admin_id)
        admin_name = ""
        if admin_user:
            admin_name = (admin_user.full_name or admin_user.email or "").strip()

        hold_start_dt = await _stage_entered_at(db, case.id, "hold")
        sent_at = sent_map.get(case.id) or case.created_at

        items.append(
            PendingQualitativeItem(
                id=case.id,
                om_user_id=case.om_user_id,
                chatter_display_name=_resolve_chatter_display_name(
                    case.om_user_id, raw_name
                ),
                category=case.category or "",
                diagnosis_text=diagnosis,
                action_plan=plan,
                priority=case.priority,
                admin=PendingQualitativeAdmin(id=case.admin_id, name=admin_name),
                hold_start_date=hold_start_dt.date() if hold_start_dt else None,
                hold_end_date=case.review_date,
                sent_for_review_at=sent_at,
                activities_count=act_counts.get(case.id, 0),
            )
        )

    return PendingQualitativeList(items=items, total=total)


# ── GET /cases/{case_id} (owner qualitative detail) ───────────────────────────

@router.get("/cases/{case_id}", response_model=OwnerQualitativeCaseDetail)
async def get_owner_qualitative_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Детали качественного кейса для оценки овнером."""
    case = await _get_owner_case(db, current_user.tenant_id, case_id)
    if case.case_type != "qualitative":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Эндпоинт только для качественных кейсов",
        )

    tid = current_user.tenant_id
    mapping = (
        await db.execute(
            select(ChatterMapping.display_names).where(
                ChatterMapping.tenant_id == tid,
                ChatterMapping.onlymonster_id == case.om_user_id,
            )
        )
    ).scalar_one_or_none()
    admin_user = await db.get(User, case.admin_id)
    admin_name = ""
    if admin_user:
        admin_name = (admin_user.full_name or admin_user.email or "").strip()

    diagnosis, plan = _parse_case_notes(case.notes)
    hold_start_dt = await _stage_entered_at(db, case.id, "hold")
    sent_at = await _stage_entered_at(db, case.id, "awaiting_review")

    hist_rows = (
        await db.execute(
            select(CaseStageHistory)
            .where(CaseStageHistory.case_id == case_id)
            .order_by(CaseStageHistory.changed_at.asc())
        )
    ).scalars().all()

    ledger_points: Optional[float] = None
    if case.stage == "closed" and case.result in ("success", "failed"):
        event_type = (
            "qualitative_success" if case.result == "success" else "qualitative_failed"
        )
        ledger = await _latest_ledger_for_case(db, case_id, (event_type,))
        if ledger:
            ledger_points = float(ledger.points)

    return OwnerQualitativeCaseDetail(
        id=case.id,
        om_user_id=case.om_user_id,
        chatter_display_name=_resolve_chatter_display_name(case.om_user_id, mapping),
        category=case.category or "",
        diagnosis_text=diagnosis,
        action_plan=plan,
        priority=case.priority,
        stage=case.stage,
        result=case.result,
        admin=PendingQualitativeAdmin(id=case.admin_id, name=admin_name),
        hold_start_date=hold_start_dt.date() if hold_start_dt else None,
        hold_end_date=case.review_date,
        sent_for_review_at=sent_at,
        opened_at=case.opened_at,
        closed_at=case.closed_at,
        history=[StageHistoryItem.from_orm(h) for h in hist_rows],
        ledger_points=ledger_points,
    )


# ── POST /cases/{case_id}/close-qualitative ───────────────────────────────────

@router.post(
    "/cases/{case_id}/close-qualitative",
    response_model=CloseQualitativeResponse,
)
async def close_qualitative(
    case_id: int,
    body: CloseQualitativeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Овнер закрывает качественный кейс на оценке (success / failed)."""
    case = await _get_owner_case(db, current_user.tenant_id, case_id)
    if case.case_type != "qualitative":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Эндпоинт только для качественных кейсов",
        )

    try:
        await svc_cases.transition_stage(
            db,
            case_id,
            "closed",
            user=current_user,
            result=body.result,
            expected_from_stage="awaiting_review",
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _svc_err(exc) from exc

    event_type = "qualitative_success" if body.result == "success" else "qualitative_failed"
    ledger = await _latest_ledger_for_case(db, case_id, (event_type,))
    points = float(ledger.points) if ledger else 0.0

    return CloseQualitativeResponse(
        case_id=case_id,
        new_stage="closed",
        result=body.result,
        ledger_event=event_type,
        points=points,
    )


# ── POST /cases/{case_id}/return-for-revision ─────────────────────────────────

@router.post(
    "/cases/{case_id}/return-for-revision",
    response_model=ReturnForRevisionResponse,
)
async def return_for_revision(
    case_id: int,
    body: ReturnForRevisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Овнер возвращает качественный кейс на доработку с обязательным комментарием."""
    case = await _get_owner_case(db, current_user.tenant_id, case_id)
    if case.case_type != "qualitative":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Эндпоинт только для качественных кейсов",
        )

    comment = body.comment.strip()
    try:
        await svc_cases.transition_stage(
            db,
            case_id,
            "in_progress",
            user=current_user,
            comment=comment,
            expected_from_stage="awaiting_review",
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _svc_err(exc) from exc

    activity = (
        await db.execute(
            select(CaseActivity)
            .where(
                CaseActivity.case_id == case_id,
                CaseActivity.activity_type == "note",
                CaseActivity.text.like("Возврат на доработку от владельца:%"),
            )
            .order_by(CaseActivity.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Системная активность не создана",
        )

    return ReturnForRevisionResponse(
        case_id=case_id,
        new_stage="in_progress",
        activity_id=activity.id,
    )


# ── GET /kpi-config ───────────────────────────────────────────────────────────

@router.get("/kpi-config", response_model=list[KpiConfigOut])
async def get_kpi_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Список конфигураций KPI-метрик. Автосид если пусто."""
    tid = current_user.tenant_id
    rows = (
        await db.execute(
            select(KpiConfig).where(KpiConfig.tenant_id == tid)
            .order_by(KpiConfig.metric_type)
        )
    ).scalars().all()

    if not rows:
        await seed_default_kpi_config(db, tid)
        rows = (
            await db.execute(
                select(KpiConfig).where(KpiConfig.tenant_id == tid)
                .order_by(KpiConfig.metric_type)
            )
        ).scalars().all()

    return [KpiConfigOut.from_orm(r) for r in rows]


# ── PUT /kpi-config/{metric_type} ─────────────────────────────────────────────

@router.put("/kpi-config/{metric_type}", response_model=KpiConfigOut)
async def update_kpi_config(
    metric_type: MetricTypeLiteral,
    body: KpiConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """UPSERT конфигурации для одной метрики."""
    import json as _json

    tid = current_user.tenant_id
    await db.execute(
        text(
            """
            INSERT INTO kpi_config
                (tenant_id, metric_type, noise_threshold_pct,
                 guardrail_metrics, hold_days, detect_to_result_ratio_min, calibration_days)
            VALUES
                (:tid, :mt, :noise, :guardrail::jsonb,
                 :hold_days, :ratio, :cal_days)
            ON CONFLICT (tenant_id, metric_type) DO UPDATE SET
                noise_threshold_pct        = EXCLUDED.noise_threshold_pct,
                guardrail_metrics          = EXCLUDED.guardrail_metrics,
                hold_days                  = EXCLUDED.hold_days,
                detect_to_result_ratio_min = EXCLUDED.detect_to_result_ratio_min,
                calibration_days           = EXCLUDED.calibration_days
            """
        ),
        {
            "tid":      tid,
            "mt":       metric_type,
            "noise":    body.noise_threshold_pct,
            "guardrail": _json.dumps(body.guardrail_metrics),
            "hold_days": body.hold_days,
            "ratio":    body.detect_to_result_ratio_min,
            "cal_days": body.calibration_days,
        },
    )
    await db.commit()

    row = (
        await db.execute(
            select(KpiConfig).where(
                KpiConfig.tenant_id == tid,
                KpiConfig.metric_type == metric_type,
            )
        )
    ).scalar_one()
    return KpiConfigOut.from_orm(row)


# ── GET /cases/{case_id}/activities (owner read-only) ───────────────────────

@router.get(
    "/cases/{case_id}/activities",
    response_model=ActivityListOut,
    summary="Лента активностей кейса (овнер)",
    description="Только чтение: любой кейс своего tenant; те же фильтры, что у admin-portal.",
)
async def owner_list_case_activities(
    case_id: int,
    activity_type: Optional[list[str]] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    has_files: Optional[bool] = Query(default=None),
    text_search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    try:
        raw = await svc_activities.list_activities(
            db,
            current_user.tenant_id,
            case_id,
            _build_activity_filters(
                activity_type, date_from, date_to, has_files, text_search, limit, offset
            ),
        )
        return _activity_list_out(raw)
    except (CaseActivityNotFound, CaseActivityValidation) as exc:
        raise _map_activity_err(exc) from exc
