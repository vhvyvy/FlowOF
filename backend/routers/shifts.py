import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case, or_

from database import get_db
from dependencies import get_current_tenant
from economics import load_settings
from models import ChatterKpi, ChatterMapping, Plan, Tenant, Transaction
from schemas import ShiftRow, ShiftsResponse

logger = logging.getLogger("skynet.shifts")
router = APIRouter(prefix="/api/v1", tags=["shifts"])


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


async def _load_kpi_map(
    db: AsyncSession, tenant_id: int, year: int, month: int
) -> dict[str, dict]:
    """Load Onlymonster metrics keyed by chatter identifier."""
    import json

    # Load mapping: name → onlymonster_id
    mapping_result = await db.execute(
        select(ChatterMapping).where(ChatterMapping.tenant_id == tenant_id)
    )
    name_to_id: dict[str, str] = {}
    for m in mapping_result.scalars().all():
        oid = str(m.onlymonster_id)
        names_raw = m.display_names or ""
        try:
            names = json.loads(names_raw) if names_raw.startswith("[") else [names_raw]
        except Exception:
            names = [names_raw]
        for n in names:
            n = str(n).strip()
            if n:
                name_to_id[n] = oid

    # Load KPI from chatter_kpi_mt
    from sqlalchemy import text

    kpi: dict[str, dict] = {}
    kpi_result = await db.execute(
        select(ChatterKpi).where(
            and_(
                ChatterKpi.tenant_id == tenant_id,
                ChatterKpi.year == year,
                ChatterKpi.month == month,
            )
        )
    )
    for r in kpi_result.scalars().all():
        kpi[str(r.chatter)] = {
            "ppv_open_rate": float(r.ppv_open_rate) if r.ppv_open_rate is not None else None,
            "apv": float(r.apv) if r.apv is not None else None,
            "total_chats": int(r.total_chats) if r.total_chats is not None else None,
        }

    # Fallback: legacy chatter_kpi
    if not kpi:
        try:
            legacy = await db.execute(
                text(
                    "SELECT chatter, ppv_open_rate, apv, total_chats "
                    "FROM chatter_kpi WHERE year=:year AND month=:month"
                ),
                {"year": year, "month": month},
            )
            for r in legacy.all():
                kpi[str(r.chatter)] = {
                    "ppv_open_rate": float(r.ppv_open_rate) if r.ppv_open_rate is not None else None,
                    "apv": float(r.apv) if r.apv is not None else None,
                    "total_chats": int(r.total_chats) if r.total_chats is not None else None,
                }
        except Exception:
            pass

    return kpi, name_to_id


def _kpi_for(chatter: str, kpi: dict, name_to_id: dict) -> dict:
    s = str(chatter).strip()
    if s in kpi:
        return kpi[s]
    oid = name_to_id.get(s)
    if oid and oid in kpi:
        return kpi[oid]
    for k in kpi:
        if s.startswith(k) or k.startswith(s):
            return kpi[k]
    return {}


