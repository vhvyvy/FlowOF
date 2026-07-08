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
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner
from models import AdminCase, AdminKpiSnapshot, KpiConfig, User
from schema_patch import seed_default_kpi_config
from services import case_ledger as svc_ledger
from services.admin_kpi_calc import recalc_admin_kpi_snapshot

logger = logging.getLogger("flowof.admins_review")
router = APIRouter(prefix="/api/v1/dashboard/admins-review", tags=["admins_review"])

MetricTypeLiteral = Literal["ppv_open_rate", "rpc", "apv", "total_chats", "revenue"]

_OPEN_STAGES = ("detected", "in_progress", "hold", "review_due")


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
