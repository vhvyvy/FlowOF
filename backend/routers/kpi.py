import io
import json
import logging
from calendar import monthrange
from datetime import datetime

import csv

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from dependencies import get_current_tenant
from economics import load_settings
from models import ChatterKpi, ChatterMapping, Tenant, Transaction
from schemas import (
    KpiMappingCreate, KpiMappingOut, KpiResponse, KpiSyncResult,
)
from services.kpi_service import get_chatter_kpi
from services.onlymonster import fetch_chatter_metrics
from team_helpers import list_teams, team_transaction_clause

logger = logging.getLogger("flowof.kpi")
router = APIRouter(prefix="/api/v1", tags=["kpi"])


@router.get("/kpi", response_model=KpiResponse)
async def get_kpi(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    team_id: int | None = Query(None, description="Filter to one team"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        settings = await load_settings(db, tenant.id)
        use_retention = settings.get("use_retention", "1") == "1"

        # ── Resolve team filter ────────────────────────────────────────────
        teams = await list_teams(db, tenant.id)
        default_team_id = teams[0].id if teams else None
        team_filter = None
        if team_id is not None:
            selected = next((t for t in teams if t.id == team_id), None)
            if selected is not None:
                team_filter = team_transaction_clause(selected.id, default_team_id)

        rows, total_revenue, total_txns, avg_rpc = await get_chatter_kpi(
            db, tenant.id, year, month, use_retention=use_retention, team_filter=team_filter
        )

        return KpiResponse(
            rows=rows,
            total_revenue=total_revenue,
            total_transactions=total_txns,
            avg_rpc=avg_rpc,
            has_onlymonster_key=bool(tenant.onlymonster_key),
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
        raise HTTPException(
            status_code=400,
            detail="Onlymonster API-ключ не настроен. Добавьте ONLYMONSTER_API_KEY в настройки тенанта.",
        )

    api_url  = "https://omapi.onlymonster.ai"
    api_key  = tenant.onlymonster_key
    last_day = monthrange(year, month)[1]
    start    = datetime(year, month, 1)
    end      = datetime(year, month, last_day, 23, 59, 59)

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


@router.post("/kpi/sync-all", response_model=KpiSyncResult)
async def sync_kpi_all_months(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Sync chatter metrics from Onlymonster API for ALL months that have transactions."""
    if not tenant.onlymonster_key:
        raise HTTPException(status_code=400, detail="Onlymonster API-ключ не настроен")

    api_url = "https://omapi.onlymonster.ai"
    api_key = tenant.onlymonster_key

    months_result = await db.execute(
        select(
            func.extract("year",  Transaction.date).label("yr"),
            func.extract("month", Transaction.date).label("mo"),
        )
        .where(Transaction.tenant_id == tenant.id)
        .group_by("yr", "mo")
        .order_by("yr", "mo")
    )
    months = [(int(r.yr), int(r.mo)) for r in months_result.all() if r.yr and r.mo]

    if not months:
        return KpiSyncResult(synced=0, message="Нет месяцев с транзакциями")

    total = 0
    errors: list[str] = []
    for yr, mo in months:
        last_day = monthrange(yr, mo)[1]
        start    = datetime(yr, mo, 1)
        end      = datetime(yr, mo, last_day, 23, 59, 59)
        try:
            records = await fetch_chatter_metrics(api_url, api_key, start, end)
            if records:
                await _upsert_kpi_records(db, tenant.id, yr, mo, records)
                total += len(records)
        except Exception as e:
            errors.append(f"{yr}/{mo}: {e}")
            logger.warning("sync-all error %d/%d: %s", yr, mo, e)

    await db.commit()
    msg = f"Синхронизировано {total} записей за {len(months)} месяцев"
    if errors:
        msg += f" (ошибки: {'; '.join(errors[:3])})"
    return KpiSyncResult(synced=total, message=msg)


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


# ── Internal storage helpers (sync / upload only) ─────────────────────────────

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
    ppv_col     = _find_col("ppv open rate", "ppv open rate %", "ppv_open_rate")
    apv_col     = _find_col("apv", "avg. price of sold ppv", "avg price of sold ppv", "avg payment value")
    chats_col   = _find_col("total chats", "total_chats")

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


async def _upsert_kpi_records(
    db: AsyncSession,
    tenant_id: int,
    year: int,
    month: int,
    records: list[dict],
) -> None:
    """Upsert KPI records into chatter_kpi_mt."""
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
                "apv":           pg_insert(ChatterKpi).excluded.apv,
                "total_chats":   pg_insert(ChatterKpi).excluded.total_chats,
                "source":        pg_insert(ChatterKpi).excluded.source,
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
    oid   = body.onlymonster_id.strip()
    dname = body.display_name.strip()
    if not oid or not dname:
        raise HTTPException(status_code=422, detail="onlymonster_id и display_name обязательны")

    existing_result = await db.execute(
        select(ChatterMapping).where(
            and_(ChatterMapping.tenant_id == tenant.id, ChatterMapping.onlymonster_id == oid)
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        try:
            names = (
                json.loads(existing.display_names)
                if existing.display_names and existing.display_names.startswith("[")
                else [existing.display_names or ""]
            )
        except Exception:
            names = [existing.display_names or ""]
        if dname not in names:
            names.append(dname)
        existing.display_names = json.dumps(names, ensure_ascii=False)
        await db.commit()
        await db.refresh(existing)
        return existing

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


# ── Daily KPI endpoints ────────────────────────────────────────────────────────

from datetime import date as _date


@router.post("/kpi/daily/collect")
async def collect_kpi_daily(
    date: _date = Query(..., description="Target date (YYYY-MM-DD)"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Manually collect Onlymonster KPI for a specific date → chatter_kpi_daily."""
    if not tenant.onlymonster_key:
        raise HTTPException(
            status_code=400,
            detail="Onlymonster API-ключ не настроен. Добавьте его в настройки тенанта.",
        )
    try:
        from services.kpi_daily import collect_daily_kpi
        result = await collect_daily_kpi(db, tenant.id, date)
        if result.get("error"):
            raise HTTPException(status_code=502, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("kpi daily collect error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kpi/daily/backfill")
async def backfill_kpi_daily(
    date_from: _date = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: _date   = Query(..., description="End date (YYYY-MM-DD)"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Backfill daily Onlymonster KPI for a date range (max 180 days)."""
    if not tenant.onlymonster_key:
        raise HTTPException(
            status_code=400,
            detail="Onlymonster API-ключ не настроен. Добавьте его в настройки тенанта.",
        )
    try:
        from services.kpi_daily import backfill_daily_kpi
        result = await backfill_daily_kpi(db, tenant.id, date_from, date_to)
        return result
    except Exception as e:
        logger.error("kpi daily backfill error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/kpi/daily")
async def get_kpi_daily(
    date_from: _date       = Query(..., description="Start date (YYYY-MM-DD)"),
    date_to: _date         = Query(..., description="End date (YYYY-MM-DD)"),
    chatter: str | None    = Query(None, description="Filter by chatter name (optional)"),
    tenant: Tenant         = Depends(get_current_tenant),
    db: AsyncSession       = Depends(get_db),
):
    """Read daily KPI rows from chatter_kpi_daily for inspection / future use."""
    from sqlalchemy import text as _text
    try:
        params: dict = {"tid": tenant.id, "df": date_from, "dt": date_to}
        chatter_clause = ""
        if chatter:
            chatter_clause = "AND chatter ILIKE :chatter"
            params["chatter"] = f"%{chatter}%"

        rows = (await db.execute(
            _text(
                f"""
                SELECT chatter, om_user_id, date, ppv_open_rate, apv, total_chats, source
                FROM chatter_kpi_daily
                WHERE tenant_id = :tid
                  AND date >= :df
                  AND date <= :dt
                  {chatter_clause}
                ORDER BY date DESC, chatter ASC
                LIMIT 5000
                """
            ),
            params,
        )).mappings().all()

        return {
            "date_from": str(date_from),
            "date_to":   str(date_to),
            "count":     len(rows),
            "rows": [
                {
                    "chatter":       r["chatter"],
                    "om_user_id":    r["om_user_id"],
                    "date":          str(r["date"]),
                    "ppv_open_rate": float(r["ppv_open_rate"]) if r["ppv_open_rate"] is not None else None,
                    "apv":           float(r["apv"]) if r["apv"] is not None else None,
                    "total_chats":   r["total_chats"],
                    "source":        r["source"],
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.error("kpi daily get error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
