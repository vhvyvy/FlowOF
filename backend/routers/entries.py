"""Ручной учёт: CRUD транзакций и расходов."""
from __future__ import annotations

from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])

# ─── Schemas ─────────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    date: DateType
    model_id: int
    chatter_id: int
    shift_catalog_id: Optional[int] = None
    amount: float


class TransactionUpdate(BaseModel):
    date: DateType
    model_id: int
    chatter_id: int
    shift_catalog_id: Optional[int] = None
    amount: float


# ─── ТРАНЗАКЦИИ ──────────────────────────────────────────────────────────────

@router.post("/transactions", status_code=201)
async def create_transaction(
    data: TransactionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    tx = Transaction(
        tenant_id=tenant.id,
        date=data.date,
        model_id=data.model_id,
        chatter_id=data.chatter_id,
        shift_catalog_id=data.shift_catalog_id,
        amount=data.amount,
        source="manual",
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return {"id": tx.id, "success": True}


@router.get("/transactions")
async def list_transactions(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    source: Optional[str] = Query(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Список транзакций за месяц с JOIN на справочники.

    Для импортированных строк (model_id IS NULL) возвращает строковые имена
    из колонок model / chatter / shift_name.
    source-фильтр учитывает NULL source как 'import'.
    """
    base_sql = """
        SELECT
            t.id,
            t.date,
            t.amount,
            t.model_id,
            t.chatter_id,
            t.shift_catalog_id,
            COALESCE(t.source, 'import')            AS source,
            COALESCE(m.name,  t.model)              AS model_name,
            COALESCE(c.name,  t.chatter)            AS chatter_name,
            COALESCE(sc.name, t.shift_name)         AS shift_name
        FROM transactions t
        LEFT JOIN models         m  ON t.model_id         = m.id
        LEFT JOIN chatters       c  ON t.chatter_id       = c.id
        LEFT JOIN shifts_catalog sc ON t.shift_catalog_id = sc.id
        WHERE t.tenant_id = :tid
          AND t.date IS NOT NULL
          AND EXTRACT(MONTH FROM t.date) = :month
          AND EXTRACT(YEAR  FROM t.date) = :year
    """
    params: dict = {"tid": tenant.id, "month": month, "year": year}

    if source:
        base_sql += " AND COALESCE(t.source, 'import') = :source"
        params["source"] = source

    base_sql += " ORDER BY t.date DESC, t.id DESC"

    result = await db.execute(text(base_sql), params)
    return {"items": [dict(r) for r in result.mappings()]}


@router.put("/transactions/{tx_id}")
async def update_transaction(
    tx_id: int,
    data: TransactionUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    tx = await db.get(Transaction, tx_id)
    if not tx or tx.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Не найдено")
    tx.date = data.date
    tx.model_id = data.model_id
    tx.chatter_id = data.chatter_id
    tx.shift_catalog_id = data.shift_catalog_id
    tx.amount = data.amount
    tx.source = "manual"  # правка отвязывает от автосинка
    await db.commit()
    return {"success": True}


@router.delete("/transactions/{tx_id}")
async def delete_transaction(
    tx_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    tx = await db.get(Transaction, tx_id)
    if not tx or tx.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Не найдено")
    await db.delete(tx)
    await db.commit()
    return {"success": True}