@router.get("/shifts", response_model=ShiftsResponse)
async def get_shifts(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)
        settings = await load_settings(db, tenant.id)
        admin_pct = float(settings.get("admin_percent", "9")) / 100

        # shift_key = shift_name if available (select), else shift_id (relation)
        shift_key = func.coalesce(
            case((Transaction.shift_name != "", Transaction.shift_name), else_=None),
            Transaction.shift_id,
        ).label("shift_key")

        _has_shift = or_(
            and_(Transaction.shift_name.isnot(None), Transaction.shift_name != ""),
            and_(Transaction.shift_id.isnot(None), Transaction.shift_id != ""),
        )

        # ── Revenue / stats per shift ──────────────────────────────────────
        shift_result = await db.execute(
            select(
                func.coalesce(
                    case((Transaction.shift_name != "", Transaction.shift_name), else_=None),
                    Transaction.shift_id,
                ).label("shift_key"),
                func.sum(Transaction.amount).label("revenue"),
                func.count(Transaction.id).label("transactions"),
                func.count(func.distinct(Transaction.chatter)).label("chatters"),
                func.count(func.distinct(Transaction.model)).label("models"),
                func.count(func.distinct(Transaction.date)).label("active_days"),
            )
            .where(and_(
                Transaction.tenant_id == tenant.id,
                Transaction.date >= start,
                Transaction.date <= end,
                _has_shift,
            ))
            .group_by("shift_key")
            .order_by(func.sum(Transaction.amount).desc())
        )
        shift_rows = shift_result.all()

        if not shift_rows:
            return ShiftsResponse(
                shifts=[],
                total_revenue=0,
                admin_pct=admin_pct * 100,
                admin_payout_total=0,
                admin_payout_each=0,
                shifts_count=0,
            )

        total_revenue = sum(float(r.revenue or 0) for r in shift_rows)
        n_shifts = len(shift_rows)
        admin_payout_total = total_revenue * admin_pct
        admin_payout_each = admin_payout_total / n_shifts if n_shifts > 0 else 0

        # ── Plan completion per shift ──────────────────────────────────────
        plan_result = await db.execute(
            select(Plan.model, Plan.plan_amount).where(
                and_(Plan.tenant_id == tenant.id, Plan.year == year, Plan.month == month)
            )
        )
        plan_map = {r.model: float(r.plan_amount or 0) for r in plan_result.all() if r.plan_amount and float(r.plan_amount) > 0}

        # Revenue per model within each shift
        model_shift_result = await db.execute(
            select(
                func.coalesce(
                    case((Transaction.shift_name != "", Transaction.shift_name), else_=None),
                    Transaction.shift_id,
                ).label("shift_key"),
                Transaction.model,
                func.sum(Transaction.amount).label("rev"),
            )
            .where(and_(
                Transaction.tenant_id == tenant.id,
                Transaction.date >= start,
                Transaction.date <= end,
                _has_shift,
            ))
            .group_by("shift_key", Transaction.model)
        )
        # model total revenue (for plan completion)
        model_total_rev: dict[str, float] = {}
        shift_model_rev: dict[str, dict[str, float]] = {}
        for r in model_shift_result.all():
            sn = str(r.shift_key)
            m = str(r.model or "")
            rev = float(r.rev or 0)
            model_total_rev[m] = model_total_rev.get(m, 0) + rev
            if sn not in shift_model_rev:
                shift_model_rev[sn] = {}
            shift_model_rev[sn][m] = shift_model_rev[sn].get(m, 0) + rev

        # ── Chatters per shift (for KPI lookup) ───────────────────────────
        chatter_shift_result = await db.execute(
            select(
                func.coalesce(
                    case((Transaction.shift_name != "", Transaction.shift_name), else_=None),
                    Transaction.shift_id,
                ).label("shift_key"),
                Transaction.chatter,
            )
            .where(and_(
                Transaction.tenant_id == tenant.id,
                Transaction.date >= start,
                Transaction.date <= end,
                _has_shift,
                Transaction.chatter.isnot(None),
            ))
            .distinct()
        )
        shift_chatters: dict[str, list[str]] = {}
        for r in chatter_shift_result.all():
            sn = str(r.shift_key)
            c = str(r.chatter)
            if sn not in shift_chatters:
                shift_chatters[sn] = []
            shift_chatters[sn].append(c)

        # ── Onlymonster KPI ───────────────────────────────────────────────
        kpi_data, name_to_id = await _load_kpi_map(db, tenant.id, year, month)

        # ── Build shift rows ──────────────────────────────────────────────
        result_shifts: list[ShiftRow] = []
        for r in shift_rows:
            sn = str(r.shift_key)
            rev = float(r.revenue or 0)
            txns = int(r.transactions or 0)
            chatters_count = int(r.chatters or 0)
            models_count = int(r.models or 0)
            active_days = int(r.active_days or 0)

            # Plan completion (revenue-weighted across models in this shift)
            plan_completion: float | None = None
            shift_models = shift_model_rev.get(sn, {})
            if plan_map and shift_models:
                weighted_sum = 0.0
                weight_total = 0.0
                for m, mrev in shift_models.items():
                    if m in plan_map and plan_map[m] > 0:
                        completion = model_total_rev.get(m, mrev) / plan_map[m]
                        weighted_sum += completion * mrev
                        weight_total += mrev
                if weight_total > 0:
                    plan_completion = round(weighted_sum / weight_total * 100, 1)

            # Average KPI metrics across chatters in this shift
            chatters_in_shift = shift_chatters.get(sn, [])
            ppv_vals, apv_vals, chats_vals = [], [], []
            for c in chatters_in_shift:
                km = _kpi_for(c, kpi_data, name_to_id)
                if km.get("ppv_open_rate") is not None:
                    ppv_vals.append(km["ppv_open_rate"])
                if km.get("apv") is not None:
                    apv_vals.append(km["apv"])
                if km.get("total_chats") is not None:
                    chats_vals.append(km["total_chats"])

            result_shifts.append(ShiftRow(
                name=sn,
                revenue=round(rev, 2),
                transactions=txns,
                chatters=chatters_count,
                models=models_count,
                active_days=active_days,
                avg_check=round(rev / txns, 2) if txns > 0 else 0,
                revenue_per_chatter=round(rev / chatters_count, 2) if chatters_count > 0 else None,
                revenue_per_model=round(rev / models_count, 2) if models_count > 0 else None,
                productivity_per_day=round(rev / active_days, 2) if active_days > 0 else None,
                share_pct=round(rev / total_revenue * 100, 1) if total_revenue > 0 else 0,
                admin_payout=round(admin_payout_each, 2),
                plan_completion=plan_completion,
                avg_ppv_open_rate=round(sum(ppv_vals) / len(ppv_vals), 1) if ppv_vals else None,
                avg_apv=round(sum(apv_vals) / len(apv_vals), 2) if apv_vals else None,
                total_chats_sum=sum(chats_vals) if chats_vals else None,
            ))

        return ShiftsResponse(
            shifts=result_shifts,
            total_revenue=round(total_revenue, 2),
            admin_pct=round(admin_pct * 100, 1),
            admin_payout_total=round(admin_payout_total, 2),
            admin_payout_each=round(admin_payout_each, 2),
            shifts_count=n_shifts,
        )

    except Exception as e:
        logger.error("shifts error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка загрузки данных смен")
