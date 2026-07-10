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
POST   /cases/{case_id}/activities  — добавить активность (multipart)
GET    /cases/{case_id}/activities  — лента активностей кейса
DELETE /cases/{case_id}/activities/{activity_id} — удалить (<24ч)
GET    /activities/files/{file_id}  — скачать вложение
GET    /me/ledger                   — история очков
GET    /me/kpi                      — KPI-снапшот текущего/выбранного месяца
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from pydantic.config import ConfigDict
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_admin
from models import (
    AdminCase, AdminKpiSnapshot, BaselineSnapshot, CaseActivity,
    CaseActivityFile, CaseStageHistory,
    ChatterMapping, KpiConfig, User,
)
from schemas import (
    ActivityCreateOut,
    ActivityFileOut,
    ActivityItemOut,
    ActivityListOut,
    ActivityAdminOut,
)
from schema_patch import seed_default_kpi_config
from services import admin_cases as svc_cases
from services import case_activities as svc_activities
from services.case_activities import CaseActivityNotFound, CaseActivityValidation
from services import case_ledger as svc_ledger
from services.admin_kpi_calc import recalc_admin_kpi_snapshot
from services.case_baseline import read_metric_at_date
from services.case_review_service import check_review_due_cases
from services.kpi_service import get_chatter_kpi

logger = logging.getLogger("flowof.admin_portal")
router = APIRouter(prefix="/api/v1/admin-portal", tags=["admin_portal"])

MetricTypeLiteral = Literal["ppv_open_rate", "rpc", "apv", "total_chats", "revenue"]
CaseTypeLiteral = Literal["quantitative", "qualitative"]
StageLiteral = Literal[
    "detected", "in_progress", "hold", "review_due", "awaiting_review", "closed", "cancelled"
]
PriorityLiteral = Literal["high", "normal", "low"]
ResultLiteral = Literal["success", "failed", "cancelled"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CreateCaseRequest(BaseModel):
    """Создание количественного или качественного кейса."""

    model_config = ConfigDict(extra="forbid")

    om_user_id: str
    chatter_display_name: str = ""
    case_type: CaseTypeLiteral = "quantitative"
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    metric_type: Optional[MetricTypeLiteral] = None
    diagnosis_text: str = ""
    action_plan: str = ""
    priority: PriorityLiteral = "normal"
    hold_days: int = Field(default=21, ge=0, le=60)

    @model_validator(mode="after")
    def validate_case_type_fields(self) -> "CreateCaseRequest":
        if self.case_type == "quantitative":
            if self.metric_type is None:
                raise ValueError("metric_type обязателен для количественного кейса")
            if self.category is not None:
                raise ValueError("category допустима только для качественных кейсов")
        else:
            cat = (self.category or "").strip()
            if not cat:
                raise ValueError("category обязателена для качественного кейса (1–100 символов)")
            if self.metric_type is not None:
                raise ValueError("metric_type не используется для качественных кейсов")
        return self


class CaseOut(BaseModel):
    id: int
    tenant_id: int
    admin_id: int
    om_user_id: str
    case_type: str = "quantitative"
    category: Optional[str] = None
    metric_type: Optional[str] = None
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
            case_type=c.case_type or "quantitative",
            category=c.category,
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


class MetricPoint(BaseModel):
    value: Optional[float] = None
    date_label: Optional[str] = None   # human-readable period (e.g. "7 июл" or "июл 2025")


class CaseDetailOut(CaseOut):
    snapshots: list[SnapshotOut] = []
    history: list[HistoryOut] = []
    today_metric: MetricPoint = MetricPoint()
    week_avg_metric: MetricPoint = MetricPoint()
    month_metric: MetricPoint = MetricPoint()


class PatchStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_stage: StageLiteral
    notes: Optional[str] = None


class TransitionRequest(BaseModel):
    """POST /cases/{id}/transition — смена стадии админом."""

    model_config = ConfigDict(extra="forbid")

    target_stage: StageLiteral
    notes: Optional[str] = None


class CloseRequest(BaseModel):
    result: ResultLiteral
    result_notes: str = ""


class ChatterItem(BaseModel):
    om_user_id: str
    display_name: str
    month_open_rate: Optional[float] = None
    month_rpc: Optional[float] = None
    month_apv: Optional[float] = None
    month_chats: Optional[int] = None
    month_revenue: Optional[float] = None
    has_open_case: bool = False
    open_case_by_me: bool = False


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


_OPEN_STAGES = ("detected", "in_progress", "hold", "review_due", "awaiting_review")

_ACTIVITY_FILE_URL = "/api/v1/admin-portal/activities/files"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _map_activity_err(exc: Exception) -> HTTPException:
    """Map case_activities service errors to HTTP status codes."""
    if isinstance(exc, CaseActivityNotFound):
        detail = exc.args[0] if exc.args else str(exc)
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    if isinstance(exc, PermissionError):
        detail = exc.args[0] if exc.args else str(exc)
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    if isinstance(exc, CaseActivityValidation):
        detail = exc.args[0] if exc.args else str(exc)
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )
    return _svc_err(exc)


