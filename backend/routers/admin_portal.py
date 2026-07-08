"""
Admin Portal — личный кабинет администратора агентства.

Prefix  : /api/v1/admin-portal
Auth    : require_admin (User.is_admin = True)
tenant_id извлекается из user.tenant_id (никогда из body).

Эндпоинты
---------
POST   /cases                       — создать кейс
GET    /cases                       — свои кейсы (с фильтром по stage)
GET    /cases/{case_id}             — детали + снапшоты + история
PATCH  /cases/{case_id}/stage       — сменить стадию
POST   /cases/{case_id}/close       — закрыть кейс
GET    /chatters                    — список чаттеров агентства + last metrics
GET    /me/ledger                   — история очков
GET    /me/kpi                      — KPI-снапшот текущего/выбранного месяца
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_admin
from models import (
    AdminCase, AdminKpiSnapshot, BaselineSnapshot, CaseStageHistory,
    ChatterMapping, KpiConfig, User,
)
from schema_patch import seed_default_kpi_config
from services import admin_cases as svc_cases
from services import case_ledger as svc_ledger
from services.admin_kpi_calc import recalc_admin_kpi_snapshot
from services.case_review_service import check_review_due_cases

logger = logging.getLogger("flowof.admin_portal")
router = APIRouter(prefix="/api/v1/admin-portal", tags=["admin_portal"])

MetricTypeLiteral = Literal["ppv_open_rate", "rpc", "apv", "total_chats", "revenue"]
StageLiteral = Literal["detected", "in_progress", "hold", "review_due", "closed", "cancelled"]
PriorityLiteral = Literal["high", "normal", "low"]
ResultLiteral = Literal["success", "failed", "cancelled"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    om_user_id: str
    chatter_display_name: str = ""
    metric_type: MetricTypeLiteral
    diagnosis_text: str = ""
    action_plan: str = ""
    priority: PriorityLiteral = "normal"


class CaseOut(BaseModel):
    id: int
    tenant_id: int
    admin_id: int
    om_user_id: str
    metric_type: str
    stage: str
    priority: str
    result: Optional[str]
    opened_at: datetime
    closed_at: Optional[datetime]
    review_date: Optional[date]
    baseline_value: Optional[float]
    target_value: Optional[float]
    result_value: Optional[float]
    notes: Optional[str]
    created_at: datetime

    @classmethod
    def from_orm(cls, c: AdminCase) -> "CaseOut":
        return cls(
            id=c.id,
            tenant_id=c.tenant_id,
            admin_id=c.admin_id,
            om_user_id=c.om_user_id,
            metric_type=c.metric_type,
            stage=c.stage,
            priority=c.priority,
            result=c.result,
            opened_at=c.opened_at,
            closed_at=c.closed_at,
            review_date=c.review_date,
            baseline_value=float(c.baseline_value) if c.baseline_value is not None else None,
            target_value=float(c.target_value) if c.target_value is not None else None,
            result_value=float(c.result_value) if c.result_value is not None else None,
            notes=c.notes,
            created_at=c.created_at,
        )


class SnapshotOut(BaseModel):
    id: int
    snapshot_type: str
    metric_type: str
    metric_value: float
    snapshot_date: date
    source: str
    created_at: datetime

    @classmethod
    def from_orm(cls, s: BaselineSnapshot) -> "SnapshotOut":
        return cls(
            id=s.id,
            snapshot_type=s.snapshot_type,
            metric_type=s.metric_type,
            metric_value=float(s.metric_value),
            snapshot_date=s.snapshot_date,
            source=s.source,
            created_at=s.created_at,
        )


class HistoryOut(BaseModel):
    id: int
    from_stage: Optional[str]
    to_stage: str
    changed_at: datetime
    changed_by: str
    notes: Optional[str]

    @classmethod
    def from_orm(cls, h: CaseStageHistory) -> "HistoryOut":
        return cls(
            id=h.id,
            from_stage=h.from_stage,
            to_stage=h.to_stage,
            changed_at=h.changed_at,
            changed_by=h.changed_by,
            notes=h.notes,
        )


class CaseDetailOut(CaseOut):
    snapshots: list[SnapshotOut] = []
    history: list[HistoryOut] = []


class PatchStageRequest(BaseModel):
    new_stage: StageLiteral
    notes: Optional[str] = None


class CloseRequest(BaseModel):
    result: ResultLiteral
    result_notes: str = ""


class ChatterItem(BaseModel):
    om_user_id: str
    display_name: str
    is_mapped: bool
    last_ppv_open_rate: Optional[float]
    last_apv: Optional[float]
    last_total_chats: Optional[int]
    has_open_case: bool
    open_case_by_me: bool


class KpiSnapshotOut(BaseModel):
    tenant_id: int
    admin_id: int
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
    def from_orm(cls, s: AdminKpiSnapshot) -> "KpiSnapshotOut":
        return cls(
            tenant_id=s.tenant_id,
            admin_id=s.admin_id,
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


_OPEN_STAGES = ("detected", "in_progress", "hold", "review_due")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _svc_err(exc: Exception) -> HTTPException:
    """Convert known service exceptions to HTTP errors."""
    msg = str(exc)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
    if isinstance(exc, ValueError):
        if "Уже есть открытый кейс" in msg:
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        if "Недостаточно данных для baseline" in msg or "not found" in msg.lower():
            return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)


# ── POST /cases ───────────────────────────────────────────────────────────────

@router.post("/cases", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
async def create_case(
    body: CreateCaseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Открыть новый кейс по чаттеру и метрике."""
    try:
        case = await svc_cases.create_case(
            db=db,
            tenant_id=current_user.tenant_id,
            admin_id=current_user.id,
            om_user_id=body.om_user_id,
            chatter_display_name=body.chatter_display_name,
            metric_type=body.metric_type,
            diagnosis_text=body.diagnosis_text,
            action_plan=body.action_plan,
            priority=body.priority,
        )
    except Exception as exc:
        raise _svc_err(exc) from exc
    return CaseOut.from_orm(case)


