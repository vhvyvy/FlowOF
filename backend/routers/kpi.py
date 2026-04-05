import io
import json
import logging
from calendar import monthrange
from datetime import date, datetime

import csv

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from dependencies import get_current_tenant
from economics import (
    DEFAULT_TIER, PLAN_TIERS, RETENTION_RATE,
    compute_actual_chatter_cut, load_settings,
    _tier_pct,
)
from models import ChatterKpi, ChatterMapping, Plan, Tenant, Transaction
from schemas import (
    KpiMappingCreate, KpiMappingOut, KpiResponse, KpiRow, KpiSyncResult,
)
from services.onlymonster import fetch_chatter_metrics

logger = logging.getLogger("skynet.kpi")
router = APIRouter(prefix="/api/v1", tags=["kpi"])

HIDDEN_IDS = {"9680", "18073", "71191", "73588", "79737", "80144", "@hornykabanchik"}


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _safe(v: float | None, digits: int = 2) -> float | None:
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _compute_derived(row: dict, total_revenue: float) -> KpiRow:
    """Compute all derived KPI metrics from base fields."""
    rev = row["revenue"]
    txns = row["transactions"]
    ppv_or = _safe(row.get("ppv_open_rate"), 1)
    apv = _safe(row.get("apv"), 2)
    chats = row.get("total_chats")
    chats_int = int(chats) if chats is not None else None

    # Derived
    rpc = _safe(rev / chats, 2) if chats and chats > 0 else None
    ppv_sold = _safe(rev / apv, 2) if apv and apv > 0 else None
    apc = _safe(ppv_sold / chats, 2) if ppv_sold and chats and chats > 0 else None
    vol_rating = _safe(chats * (ppv_or / 100), 2) if chats and ppv_or is not None else None
    conv_score = _safe((ppv_or or 0) * (apc or 0), 2) if ppv_or is not None and apc is not None else None
    mono_depth = _safe((rpc or 0) / (apv or 1) * 100, 2) if rpc is not None and apv and apv > 0 else None
    prod_idx = _safe((ppv_sold or 0) / (chats or 1) * (ppv_or or 0), 2) if chats and chats > 0 and ppv_or is not None else None
    eff_ratio = _safe((rpc or 0) / (apv or 1) * (ppv_or or 0), 2) if rpc is not None and apv and apv > 0 and ppv_or is not None else None

    return KpiRow(
        chatter=row["chatter"],
        onlymonster_id=row.get("onlymonster_id"),
        revenue=round(rev, 2),
        transactions=txns,
        avg_check=round(rev / txns, 2) if txns > 0 else 0.0,
        share_pct=round(rev / total_revenue * 100, 1) if total_revenue > 0 else 0.0,
        payout=round(row.get("payout", 0.0), 2),
        ppv_open_rate=ppv_or,
        apv=apv,
        total_chats=chats_int,
        rpc=rpc,
        ppv_sold=ppv_sold,
        apc_per_chat=apc,
        volume_rating=vol_rating,
        conversion_score=conv_score,
        monetization_depth=mono_depth,
        productivity_index=prod_idx,
        efficiency_ratio=eff_ratio,
        source=row.get("source"),
    )


async def _load_kpi_data(db: AsyncSession, tenant_id: int, year: int, month: int) -> dict[str, dict]:
    """Load stored Onlymonster metrics from chatter_kpi_mt, keyed by chatter id."""
    result = await db.execute(
        select(ChatterKpi).where(
            and_(
                ChatterKpi.tenant_id == tenant_id,
                ChatterKpi.year == year,
                ChatterKpi.month == month,
            )
        )
    )
    return {
        str(r.chatter): {
            "ppv_open_rate": float(r.ppv_open_rate) if r.ppv_open_rate is not None else None,
            "apv": float(r.apv) if r.apv is not None else None,
            "total_chats": int(r.total_chats) if r.total_chats is not None else None,
            "source": r.source,
        }
        for r in result.scalars().all()
    }