def _build_activity_filters(
    activity_type: Optional[list[str]],
    date_from: Optional[date],
    date_to: Optional[date],
    has_files: Optional[bool],
    text_search: Optional[str],
    limit: int,
    offset: int,
) -> svc_activities.ActivityFilters:
    return svc_activities.ActivityFilters(
        activity_types=activity_type,
        date_from=date_from,
        date_to=date_to,
        has_files=has_files,
        text_search=text_search,
        limit=limit,
        offset=offset,
    )


def _activity_list_out(raw: dict[str, Any]) -> ActivityListOut:
    items: list[ActivityItemOut] = []
    for row in raw.get("items", []):
        admin = row.get("admin") or {}
        files = [
            ActivityFileOut(
                id=f["id"],
                file_path=f["file_path"],
                original_name=f.get("original_name"),
                size_bytes=f.get("size_bytes"),
                mime_type=f.get("mime_type"),
                download_url=f"{_ACTIVITY_FILE_URL}/{f['id']}",
            )
            for f in row.get("files", [])
        ]
        items.append(
            ActivityItemOut(
                id=row["id"],
                activity_type=row["activity_type"],
                text=row["text"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                admin=ActivityAdminOut(
                    id=admin.get("id", row.get("admin_id", 0)),
                    name=admin.get("name", ""),
                ),
                files=files,
            )
        )
    return ActivityListOut(items=items, total=raw.get("total", 0))


def _svc_err(exc: Exception) -> HTTPException:
    """Convert known service exceptions to HTTP errors."""
    msg = str(exc)
    if isinstance(exc, svc_cases.StageConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
    if isinstance(exc, ValueError):
        if "Уже есть открытый кейс" in msg:
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        if (
            "Достигнут лимит" in msg
            or "Недостаточно данных для baseline" in msg
            or "not found" in msg.lower()
            or "обязател" in msg.lower()
            or "допустим" in msg.lower()
            or "не используется" in msg.lower()
            or "Дождитесь окончания HOLD" in msg
        ):
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
            diagnosis_text=body.diagnosis_text,
            action_plan=body.action_plan,
            priority=body.priority,
            hold_days=body.hold_days,
            case_type=body.case_type,
            category=body.category.strip() if body.category else None,
            metric_type=body.metric_type,
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

    today = date.today()
    year, month = today.year, today.month

    today_metric = MetricPoint()
    week_avg_metric = MetricPoint()
    month_metric = MetricPoint()

    if case.metric_type and (case.case_type or "quantitative") == "quantitative":
        # ── today_metric: yesterday's daily value (1-day lookback) ───────────
        yesterday = today - timedelta(days=1)
        today_val = await read_metric_at_date(
            db, case.tenant_id, case.om_user_id, case.metric_type, yesterday
        )
        today_metric = MetricPoint(
            value=float(today_val) if today_val is not None else None,
            date_label=yesterday.strftime("%-d %b").lstrip("0") if today_val is not None else None,
        )

        # ── week_avg_metric: average of last 7 available daily values ─────────────
        week_vals = []
        for d in range(1, 8):
            v = await read_metric_at_date(
                db, case.tenant_id, case.om_user_id, case.metric_type, today - timedelta(days=d)
            )
            if v is not None:
                week_vals.append(float(v))
        if week_vals:
            avg = sum(week_vals) / len(week_vals)
            start_day = (today - timedelta(days=7)).strftime("%-d")
            end_day   = yesterday.strftime("%-d %b")
            week_avg_metric = MetricPoint(
                value=round(avg, 4),
                date_label=f"{start_day}–{end_day}",
            )

        # ── month_metric: current month aggregate from kpi_service ───────────────
        try:
            kpi_rows, _, _, _ = await get_chatter_kpi(db, case.tenant_id, year, month)
            month_row = next(
                (r for r in kpi_rows if r.onlymonster_id == case.om_user_id), None
            )
            metric_attr = {
                "ppv_open_rate": "ppv_open_rate",
                "apv":           "apv",
                "rpc":           "rpc",
                "total_chats":   "total_chats",
                "revenue":       "revenue",
            }.get(case.metric_type)
            month_val = getattr(month_row, metric_attr, None) if month_row and metric_attr else None
            month_metric = MetricPoint(
                value=float(month_val) if month_val is not None else None,
                date_label=today.strftime("%b %Y"),
            )
        except Exception as exc:
            logger.warning("get_case: month_metric error case=%s: %s", case_id, exc)

    base = CaseOut.from_orm(case)
    return CaseDetailOut(
        **base.model_dump(),
        snapshots=[SnapshotOut.from_orm(s) for s in snaps],
        history=[HistoryOut.from_orm(h) for h in history],
        today_metric=today_metric,
        week_avg_metric=week_avg_metric,
        month_metric=month_metric,
    )


# ── PATCH /cases/{case_id}/stage + POST /cases/{case_id}/transition ───────────

async def _admin_transition_stage(
    db: AsyncSession,
    case_id: int,
    target_stage: str,
    current_user: User,
    notes: Optional[str],
) -> AdminCase:
    case = await db.get(AdminCase, case_id)
    if case is None or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кейс не найден")
    if case.admin_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Это не ваш кейс")

    try:
        await svc_cases.transition_stage(
            db=db,
            case_id=case_id,
            new_stage=target_stage,
            user=current_user,
            notes=notes,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise _svc_err(exc) from exc

    await db.refresh(case)
    return case


@router.patch("/cases/{case_id}/stage", response_model=CaseOut)
async def patch_stage(
    case_id: int,
    body: PatchStageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Сменить стадию кейса по FSM (админ)."""
    case = await _admin_transition_stage(
        db, case_id, body.new_stage, current_user, body.notes
    )
    return CaseOut.from_orm(case)


@router.post("/cases/{case_id}/transition", response_model=CaseOut)
async def post_transition(
    case_id: int,
    body: TransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Сменить стадию кейса по FSM (админ). Алиас PATCH /stage с target_stage."""
    case = await _admin_transition_stage(
        db, case_id, body.target_stage, current_user, body.notes
    )
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

def _resolve_chatter_display_name(om_id: str, raw_name: str | None) -> str:
    """Unwrap mapping display_names; always return a non-empty label (fallback: om_id)."""
    import json as _json

    raw = (raw_name or "").strip()
    display = ""
    if raw:
        try:
            parsed = _json.loads(raw)
            if isinstance(parsed, list) and parsed:
                display = str(parsed[0]).strip()
            else:
                display = raw.split(",")[0].strip()
        except Exception:
            display = raw.split(",")[0].strip()
    return display or str(om_id)


def _mapping_is_admin_account(display_names: str | None) -> bool:
    """ChatterMapping has no role/is_admin — agency admin OM accounts use [Adm] prefix."""
    return "[Adm]" in (display_names or "")


@router.get("/chatters", response_model=list[ChatterItem])
async def list_chatters(
    show_all: bool = Query(False, description="Показать всех, включая неактивных"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Список активных чаттеров агентства с месячными KPI (текущий месяц).
    Активность (show_all=false): за текущий календарный месяц —
      daily total_chats > 0 (то же окно, что get_chatter_kpi year/month).
    Метрики: те же, что на KPI-вкладке owner'а (kpi_service.get_chatter_kpi).

    Список строится по daily (вариант A), не по транзакциям get_chatter_kpi.
    Намеренно не попадают чаттеры только с revenue в KPI, без daily total_chats>0
    за месяц — напр. om 48721 @Vyach3slav (есть деньги, нет daily; sync vs не чатил — отдельно).
    """
    tid = current_user.tenant_id
    today = date.today()
    year, month = today.year, today.month

    # ── Monthly KPI via the same service as owner KPI tab ────────────────────
    kpi_rows, _, _, _ = await get_chatter_kpi(db, tid, year, month)

    # Index monthly KPI by onlymonster_id
    monthly_by_om: dict[str, Any] = {}
    for row in kpi_rows:
        if row.onlymonster_id:
            monthly_by_om[row.onlymonster_id] = row

    # ── Active mappings: calendar month, daily total_chats > 0 only ─────────
    # month_start aligns with get_chatter_kpi(year, month) window.
    # NOTE: on the 1st of each month, chatter_kpi_daily for the new month appears
    # only after the kpi_daily CRON at 04:00 UTC. Between 00:00–04:00 UTC the list
    # will be empty until the first daily sync runs.
    month_start = date(year, month, 1)

    admin_name_filter = func.coalesce(ChatterMapping.display_names, "").notlike("%[Adm]%")

    if show_all:
        mapping_rows = (
            await db.execute(
                select(ChatterMapping.onlymonster_id, ChatterMapping.display_names)
                .where(ChatterMapping.tenant_id == tid, admin_name_filter)
                .order_by(ChatterMapping.onlymonster_id)
            )
        ).fetchall()
    else:
        mapping_rows = (
            await db.execute(
                text(
                    """
                    SELECT m.onlymonster_id, m.display_names
                    FROM chatter_onlymonster_mapping m
                    WHERE m.tenant_id = :tid
                      AND COALESCE(m.display_names, '') NOT LIKE '%[Adm]%'
                      AND EXISTS (
                        SELECT 1 FROM chatter_kpi_daily d
                        WHERE d.tenant_id = m.tenant_id
                          AND d.om_user_id = m.onlymonster_id
                          AND d.date >= :month_start
                          AND d.total_chats > 0
                      )
                    ORDER BY m.onlymonster_id
                    """
                ),
                {"tid": tid, "month_start": month_start},
            )
        ).fetchall()

    if not mapping_rows:
        return []

    # ── Open cases per om_user_id ─────────────────────────────────────────────
    open_cases_rows = (
        await db.execute(
            text(
                "SELECT om_user_id, admin_id FROM admin_cases "
                "WHERE tenant_id = :tid AND stage = ANY(:stages)"
            ),
            {"tid": tid, "stages": list(_OPEN_STAGES)},
        )
    ).fetchall()
    open_any: set[str] = {r[0] for r in open_cases_rows}
    open_mine: set[str] = {r[0] for r in open_cases_rows if r[1] == current_user.id}

    # ── Build items ───────────────────────────────────────────────────────────
    items: list[ChatterItem] = []
    for om_id, raw_name in mapping_rows:
        if _mapping_is_admin_account(raw_name):
            continue
        display = _resolve_chatter_display_name(om_id, raw_name)

        kpi = monthly_by_om.get(om_id)
        items.append(
            ChatterItem(
                om_user_id=om_id,
                display_name=display,
                month_open_rate=kpi.ppv_open_rate if kpi else None,
                month_rpc=kpi.rpc if kpi else None,
                month_apv=kpi.apv if kpi else None,
                month_chats=kpi.total_chats if kpi else None,
                month_revenue=kpi.revenue if kpi else None,
                has_open_case=om_id in open_any,
                open_case_by_me=om_id in open_mine,
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


# ── Case activities ───────────────────────────────────────────────────────────

@router.post(
    "/cases/{case_id}/activities",
    response_model=ActivityCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить активность к кейсу",
    description="Multipart: тип, текст и до 5 скриншотов (image/*, ≤5 МБ каждый).",
)
async def create_case_activity(
    case_id: int,
    activity_type: str = Form(...),
    text: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        result = await svc_activities.create_activity(
            db=db,
            tenant_id=current_user.tenant_id,
            case_id=case_id,
            admin_id=current_user.id,
            activity_type=activity_type,
            text=text,
            uploaded_files=files,
        )
        return ActivityCreateOut(**result)
    except (CaseActivityNotFound, CaseActivityValidation, PermissionError) as exc:
        raise _map_activity_err(exc) from exc


@router.get(
    "/cases/{case_id}/activities",
    response_model=ActivityListOut,
    summary="Лента активностей кейса",
    description="Фильтры по типу, дате, наличию файлов и тексту; пагинация limit/offset.",
)
async def list_case_activities(
    case_id: int,
    activity_type: Optional[list[str]] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    has_files: Optional[bool] = Query(default=None),
    text_search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
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


@router.get(
    "/activities/files/{file_id}",
    summary="Скачать вложение активности",
    description="Доступ: owner тенанта или admin — автор кейса. Файл из FILE_STORAGE_ROOT.",
    responses={
        200: {"description": "Binary file"},
        404: {"description": "Файл не найден в БД"},
        410: {"description": "Запись есть, файл на диске отсутствует"},
    },
)
async def download_activity_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services.file_storage import get_storage_root

    row = (
        await db.execute(
            select(CaseActivityFile, CaseActivity, AdminCase)
            .join(CaseActivity, CaseActivityFile.activity_id == CaseActivity.id)
            .join(AdminCase, CaseActivity.case_id == AdminCase.id)
            .where(
                CaseActivityFile.id == file_id,
                AdminCase.tenant_id == current_user.tenant_id,
            )
        )
    ).one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    file_row, _activity, admin_case = row

    is_owner = current_user.role == "owner"
    is_case_admin = bool(current_user.is_admin) and current_user.id == admin_case.admin_id
    if not (is_owner or is_case_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому файлу",
        )

    abs_path = get_storage_root() / file_row.file_path
    if not abs_path.is_file():
        logger.warning(
            "activity file missing on disk: id=%s path=%s",
            file_id,
            abs_path,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Файл на диске отсутствует",
        )

    if file_row.original_name:
        filename = file_row.original_name
    else:
        ext = Path(file_row.file_path).suffix or ".bin"
        filename = f"file{ext}"

    media_type = file_row.mime_type or "application/octet-stream"
    return FileResponse(
        path=str(abs_path),
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete(
    "/cases/{case_id}/activities/{activity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить активность",
    description="Только автор активности, в течение 24 часов после создания.",
)
async def delete_case_activity(
    case_id: int,
    activity_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    try:
        await svc_activities.delete_activity(
            db=db,
            tenant_id=current_user.tenant_id,
            case_id=case_id,
            admin_id=current_user.id,
            activity_id=activity_id,
        )
    except (CaseActivityNotFound, PermissionError) as exc:
        raise _map_activity_err(exc) from exc


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
