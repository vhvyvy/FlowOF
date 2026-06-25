"""Авансы и штрафы чаттерам."""
from __future__ import annotations

from datetime import date as DateType

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner
from models import User

router = APIRouter(prefix="/api/v1/adjustments", tags=["adjustments"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class AdjustmentCreate(BaseModel):
    chatter_id: int
    type: str           # 'advance' | 'penalty'
    amount: float
    description: str | None = None
    date: DateType


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_adjustment(
    data: AdjustmentCreate,
    user: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    if data.type not in ("advance", "penalty"):
        raise HTTPException(status_code=422, detail="type must be 'advance' or 'penalty'")
    if data.amount <= 0:
        raise HTTPException(status_code=422, detail="amount must be positive")

    # Verify chatter belongs to this tenant
    chatter_result = await db.execute(
        text("SELECT id FROM chatters WHERE id = :cid AND tenant_id = :tid"),
        {"cid": data.chatter_id, "tid": user.tenant_id},
    )
    if not chatter_result.mappings().first():
        raise HTTPException(status_code=404, detail="Чаттер не найден")

    result = await db.execute(
        text(
            """INSERT INTO chatter_adjustments
               (tenant_id, chatter_id, type, amount, description, date, created_by_user_id)
               VALUES (:tid, :cid, :type, :amount, :desc, :date, :uid)
               RETURNING id"""
        ),
        {
            "tid": user.tenant_id,
            "cid": data.chatter_id,
            "type": data.type,
            "amount": data.amount,
            "desc": data.description,
            "date": data.date,
            "uid": user.id,
        },
    )
    new_id = result.scalar()
    await db.commit()
    return {"id": new_id, "success": True}


@router.get("")
async def list_adjustments(
    chatter_id: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2000),
    user: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """SELECT a.id, a.type, a.amount, a.description, a.date, a.created_at
               FROM chatter_adjustments a
               WHERE a.tenant_id = :tid
                 AND a.chatter_id = :cid
                 AND EXTRACT(MONTH FROM a.date) = :month
                 AND EXTRACT(YEAR  FROM a.date) = :year
               ORDER BY a.date DESC, a.id DESC"""
        ),
        {"tid": user.tenant_id, "cid": chatter_id, "month": month, "year": year},
    )
    items = []
    for r in result.mappings():
        row = dict(r)
        row["date"] = str(row["date"])
        row["amount"] = float(row["amount"] or 0)
        row["created_at"] = str(row["created_at"]) if row.get("created_at") else None
        items.append(row)
    return {"items": items}


@router.delete("/{adj_id}")
async def delete_adjustment(
    adj_id: int,
    user: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT id FROM chatter_adjustments WHERE id = :id AND tenant_id = :tid"),
        {"id": adj_id, "tid": user.tenant_id},
    )
    if not result.mappings().first():
        raise HTTPException(status_code=404, detail="Не найдено")
    await db.execute(
        text("DELETE FROM chatter_adjustments WHERE id = :id"),
        {"id": adj_id},
    )
    await db.commit()
    return {"success": True}