async def _load_mapping(db: AsyncSession, tenant_id: int) -> tuple[dict[str, str], dict[str, str]]:
    """
    Returns (id_to_name, name_to_id).
    id_to_name: onlymonster_id -> first display name
    name_to_id: any display name -> onlymonster_id
    """
    result = await db.execute(
        select(ChatterMapping).where(ChatterMapping.tenant_id == tenant_id)
    )
    id_to_name: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    for m in result.scalars().all():
        oid = str(m.onlymonster_id)
        names_raw = m.display_names or ""
        try:
            names = json.loads(names_raw) if names_raw.startswith("[") else [names_raw]
        except Exception:
            names = [names_raw]
        if names:
            id_to_name[oid] = names[0]
        for n in names:
            n = str(n).strip()
            if n:
                name_to_id[n] = oid
    return id_to_name, name_to_id


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        start, end = _month_range(year, month)

        settings = await load_settings(db, tenant.id)
        ur = settings.get("use_retention", "1") == "1"

        # ── Revenue per chatter from transactions ──────────────────────────
        chatter_result = await db.execute(
            select(
                Transaction.chatter,
                func.sum(Transaction.amount).label("revenue"),
                func.count(Transaction.id).label("txn_count"),
            )
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                    Transaction.chatter.isnot(None),
                )
            )
            .group_by(Transaction.chatter)
            .order_by(func.sum(Transaction.amount).desc())
        )
        txn_rows = chatter_result.all()
        total_revenue = sum(float(r.revenue or 0) for r in txn_rows)
        total_txns = sum(int(r.txn_count or 0) for r in txn_rows)

        # ── Payout per chatter (plan-tier based, per model) ───────────────
        # Build model revenue map
        model_rev_result = await db.execute(
            select(
                Transaction.chatter,
                Transaction.model,
                func.sum(Transaction.amount).label("rev"),
            )
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                    Transaction.chatter.isnot(None),
                )
            )
            .group_by(Transaction.chatter, Transaction.model)
        )
        chatter_model_rows = model_rev_result.all()

        plan_result = await db.execute(
            select(Plan.model, Plan.plan_amount).where(
                and_(Plan.tenant_id == tenant.id, Plan.year == year, Plan.month == month)
            )
        )
        plan_map = {r.model: float(r.plan_amount or 0) for r in plan_result.all()}

        # model revenue for tier calc
        model_total_rev: dict[str, float] = {}
        for r in model_rev_result:
            pass
        model_rev_result2 = await db.execute(
            select(Transaction.model, func.sum(Transaction.amount).label("rev"))
            .where(and_(Transaction.tenant_id == tenant.id, Transaction.date >= start, Transaction.date <= end))
            .group_by(Transaction.model)
        )
        model_total_rev = {r.model: float(r.rev or 0) for r in model_rev_result2.all()}

        # chatter payout
        chatter_payout: dict[str, float] = {}
        for r in chatter_model_rows:
            ch = r.chatter
            m = r.model
            rev = float(r.rev or 0)
            plan_amt = plan_map.get(m, 0.0)
            if plan_amt > 0:
                model_rev_total = model_total_rev.get(m, rev)
                tier = max(0.20, _tier_pct(model_rev_total / plan_amt))
            else:
                tier = DEFAULT_TIER
            gross = rev * tier
            net = gross * (1 - RETENTION_RATE) if ur else gross
            chatter_payout[ch] = chatter_payout.get(ch, 0.0) + net

        # ── Onlymonster mapping & stored metrics ──────────────────────────
        id_to_name, name_to_id = await _load_mapping(db, tenant.id)
        kpi_data = await _load_kpi_data(db, tenant.id, year, month)

        # Resolve KPI metrics for a chatter display name
        def _kpi_for_chatter(chatter: str) -> tuple[dict, str | None]:
            s = str(chatter).strip()
            # Direct match by display name
            if s in kpi_data:
                oid = name_to_id.get(s)
                return kpi_data[s], oid
            # Match via mapping: get OM id for this chatter name, then look up kpi by id
            oid = name_to_id.get(s)
            if oid and oid in kpi_data:
                return kpi_data[oid], oid
            # Partial match
            for k, m in kpi_data.items():
                if s.startswith(k) or k.startswith(s):
                    return m, name_to_id.get(k)
            return {}, None

        # ── Build rows ────────────────────────────────────────────────────
        rows: list[KpiRow] = []
        for r in txn_rows:
            chatter = str(r.chatter or "Unknown").strip()
            if chatter in HIDDEN_IDS:
                continue
            rev = float(r.revenue or 0)
            txns = int(r.txn_count or 0)

            om_metrics, om_id = _kpi_for_chatter(chatter)
            row_data = {
                "chatter": chatter,
                "onlymonster_id": om_id,
                "revenue": rev,
                "transactions": txns,
                "payout": chatter_payout.get(chatter, 0.0),
                **om_metrics,
            }
            rows.append(_compute_derived(row_data, total_revenue))

        avg_rpc: float | None = None
        total_chats_sum = sum(r.total_chats for r in rows if r.total_chats)
        if total_chats_sum > 0:
            avg_rpc = round(total_revenue / total_chats_sum, 2)

        has_key = bool(tenant.onlymonster_key)

        return KpiResponse(
            rows=rows,
            total_revenue=round(total_revenue, 2),
            total_transactions=total_txns,
            avg_rpc=avg_rpc,
            has_onlymonster_key=has_key,
        )

    except Exception as e:
        logger.error("kpi error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка загрузки KPI")


