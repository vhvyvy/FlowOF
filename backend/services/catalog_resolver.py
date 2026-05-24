"""Матчинг текстовых имён со справочниками тенанта.

При импорте транзакций модели/чаттеры/смены хранятся как строки.
Эти функции ищут запись по имени в справочнике и создают её, если не находят.
Так импортированные данные сразу привязываются к catalog-записям и появляются
в формах ручного ввода.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import CatalogChatter, CatalogModel, ExpenseCategory, ShiftCatalog

logger = logging.getLogger("flowof.catalog_resolver")


def _clean(name: Optional[str]) -> Optional[str]:
    """Trim and return None for empty strings."""
    if not name:
        return None
    s = str(name).strip()
    return s if s else None


async def resolve_model_id(
    name: Optional[str],
    tenant_id: int,
    db: AsyncSession,
) -> Optional[int]:
    """Найти модель по имени или создать новую запись в справочнике."""
    name = _clean(name)
    if not name:
        return None
    result = await db.execute(
        select(CatalogModel).where(
            CatalogModel.tenant_id == tenant_id,
            CatalogModel.name == name,
        )
    )
    obj = result.scalar_one_or_none()
    if obj:
        if not obj.active:
            obj.active = True  # реактивируем если был soft-deleted
        return obj.id
    obj = CatalogModel(tenant_id=tenant_id, name=name, active=True)
    db.add(obj)
    await db.flush()
    logger.debug("catalog_resolver: created model '%s' tenant=%s id=%s", name, tenant_id, obj.id)
    return obj.id


async def resolve_chatter_id(
    name: Optional[str],
    tenant_id: int,
    db: AsyncSession,
) -> Optional[int]:
    """Найти чаттера по имени или создать новую запись в справочнике."""
    name = _clean(name)
    if not name:
        return None
    result = await db.execute(
        select(CatalogChatter).where(
            CatalogChatter.tenant_id == tenant_id,
            CatalogChatter.name == name,
        )
    )
    obj = result.scalar_one_or_none()
    if obj:
        if not obj.active:
            obj.active = True
        return obj.id
    obj = CatalogChatter(tenant_id=tenant_id, name=name, active=True)
    db.add(obj)
    await db.flush()
    logger.debug("catalog_resolver: created chatter '%s' tenant=%s id=%s", name, tenant_id, obj.id)
    return obj.id


async def resolve_shift_catalog_id(
    name: Optional[str],
    tenant_id: int,
    db: AsyncSession,
) -> Optional[int]:
    """Найти смену по имени или создать новую запись в справочнике.

    Принимает как текстовое имя смены, так и shift_name из транзакции.
    UUID-значения из старых Notion-импортов игнорируются.
    """
    name = _clean(name)
    if not name:
        return None
    # Пропускаем Notion-UUID: они не являются человеко-читаемыми именами смен
    import re
    _UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
    )
    if _UUID_RE.match(name):
        return None

    result = await db.execute(
        select(ShiftCatalog).where(
            ShiftCatalog.tenant_id == tenant_id,
            ShiftCatalog.name == name,
        )
    )
    obj = result.scalar_one_or_none()
    if obj:
        if not obj.active:
            obj.active = True
        return obj.id
    obj = ShiftCatalog(tenant_id=tenant_id, name=name, active=True)
    db.add(obj)
    await db.flush()
    logger.debug("catalog_resolver: created shift '%s' tenant=%s id=%s", name, tenant_id, obj.id)
    return obj.id


async def resolve_category_id(
    name: Optional[str],
    tenant_id: int,
    db: AsyncSession,
) -> Optional[int]:
    """Найти категорию расхода по имени или создать новую запись в справочнике."""
    name = _clean(name)
    if not name:
        return None
    result = await db.execute(
        select(ExpenseCategory).where(
            ExpenseCategory.tenant_id == tenant_id,
            ExpenseCategory.name == name,
        )
    )
    obj = result.scalar_one_or_none()
    if obj:
        if not obj.active:
            obj.active = True
        return obj.id
    obj = ExpenseCategory(tenant_id=tenant_id, name=name, active=True)
    db.add(obj)
    await db.flush()
    logger.debug("catalog_resolver: created category '%s' tenant=%s id=%s", name, tenant_id, obj.id)
    return obj.id
