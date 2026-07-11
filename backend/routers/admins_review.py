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
GET  /cases/{case_id}                   — детали кейса (quant + qual)
GET  /cases/{case_id}/activities        — лента активностей кейса (read-only)
GET  /pending-qualitative               — качественные кейсы на оценке
POST /recalc-snapshots                  — пересчёт KPI-снапшотов текущего месяца
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
from schemas import (
    ActivityListOut,
    CaseOut,
    LedgerItem,
    OwnerAdminBrief,
    OwnerCaseDetail,
    RecalcSnapshotsAdminItem,
    RecalcSnapshotsResponse,
    StageHistoryItem,
)
from schema_patch import seed_default_kpi_config
from services import admin_cases as svc_cases
from services import case_activities as svc_activities
from services import case_ledger as svc_ledger
from services.case_activities import CaseActivityNotFound, CaseActivityValidation
from services.admin_kpi_calc import nightly_recalc_all_tenant_snapshots, recalc_admin_kpi_snapshot
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


def _derive_hold_days(case: AdminCase) -> Optional[int]:
    if case.review_date is None:
        return None
    opened = case.opened_at.date() if hasattr(case.opened_at, "date") else case.opened_at
    return (case.review_date - opened).days


def _admin_display_name(user: Optional[User]) -> str:
    if user is None:
        return ""
    return (user.full_name or user.email or "").strip()


def _case_out_from_row(case: AdminCase, display_names: Optional[str]) -> CaseOut:
    opened = case.opened_at.date() if hasattr(case.opened_at, "date") else case.opened_at
    closed = None
    if case.closed_at is not None:
        closed = case.closed_at.date() if hasattr(case.closed_at, "date") else case.closed_at
    case_type = case.case_type or "quantitative"
    return CaseOut(
        id=case.id,
        admin_id=case.admin_id,
        case_type=case_type,
        category=case.category if case_type == "qualitative" else None,
        om_user_id=case.om_user_id,
        metric_type=case.metric_type if case_type == "quantitative" else None,
        chatter_display_name=_resolve_chatter_display_name(case.om_user_id, display_names),
        stage=case.stage,
        priority=case.priority,
        result=case.result,
        opened_at=opened,
        closed_at=closed,
        review_date=case.review_date,
        hold_days=_derive_hold_days(case),
        baseline_value=float(case.baseline_value) if case.baseline_value is not None else None,
        result_value=float(case.result_value) if case.result_value is not None else None,
        baseline_version=case.baseline_version or "v1",
        is_early_month=bool(case.is_early_month),
        is_new_chatter=bool(case.is_new_chatter),
        notes=case.notes,
    )


async def _build_owner_case_detail(
    db: AsyncSession, tenant_id: int, case: AdminCase
) -> OwnerCaseDetail:
    mapping = (
        await db.execute(
            select(ChatterMapping.display_names).where(
                ChatterMapping.tenant_id == tenant_id,
                ChatterMapping.onlymonster_id == case.om_user_id,
            )
        )
    ).scalar_one_or_none()
    admin_user = await db.get(User, case.admin_id)
    shift_map = await _fetch_shift_map(db, tenant_id)
    admin_shift_id = getattr(admin_user, "admin_shift_id", None) if admin_user else None
    shift_name = shift_map.get(admin_shift_id) if admin_shift_id else None
    diagnosis, plan = _parse_case_notes(case.notes)
    sent_at = await _stage_entered_at(db, case.id, "awaiting_review")

    hist_rows = (
        await db.execute(
            select(CaseStageHistory)
            .where(CaseStageHistory.case_id == case.id)
            .order_by(CaseStageHistory.changed_at.asc())
        )
    ).scalars().all()

    ledger_rows = (
        await db.execute(
            select(CaseLedger)
            .where(CaseLedger.case_id == case.id)
            .order_by(CaseLedger.created_at.asc())
        )
    ).scalars().all()

    activities_count = (
        await db.execute(
            select(func.count())
            .select_from(CaseActivity)
            .where(CaseActivity.case_id == case.id)
        )
    ).scalar_one()

    case_type = case.case_type or "quantitative"
    return OwnerCaseDetail(
        id=case.id,
        case_type=case_type,
        tenant_id=case.tenant_id,
        admin=OwnerAdminBrief(
            id=case.admin_id,
            name=_admin_display_name(admin_user),
            shift_name=shift_name,
        ),
        om_user_id=case.om_user_id,
        chatter_display_name=_resolve_chatter_display_name(case.om_user_id, mapping),
        category=case.category if case_type == "qualitative" else None,
        metric_type=case.metric_type if case_type == "quantitative" else None,
        stage=case.stage,
        priority=case.priority,
        result=case.result,
        opened_at=case.opened_at,
        closed_at=case.closed_at,
        review_date=case.review_date,
        hold_days=_derive_hold_days(case),
        baseline_value=float(case.baseline_value) if case.baseline_value is not None else None,
        result_value=float(case.result_value) if case.result_value is not None else None,
        baseline_version=case.baseline_version or "v1",
        is_early_month=bool(case.is_early_month),
        is_new_chatter=bool(case.is_new_chatter),
        diagnosis_text=diagnosis,
        action_plan=plan,
        history=[StageHistoryItem.from_orm(h) for h in hist_rows],
        ledger=[
            LedgerItem(
                id=r.id,
                event_type=r.event_type,
                points=float(r.points),
                notes=r.notes,
                created_at=r.created_at,
            )
            for r in ledger_rows
        ],
        activities_count=int(activities_count),
        sent_for_review_at=sent_at,
    )


