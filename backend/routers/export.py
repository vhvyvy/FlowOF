"""CSV-экспорт данных чаттеров, KPI, Overview и Финансов."""
from __future__ import annotations

import csv
import io
import logging
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Expense

logger = logging.getLogger("flowof.export")

router = APIRouter(prefix="/api/v1/export", tags=["export"])


def _month_range(year: int, month: int):
    from calendar import monthrange as _mr
    last = _mr(year, month)[1]
    return date(year, month, 1), date(year, month, last)


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


def _multi_block_response(blocks: list[tuple[list[str], list[list]]], filename: str) -> StreamingResponse:
    """Несколько блоков (каждый со своим заголовком) в одном CSV-файле."""
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(buf, dialect="excel")
    for i, (headers, rows) in enumerate(blocks):
        if i > 0:
            writer.writerow([])  # пустая строка между блоками
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


# ─── Экспорт Overview ────────────────────────────────────────────────────────

@router.get("/overview")
async def export_overview(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Экспорт Overview-метрик за месяц: сводка, разбивка по командам, выручка по дням."""
    from routers.overview import get_overview

    try:
        data = await get_overview(
            month=month,
            year=year,
            team_id=None,
            tenant=tenant,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export overview error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка формирования экспорта")

    # Блок 1: Основные метрики
    metrics_rows = [
        ["Выручка",      _fmt(data.revenue)],
        ["Прибыль",      _fmt(data.profit)],
        ["Маржа %",      _fmt(data.margin, 1)],
        ["Расходы",      _fmt(data.expenses)],
        ["Транзакции",   str(data.transactions_count)],
    ]

    # Блок 2: По командам (если есть)
    teams_rows = [
        [t.name, _fmt(t.revenue), _fmt(t.profit), _fmt(t.margin, 1)]
        for t in (data.teams_breakdown or [])
    ]

    # Блок 3: Выручка по дням
    daily_rows = [
        [d.date, _fmt(d.amount)]
        for d in (data.daily_revenue or [])
    ]

    blocks: list[tuple[list[str], list[list]]] = [
        (["Метрика", "Значение"], metrics_rows),
        (["Команда", "Выручка ($)", "Прибыль ($)", "Маржа %"], teams_rows),
        (["Дата", "Выручка ($)"], daily_rows),
    ]

    filename = f"overview_{year}_{month:02d}.csv"
    return _multi_block_response(blocks, filename)


# ─── Экспорт Finance ─────────────────────────────────────────────────────────

@router.get("/finance")
async def export_finance(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Детальная финансовая выгрузка: P&L, расходы по категориям, все расходы."""
    from routers.finance import get_finance

    try:
        data = await get_finance(
            month=month,
            year=year,
            team_id=None,
            tenant=tenant,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("export finance error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка формирования экспорта")

    # Блок 1: P&L
    pnl_rows = [
        [r.label, _fmt(r.amount)]
        for r in (data.pnl_rows or [])
    ]

    # Блок 2: Расходы по категориям
    cat_rows = [
        [c["category"], _fmt(c["amount"])]
        for c in (data.expenses_by_category or [])
    ]

    # Блок 3: Все расходы за месяц (из БД)
    start, end = _month_range(year, month)
    exp_result = await db.execute(
        text(
            """SELECT e.date, ec.name AS category, m.name AS model_name,
                      e.amount, e.description, e.source
               FROM expenses e
               LEFT JOIN expense_categories ec ON ec.id = e.category_id
               LEFT JOIN models m ON m.id = e.model_id
               WHERE e.tenant_id = :tid
                 AND e.date >= :start AND e.date <= :end
               ORDER BY e.date DESC"""
        ),
        {"tid": tenant.id, "start": start, "end": end},
    )
    expense_rows = [
        [
            str(r["date"]),
            r["category"] or "",
            r["model_name"] or "",
            _fmt(r["amount"]),
            r["description"] or "",
            r["source"] or "",
        ]
        for r in exp_result.mappings()
    ]

    blocks: list[tuple[list[str], list[list]]] = [
        (["Статья P&L", "Сумма ($)"], pnl_rows),
        (["Категория", "Сумма ($)"], cat_rows),
        (["Дата", "Категория", "Модель", "Сумма ($)", "Описание", "Источник"], expense_rows),
    ]

    filename = f"finance_{year}_{month:02d}.csv"
    return _multi_block_response(blocks, filename)
