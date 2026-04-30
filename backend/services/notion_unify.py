"""
Дублирование Notion token + списка database id в tenant_sources.credentials
(контракт пайплайна); источник истины для синка остаётся tenants.notion_token и команды.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from import_contract import NotionCredentialsPlain
from models import Tenant, TenantSource
from notion_sync_service import _collect_database_ids
from services.credentials_crypto import decrypt_credentials_blob, encrypt_credentials_blob
from team_helpers import list_teams

logger = logging.getLogger("flowof.notion_unify")


async def resolve_notion_token_for_sync(db: AsyncSession, tenant: Tenant) -> str | None:
    """Приоритет: tenants.notion_token; иначе расшифрованный token из активного tenant_sources (notion)."""
    direct = (tenant.notion_token or "").strip()
    if direct:
        return direct
    r = await db.execute(
        select(TenantSource).where(
            TenantSource.tenant_id == tenant.id,
            TenantSource.source_type == "notion",
            TenantSource.active.is_(True),
        )
    )
    row = r.scalar_one_or_none()
    if not row or not row.credentials:
        return None
    data = decrypt_credentials_blob(row.credentials)
    t = (data.get("token") or "").strip()
    return t or None


async def mirror_notion_credentials_to_tenant_source(db: AsyncSession, tenant: Tenant) -> None:
    """Создать/обновить активную строку tenant_sources с типом notion."""
    token = (tenant.notion_token or "").strip()
    teams = await list_teams(db, tenant.id)
    db_ids = _collect_database_ids(teams)

    if not token:
        await db.execute(
            update(TenantSource)
            .where(
                TenantSource.tenant_id == tenant.id,
                TenantSource.source_type == "notion",
            )
            .values(active=False)
        )
        return

    plain = NotionCredentialsPlain(token=token, database_ids=db_ids)
    blob: dict[str, Any] = encrypt_credentials_blob(plain.model_dump())

    r = await db.execute(
        select(TenantSource).where(
            TenantSource.tenant_id == tenant.id,
            TenantSource.source_type == "notion",
        )
    )
    row = r.scalar_one_or_none()
    if row:
        row.credentials = blob
        row.active = True
        row.mapping_config = {"version": 1, "env_main_db": bool(os.getenv("NOTION_TRANSACTIONS_DATABASE_ID"))}
    else:
        db.add(
            TenantSource(
                tenant_id=tenant.id,
                source_type="notion",
                credentials=blob,
                active=True,
                mapping_config={"version": 1},
            )
        )
    logger.info("notion tenant_sources mirrored tenant=%s", tenant.id)