@router.post("/kpi/sync", response_model=KpiSyncResult)
async def sync_kpi_from_api(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Sync chatter metrics from Onlymonster API for the given month."""
    if not tenant.onlymonster_key:
        raise HTTPException(status_code=400, detail="Onlymonster API-ключ не настроен. Добавьте ONLYMONSTER_API_KEY в настройки тенанта.")

    api_url = "https://omapi.onlymonster.ai"
    api_key = tenant.onlymonster_key

    last_day = monthrange(year, month)[1]
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)

    try:
        records = await fetch_chatter_metrics(api_url, api_key, start, end)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Onlymonster API: {e}")

    if not records:
        return KpiSyncResult(synced=0, message="API вернул 0 записей")

    await _upsert_kpi_records(db, tenant.id, year, month, records)
    await db.commit()

    return KpiSyncResult(synced=len(records), message=f"Синхронизировано {len(records)} записей из Onlymonster API")


@router.post("/kpi/upload", response_model=KpiSyncResult)
async def upload_kpi_csv(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Upload CSV export from Onlymonster Chatter Metrics."""
    content = await file.read()
    try:
        records = _parse_kpi_csv(content, file.filename or "")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ошибка парсинга файла: {e}")

    if not records:
        raise HTTPException(status_code=422, detail="Файл не содержит данных или формат не распознан")

    await _upsert_kpi_records(db, tenant.id, year, month, records)
    await db.commit()

    return KpiSyncResult(synced=len(records), message=f"Загружено {len(records)} записей из файла")


def _parse_kpi_csv(content: bytes, filename: str) -> list[dict]:
    """Parse CSV from Onlymonster export."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []

    cols = {c.lower().strip(): c for c in rows[0].keys()}

    def _find_col(*keys):
        for k in keys:
            if k in cols:
                return cols[k]
        return None

    chatter_col = _find_col("member", "chatter", "member id", "member_id", "member name", "member_name")
    ppv_col = _find_col("ppv open rate", "ppv open rate %", "ppv_open_rate")
    apv_col = _find_col("apv", "avg. price of sold ppv", "avg price of sold ppv", "avg payment value")
    chats_col = _find_col("total chats", "total_chats")

    records = []
    for row in rows:
        chatter = row.get(chatter_col, "").strip() if chatter_col else ""
        if not chatter:
            continue
        rec: dict = {"chatter": chatter, "source": "csv"}
        if ppv_col:
            try:
                v = str(row.get(ppv_col, "")).replace("%", "").strip()
                rec["ppv_open_rate"] = float(v) if v else None
            except (ValueError, TypeError):
                pass
        if apv_col:
            try:
                v = str(row.get(apv_col, "")).replace("$", "").replace(",", "").strip()
                rec["apv"] = float(v) if v else None
            except (ValueError, TypeError):
                pass
        if chats_col:
            try:
                v = str(row.get(chats_col, "")).strip()
                rec["total_chats"] = int(float(v)) if v else None
            except (ValueError, TypeError):
                pass
        records.append(rec)
    return records


async def _upsert_kpi_records(db: AsyncSession, tenant_id: int, year: int, month: int, records: list[dict]):
    """Upsert KPI records into chatter_kpi_mt."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from models import ChatterKpi

    for r in records:
        chatter = str(r.get("chatter", "")).strip()
        if not chatter:
            continue
        stmt = pg_insert(ChatterKpi).values(
            tenant_id=tenant_id,
            year=year,
            month=month,
            chatter=chatter,
            ppv_open_rate=r.get("ppv_open_rate"),
            apv=r.get("apv"),
            total_chats=r.get("total_chats"),
            source=r.get("source", "manual"),
        ).on_conflict_do_update(
            index_elements=["tenant_id", "year", "month", "chatter"],
            set_={
                "ppv_open_rate": pg_insert(ChatterKpi).excluded.ppv_open_rate,
                "apv": pg_insert(ChatterKpi).excluded.apv,
                "total_chats": pg_insert(ChatterKpi).excluded.total_chats,
                "source": pg_insert(ChatterKpi).excluded.source,
            },
        )
        await db.execute(stmt)


# ── Mapping CRUD ──────────────────────────────────────────────────────────────

@router.get("/kpi/mapping", response_model=list[KpiMappingOut])
async def get_mapping(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatterMapping).where(ChatterMapping.tenant_id == tenant.id)
    )
    return result.scalars().all()


@router.post("/kpi/mapping", response_model=KpiMappingOut)
async def add_mapping(
    body: KpiMappingCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    oid = body.onlymonster_id.strip()
    dname = body.display_name.strip()
    if not oid or not dname:
        raise HTTPException(status_code=422, detail="onlymonster_id и display_name обязательны")

    # Check if mapping exists
    existing_result = await db.execute(
        select(ChatterMapping).where(
            and_(ChatterMapping.tenant_id == tenant.id, ChatterMapping.onlymonster_id == oid)
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        # Append to display_names list
        try:
            names = json.loads(existing.display_names) if existing.display_names and existing.display_names.startswith("[") else [existing.display_names or ""]
        except Exception:
            names = [existing.display_names or ""]
        if dname not in names:
            names.append(dname)
        existing.display_names = json.dumps(names, ensure_ascii=False)
        await db.commit()
        await db.refresh(existing)
        return existing
    else:
        new_m = ChatterMapping(
            tenant_id=tenant.id,
            onlymonster_id=oid,
            display_names=json.dumps([dname], ensure_ascii=False),
        )
        db.add(new_m)
        await db.commit()
        await db.refresh(new_m)
        return new_m


@router.delete("/kpi/mapping/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChatterMapping).where(
            and_(ChatterMapping.id == mapping_id, ChatterMapping.tenant_id == tenant.id)
        )
    )
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Маппинг не найден")
    await db.delete(m)
    await db.commit()
    return {"ok": True}
