"""CSV-экспорт данных чаттеров и KPI."""
from __future__ import annotations

import csv
import io
import logging
from calendar import monthrange

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant

logger = logging.getLogger("flowof.export")

router = APIRouter(prefix="/api/v1/export", tags=["export"])


def _csv_response(rows: list[list], headers: list[str], filename: str) -> StreamingResponse:
    """Формирует StreamingResponse с UTF-8 BOM CSV (корректно открывается в Excel)."""
    buf = io.StringIO()
    buf.write("\ufeff")          # UTF-8 BOM
    writer = csv.writer(buf, dialect="excel")
    writer.writerow(headers)
    writer.writerows(rows)
    content = buf.getvalue()

    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _fmt(v, digits: int = 2) -> str:
    if v is None:
        return ""
    try:
        return str(round(float(v), digits))
    except (TypeError, ValueError):
        return str(v)


# ─── Экспорт Чаттеров ────────────────────────────────────────────────────────

@router.get("/chatters")
async def export_chatters(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт данных чаттеров в CSV за указанный месяц/год."""
    from routers.chatters import get_chatters

    try:
        data = await get_chatters(
            month=month,
            year=year,
            team_id=None,
            tenant=tenant,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export chatters error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка формирования экспорта")

    status_label = {"top": "Топ", "ok": "Норм", "risk": "Риск", "miss": "Провал"}

    headers = [
        "Чаттер", "Команда", "Выручка ($)", "Транзакции",
        "Средний чек ($)", "RPC ($)", "% к выплате (нетто)",
        "К выплате ($)", "Статус",
    ]
    rows = []
    for c in data.chatters:
        avg_check = round(c.revenue / c.transactions, 2) if c.transactions > 0 else 0.0
        rows.append([
            c.name,
            c.team_name or "",
            _fmt(c.revenue),
            c.transactions,
            _fmt(avg_check),
            _fmt(c.rpc),
            _fmt(c.chatter_pct, 1),
            _fmt(c.chatter_cut),
            status_label.get(c.status, c.status),
        ])

    filename = f"chatters_{year}_{month:02d}.csv"
    return _csv_response(rows, headers, filename)


# ─── Экспорт KPI ─────────────────────────────────────────────────────────────

@router.get("/kpi")
async def export_kpi(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт KPI-метрик чаттеров в CSV за указанный месяц/год."""
    from routers.kpi import get_kpi

    try:
        data = await get_kpi(
            month=month,
            year=year,
            tenant=tenant,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export kpi error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка формирования экспорта")

    headers = [
        "Чаттер", "Onlymonster ID",
        "Выручка ($)", "Транзакции", "Средний чек ($)", "Доля %", "Выплата ($)",
        "PPV Open Rate %", "APV ($)", "Чатов",
        "RPC ($)", "PPV Sold", "APC/Chat",
        "Volume Rating", "Conv. Score", "Monetization Depth",
        "Productivity Index", "Efficiency Ratio",
        "Источник",
    ]
    rows = []
    for r in data.rows:
        rows.append([
            r.chatter,
            r.onlymonster_id or "",
            _fmt(r.revenue),
            r.transactions,
            _fmt(r.avg_check),
            _fmt(r.share_pct, 1),
            _fmt(r.payout),
            _fmt(r.ppv_open_rate, 1),
            _fmt(r.apv),
            r.total_chats if r.total_chats is not None else "",
            _fmt(r.rpc),
            _fmt(r.ppv_sold),
            _fmt(r.apc_per_chat),
            _fmt(r.volume_rating),
            _fmt(r.conversion_score),
            _fmt(r.monetization_depth),
            _fmt(r.productivity_index),
            _fmt(r.efficiency_ratio),
            r.source or "",
        ])

    filename = f"kpi_{year}_{month:02d}.csv"
    return _csv_response(rows, headers, filename)