def _snap_to_recalc_item(admin: User, snap: AdminKpiSnapshot) -> RecalcSnapshotsAdminItem:
    return RecalcSnapshotsAdminItem(
        id=admin.id,
        name=_admin_display_name(admin),
        cases_opened=snap.cases_opened,
        cases_closed_success=snap.cases_closed_success,
        cases_closed_failed=snap.cases_closed_failed,
        cases_cancelled=snap.cases_cancelled,
        guardrail_hits=snap.guardrail_hits,
        total_points=float(snap.total_points),
        detect_result_ratio=(
            float(snap.detect_result_ratio)
            if snap.detect_result_ratio is not None
            else None
        ),
        is_calibration=snap.is_calibration,
    )


async def _get_tenant_admin_or_404(
    db: AsyncSession, tenant_id: int, admin_id: int
) -> User:
    admin = await db.get(User, admin_id)
    if (
        admin is None
        or admin.tenant_id != tenant_id
        or not admin.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Администратор не найден",
        )
    return admin


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


class AdminsReviewResponse(BaseModel):
    admins: list[AdminListItem]
    detect_result_ratio_threshold: int = 15


class AdminDetailAdmin(BaseModel):
    id: int
    name: Optional[str]
    email: str
    admin_shift_id: Optional[int]
    shift_name: Optional[str]


class AdminDetailResponse(BaseModel):
    admin: AdminDetailAdmin
    current_kpi: AdminKpiSummary
    is_calibration: bool
    open_cases_count: int
    detect_result_ratio_threshold: int


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


async def _detect_result_ratio_threshold(
    db: AsyncSession, tenant_id: int
) -> int:
    cfg = (
        await db.execute(
            select(KpiConfig).where(
                KpiConfig.tenant_id == tenant_id,
                KpiConfig.metric_type == "revenue",
            )
        )
    ).scalar_one_or_none()
    return cfg.detect_to_result_ratio_min if cfg else 15


def _kpi_summary_from_snapshot(snap: Optional[AdminKpiSnapshot]) -> AdminKpiSummary:
    if snap is None:
        return AdminKpiSummary()
    return AdminKpiSummary(
        cases_opened=snap.cases_opened,
        cases_closed_success=snap.cases_closed_success,
        cases_closed_failed=snap.cases_closed_failed,
        cases_cancelled=snap.cases_cancelled,
        guardrail_hits=snap.guardrail_hits,
        total_points=float(snap.total_points),
        detect_result_ratio=(
            float(snap.detect_result_ratio)
            if snap.detect_result_ratio is not None
            else None
        ),
        is_calibration=snap.is_calibration,
    )


async def _fetch_shift_map(db: AsyncSession, tenant_id: int) -> dict[int, str]:
    rows = (
        await db.execute(
            text("SELECT id, name FROM shifts_catalog WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).fetchall()
    return {r[0]: r[1] for r in rows}


async def _fetch_open_counts(
    db: AsyncSession, tenant_id: int, admin_ids: list[int]
) -> dict[int, int]:
    if not admin_ids:
        return {}
    rows = (
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
            {"tid": tenant_id, "ids": admin_ids, "stages": list(_OPEN_STAGES)},
        )
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


async def _snapshots_for_month(
    db: AsyncSession,
    tenant_id: int,
    admin_ids: list[int],
    year: int,
    month: int,
) -> dict[int, AdminKpiSnapshot]:
    if not admin_ids:
        return {}
    rows = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == tenant_id,
                AdminKpiSnapshot.admin_id.in_(admin_ids),
                AdminKpiSnapshot.period_year == year,
                AdminKpiSnapshot.period_month == month,
            )
        )
    ).scalars().all()
    return {s.admin_id: s for s in rows}


def _admin_list_item(
    admin: User,
    kpi: AdminKpiSummary,
    open_cases_count: int,
    shift_map: dict[int, str],
) -> AdminListItem:
    admin_shift_id = getattr(admin, "admin_shift_id", None)
    return AdminListItem(
        id=admin.id,
        name=admin.full_name,
        email=admin.email,
        admin_shift_id=admin_shift_id,
        shift_name=shift_map.get(admin_shift_id) if admin_shift_id else None,
        current_month_kpi=kpi,
        open_cases_count=open_cases_count,
    )