# ── GET /cases ────────────────────────────────────────────────────────────────

@router.get("/cases", response_model=list[CaseOut])
async def list_cases(
    stage: Optional[str] = Query(None, description="Фильтр по стадии"),
    include_closed: bool = Query(False, description="Включить закрытые / отменённые кейсы"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Список собственных кейсов текущего администратора."""
    q = select(AdminCase).where(
        AdminCase.tenant_id == current_user.tenant_id,
        AdminCase.admin_id == current_user.id,
    )
    if stage:
        q = q.where(AdminCase.stage == stage)
    elif not include_closed:
        q = q.where(AdminCase.stage.in_(list(_OPEN_STAGES)))

    q = q.order_by(AdminCase.opened_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [CaseOut.from_orm(c) for c in rows]


# ── GET /cases/{case_id} ──────────────────────────────────────────────────────

@router.get("/cases/{case_id}", response_model=CaseDetailOut)
async def get_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Детали кейса: базовые поля + снапшоты + история переходов."""
    case = await db.get(AdminCase, case_id)
    if case is None or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кейс не найден")
    if case.admin_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш кейс")

    snaps = (
        await db.execute(
            select(BaselineSnapshot)
            .where(BaselineSnapshot.case_id == case_id)
            .order_by(BaselineSnapshot.created_at.asc())
        )
    ).scalars().all()

    history = (
        await db.execute(
            select(CaseStageHistory)
            .where(CaseStageHistory.case_id == case_id)
            .order_by(CaseStageHistory.changed_at.asc())
        )
    ).scalars().all()

    base = CaseOut.from_orm(case)
    return CaseDetailOut(
        **base.model_dump(),
        snapshots=[SnapshotOut.from_orm(s) for s in snaps],
        history=[HistoryOut.from_orm(h) for h in history],
    )


# ── PATCH /cases/{case_id}/stage ─────────────────────────────────────────────

@router.patch("/cases/{case_id}/stage", response_model=CaseOut)
async def patch_stage(
    case_id: int,
    body: PatchStageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Сменить стадию кейса по FSM."""
    case = await db.get(AdminCase, case_id)
    if case is None or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кейс не найден")

    try:
        await svc_cases.transition_stage(
            db=db,
            case_id=case_id,
            new_stage=body.new_stage,
            changed_by="admin",
            actor_id=current_user.id,
            notes=body.notes,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _svc_err(exc) from exc

    await db.refresh(case)
    return CaseOut.from_orm(case)


# ── POST /cases/{case_id}/close ───────────────────────────────────────────────

@router.post("/cases/{case_id}/close", response_model=CaseOut)
async def close_case(
    case_id: int,
    body: CloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Закрыть кейс с результатом (success / failed / cancelled)."""
    case = await db.get(AdminCase, case_id)
    if case is None or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кейс не найден")
    if case.admin_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш кейс")

    try:
        case = await svc_cases.close_case(
            db=db,
            case_id=case_id,
            result=body.result,
            result_notes=body.result_notes,
            changed_by="admin",
            actor_id=current_user.id,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _svc_err(exc) from exc

    await db.refresh(case)
    return CaseOut.from_orm(case)


# ── GET /chatters ─────────────────────────────────────────────────────────────

@router.get("/chatters", response_model=list[ChatterItem])
async def list_chatters(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Список чаттеров агентства с последними KPI и наличием открытых кейсов.
    Источник: chatter_onlymonster_mapping + последний день в chatter_kpi_daily.
    """
    tid = current_user.tenant_id

    # All mappings for this tenant
    mappings = (
        await db.execute(
            select(ChatterMapping).where(ChatterMapping.tenant_id == tid)
        )
    ).scalars().all()

    if not mappings:
        return []

    om_ids = [m.onlymonster_id for m in mappings]

    # Latest available date per om_user_id in chatter_kpi_daily
    latest_rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (om_user_id)
                    om_user_id, ppv_open_rate, apv, total_chats, date
                FROM chatter_kpi_daily
                WHERE tenant_id = :tid AND om_user_id = ANY(:ids)
                ORDER BY om_user_id, date DESC
                """
            ),
            {"tid": tid, "ids": om_ids},
        )
    ).fetchall()

    metrics: dict[str, dict] = {
        r[0]: {
            "ppv_open_rate": r[1],
            "apv": r[2],
            "total_chats": r[3],
        }
        for r in latest_rows
    }

    # Open cases per om_user_id (any admin)
    open_cases_rows = (
        await db.execute(
            text(
                """
                SELECT om_user_id, admin_id
                FROM admin_cases
                WHERE tenant_id = :tid AND stage = ANY(:stages)
                """
            ),
            {"tid": tid, "stages": list(_OPEN_STAGES)},
        )
    ).fetchall()

    open_any: set[str] = {r[0] for r in open_cases_rows}
    open_mine: set[str] = {r[0] for r in open_cases_rows if r[1] == current_user.id}

    items: list[ChatterItem] = []
    for m in mappings:
        display = (m.display_names or "").split(",")[0].strip() or m.onlymonster_id
        daily = metrics.get(m.onlymonster_id, {})
        items.append(
            ChatterItem(
                om_user_id=m.onlymonster_id,
                display_name=display,
                is_mapped=True,
                last_ppv_open_rate=float(daily["ppv_open_rate"]) if daily.get("ppv_open_rate") is not None else None,
                last_apv=float(daily["apv"]) if daily.get("apv") is not None else None,
                last_total_chats=int(daily["total_chats"]) if daily.get("total_chats") is not None else None,
                has_open_case=m.onlymonster_id in open_any,
                open_case_by_me=m.onlymonster_id in open_mine,
            )
        )

    return items


# ── GET /me/ledger ────────────────────────────────────────────────────────────

@router.get("/me/ledger")
async def my_ledger(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """История начислений и списаний очков текущего администратора."""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month
    return await svc_ledger.get_admin_ledger(
        db, current_user.tenant_id, current_user.id, year, month
    )


# ── GET /me/kpi ───────────────────────────────────────────────────────────────

@router.get("/me/kpi", response_model=KpiSnapshotOut)
async def my_kpi(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """KPI-снапшот текущего администратора за выбранный месяц."""
    if year is None:
        year = date.today().year
    if month is None:
        month = date.today().month

    snap = (
        await db.execute(
            select(AdminKpiSnapshot).where(
                AdminKpiSnapshot.tenant_id == current_user.tenant_id,
                AdminKpiSnapshot.admin_id == current_user.id,
                AdminKpiSnapshot.period_year == year,
                AdminKpiSnapshot.period_month == month,
            )
        )
    ).scalar_one_or_none()

    if snap is None:
        # Calculate on-demand if not yet computed
        snap = await recalc_admin_kpi_snapshot(
            db, current_user.tenant_id, current_user.id, year, month
        )

    return KpiSnapshotOut.from_orm(snap)


# ── Debug: manual HOLD review trigger ────────────────────────────────────────

@router.post("/cases/run-review-now")
async def run_review_now(
    force_all_hold: bool = Query(False, description="Ignore review_date — process ALL hold cases"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Manually trigger the HOLD review for the current admin's tenant.

    force_all_hold=true: processes every case in 'hold' stage regardless of
    review_date — useful for testing without waiting 21 days.

    Only for debugging/testing. Safe to call multiple times (idempotent decisions
    based on current metric data).
    """
    from sqlalchemy import update

    tid = current_user.tenant_id

    if force_all_hold:
        # Temporarily move all hold cases' review_date to today so the
        # standard check_review_due_cases query picks them up.
        # We restore nothing — the service itself will update/close them.
        from datetime import date as _date
        today = _date.today()
        await db.execute(
            update(AdminCase)
            .where(
                AdminCase.tenant_id == tid,
                AdminCase.stage == "hold",
            )
            .values(review_date=today)
        )
        await db.flush()

    stats = await check_review_due_cases(db, tid)
    logger.info(
        "run_review_now: admin=%s tenant=%s force=%s stats=%s",
        current_user.id, tid, force_all_hold, stats,
    )
    return {"ok": True, "force_all_hold": force_all_hold, **stats}
