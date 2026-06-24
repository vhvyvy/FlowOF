"""Справочники ручного учёта: модели, чаттеры, смены, категории расходов."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import CatalogChatter, CatalogModel, ExpenseCategory, ShiftCatalog, Tenant

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _item(obj) -> dict:
    return {"id": obj.id, "name": obj.name}


def _shift_item(obj: ShiftCatalog) -> dict:
    return {"id": obj.id, "name": obj.name, "sort_order": obj.sort_order}


# ─── МОДЕЛИ ──────────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CatalogModel)
        .where(CatalogModel.tenant_id == tenant.id, CatalogModel.active.is_(True))
        .order_by(CatalogModel.name)
    )
    return {"items": [_item(m) for m in result.scalars()]}


@router.post("/models", status_code=201)
async def create_model(
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = CatalogModel(tenant_id=tenant.id, name=name.strip())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _item(obj)


@router.patch("/models/{model_id}")
async def rename_model(
    model_id: int,
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(CatalogModel, model_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.name = name.strip()
    await db.commit()
    return _item(obj)


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(CatalogModel, model_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.active = False  # soft delete
    await db.commit()
    return {"success": True}


# ─── ЧАТТЕРЫ ─────────────────────────────────────────────────────────────────

@router.get("/chatters")
async def list_chatters(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # JOIN с users чтобы вернуть статус аккаунта для каждого чаттера
    result = await db.execute(
        text(
            """SELECT c.id, c.name,
                      u.id AS user_id,
                      u.last_login_at,
                      u.email AS user_email
               FROM chatters c
               LEFT JOIN users u ON u.chatter_id = c.id AND u.active = TRUE AND u.role = 'chatter'
               WHERE c.tenant_id = :tid AND c.active = TRUE
               ORDER BY c.name"""
        ),
        {"tid": tenant.id},
    )
    items = []
    for row in result.mappings():
        items.append({
            "id": row["id"],
            "name": row["name"],
            "user_id": row["user_id"],
            "user_email": row["user_email"],
            "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
            "has_account": row["user_id"] is not None,
        })
    return {"items": items}


@router.post("/chatters", status_code=201)
async def create_chatter(
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = CatalogChatter(tenant_id=tenant.id, name=name.strip())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _item(obj)


@router.patch("/chatters/{chatter_id}")
async def rename_chatter(
    chatter_id: int,
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(CatalogChatter, chatter_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.name = name.strip()
    await db.commit()
    return _item(obj)


@router.delete("/chatters/{chatter_id}")
async def delete_chatter(
    chatter_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(CatalogChatter, chatter_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.active = False
    await db.commit()
    return {"success": True}


# ─── СМЕНЫ ───────────────────────────────────────────────────────────────────

@router.get("/shifts")
async def list_shifts(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ShiftCatalog)
        .where(ShiftCatalog.tenant_id == tenant.id, ShiftCatalog.active.is_(True))
        .order_by(ShiftCatalog.sort_order, ShiftCatalog.name)
    )
    return {"items": [_shift_item(s) for s in result.scalars()]}


@router.post("/shifts", status_code=201)
async def create_shift(
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = ShiftCatalog(tenant_id=tenant.id, name=name.strip())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _shift_item(obj)


@router.patch("/shifts/{shift_id}")
async def update_shift(
    shift_id: int,
    name: str | None = Query(None),
    sort_order: int | None = Query(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ShiftCatalog, shift_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    if name is not None:
        obj.name = name.strip()
    if sort_order is not None:
        obj.sort_order = sort_order
    await db.commit()
    return _shift_item(obj)


@router.delete("/shifts/{shift_id}")
async def delete_shift(
    shift_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ShiftCatalog, shift_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.active = False
    await db.commit()
    return {"success": True}


# ─── КАТЕГОРИИ РАСХОДОВ ───────────────────────────────────────────────────────

@router.get("/expense-categories")
async def list_expense_categories(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExpenseCategory)
        .where(ExpenseCategory.tenant_id == tenant.id, ExpenseCategory.active.is_(True))
        .order_by(ExpenseCategory.name)
    )
    return {"items": [_item(c) for c in result.scalars()]}


@router.post("/expense-categories", status_code=201)
async def create_expense_category(
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = ExpenseCategory(tenant_id=tenant.id, name=name.strip())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _item(obj)


@router.patch("/expense-categories/{cat_id}")
async def rename_expense_category(
    cat_id: int,
    name: str = Query(..., min_length=1),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ExpenseCategory, cat_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.name = name.strip()
    await db.commit()
    return _item(obj)


@router.delete("/expense-categories/{cat_id}")
async def delete_expense_category(
    cat_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(ExpenseCategory, cat_id)
    if not obj or obj.tenant_id != tenant.id:
        raise HTTPException(status_code=404)
    obj.active = False
    await db.commit()
    return {"success": True}