# ── GET /admins ───────────────────────────────────────────────────────────────

@router.get("/admins", response_model=AdminsReviewResponse)
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
    ratio_threshold = await _detect_result_ratio_threshold(db, tid)

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
        return AdminsReviewResponse(
            admins=[],
            detect_result_ratio_threshold=ratio_threshold,
        )

    admin_ids = [a.id for a in admins]
    snaps = await _snapshots_for_month(db, tid, admin_ids, year, month)
    open_counts = await _fetch_open_counts(db, tid, admin_ids)
    shift_map = await _fetch_shift_map(db, tid)

    items = [
        _admin_list_item(
            admin,
            _kpi_summary_from_snapshot(snaps.get(admin.id)),
            open_counts.get(admin.id, 0),
            shift_map,
        )
        for admin in admins
    ]

    return AdminsReviewResponse(
        admins=items,
        detect_result_ratio_threshold=ratio_threshold,
    )


# ── GET /admins/{admin_id} ────────────────────────────────────────────────────

@router.get("/admins/{admin_id}", response_model=AdminDetailResponse)
async def get_admin_detail(
    admin_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Профиль администратора + KPI текущего месяца."""
    tid = current_user.tenant_id
    today = date.today()
    year, month = today.year, today.month

    admin = await _get_tenant_admin_or_404(db, tid, admin_id)
    ratio_threshold = await _detect_result_ratio_threshold(db, tid)
    snaps = await _snapshots_for_month(db, tid, [admin_id], year, month)
    open_counts = await _fetch_open_counts(db, tid, [admin_id])
    shift_map = await _fetch_shift_map(db, tid)

    kpi = _kpi_summary_from_snapshot(snaps.get(admin_id))
    admin_shift_id = getattr(admin, "admin_shift_id", None)

    return AdminDetailResponse(
        admin=AdminDetailAdmin(
            id=admin.id,
            name=admin.full_name,
            email=admin.email,
            admin_shift_id=admin_shift_id,
            shift_name=shift_map.get(admin_shift_id) if admin_shift_id else None,
        ),
        current_kpi=kpi,
        is_calibration=kpi.is_calibration,
        open_cases_count=open_counts.get(admin_id, 0),
        detect_result_ratio_threshold=ratio_threshold,
    )


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

    q = (
        select(AdminCase, ChatterMapping.display_names)
        .outerjoin(
            ChatterMapping,
            (ChatterMapping.tenant_id == AdminCase.tenant_id)
            & (ChatterMapping.onlymonster_id == AdminCase.om_user_id),
        )
        .where(
            AdminCase.tenant_id == tid,
            AdminCase.admin_id == admin_id,
        )
    )
    if stage:
        q = q.where(AdminCase.stage == stage)
    elif not include_closed:
        q = q.where(AdminCase.stage.in_(list(_OPEN_STAGES)))
    q = q.order_by(AdminCase.opened_at.desc())

    rows = (await db.execute(q)).all()
    return [_case_out_from_row(case, display_names) for case, display_names in rows]


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


# ── GET /cases/{case_id} (owner universal detail) ─────────────────────────────

@router.get("/cases/{case_id}", response_model=OwnerCaseDetail)
async def get_owner_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Детали кейса для овнера (quantitative и qualitative)."""
    case = await _get_owner_case(db, current_user.tenant_id, case_id)
    return await _build_owner_case_detail(db, current_user.tenant_id, case)


# ── POST /recalc-snapshots ────────────────────────────────────────────────────

@router.post("/recalc-snapshots", response_model=RecalcSnapshotsResponse)
async def recalc_snapshots(
    admin_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Пересчёт KPI-снапшотов текущего месяца для одного или всех админов tenant."""
    import traceback

    tid = current_user.tenant_id
    today = date.today()
    year, month = today.year, today.month

    if admin_id is not None:
        await _get_tenant_admin_or_404(db, tid, admin_id)
        target_ids = [admin_id]
    else:
        admins = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tid,
                    User.is_admin == True,  # noqa: E712
                    User.active == True,  # noqa: E712
                )
            )
        ).scalars().all()
        target_ids = [a.id for a in admins]

    recalculated = 0
    items: list[RecalcSnapshotsAdminItem] = []

    try:
        for aid in target_ids:
            snap = await recalc_admin_kpi_snapshot(db, tid, aid, year, month)
            admin = await db.get(User, aid)
            items.append(_snap_to_recalc_item(admin, snap))
            recalculated += 1
    except Exception as exc:
        logger.error("recalc_snapshots failed: %s", traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка пересчёта KPI: {exc}",
        ) from exc

    return RecalcSnapshotsResponse(
        recalculated=recalculated,
        admins=items,
        cached_at=datetime.utcnow(),
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
