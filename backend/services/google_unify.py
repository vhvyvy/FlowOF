"""
Хранение/выдача Google-токенов через tenant_sources.

Credentials шифруются Fernet (services/credentials_crypto.py).
Если access_token истёк — автоматически обновляется через refresh_token.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import TenantSource
from services.credentials_crypto import decrypt_credentials_blob, encrypt_credentials_blob
from services.google_sheets_service import GoogleAuthError, GoogleSheetsService

logger = logging.getLogger("flowof.google_unify")

SOURCE_TYPE = "google_sheets"


async def _get_active_source(db: AsyncSession, tenant_id: int) -> TenantSource | None:
    r = await db.execute(
        select(TenantSource).where(
            TenantSource.tenant_id == tenant_id,
            TenantSource.source_type == SOURCE_TYPE,
        )
    )
    # Берём самую свежую (если их по какой-то причине несколько).
    rows = list(r.scalars().all())
    if not rows:
        return None
    rows.sort(key=lambda x: x.id, reverse=True)
    return rows[0]


async def save_google_tokens(
    db: AsyncSession,
    tenant_id: int,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_in: int | None = None,
) -> TenantSource:
    """Создать/обновить tenant_sources(google_sheets) c зашифрованными токенами."""
    expires_at = int(time.time()) + int(expires_in or 3600) - 60  # buffer 60s
    payload: dict[str, Any] = {
        "kind": "google_sheets",
        "access_token": access_token,
        "expires_at": expires_at,
    }
    if refresh_token:
        payload["refresh_token"] = refresh_token

    existing = await _get_active_source(db, tenant_id)
    if existing:
        # При повторном OAuth Google не всегда возвращает refresh_token — сохраняем старый.
        if not refresh_token:
            old = decrypt_credentials_blob(existing.credentials or {})
            if old.get("refresh_token"):
                payload["refresh_token"] = old["refresh_token"]
        existing.credentials = encrypt_credentials_blob(payload)
        # active оставляем как есть — станет True после успешного выбора таблицы.
        await db.commit()
        await db.refresh(existing)
        return existing

    row = TenantSource(
        tenant_id=tenant_id,
        source_type=SOURCE_TYPE,
        credentials=encrypt_credentials_blob(payload),
        active=False,
        mapping_config={"version": 1},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_google_access_token(db: AsyncSession, tenant_id: int) -> str:
    """
    Вернуть рабочий access_token. Если истёк — обновить через refresh_token и сохранить.
    Бросает GoogleAuthError если соединение не настроено или refresh не удался.
    """
    source = await _get_active_source(db, tenant_id)
    if not source or not source.credentials:
        raise GoogleAuthError("Google не подключён для этого тенанта")
    data = decrypt_credentials_blob(source.credentials)
    access_token = (data.get("access_token") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip() or None
    expires_at = int(data.get("expires_at") or 0)

    if access_token and time.time() < expires_at:
        return access_token

    if not refresh_token:
        raise GoogleAuthError("Access token истёк, refresh_token отсутствует — нужен повторный вход")

    fresh = await GoogleSheetsService.refresh_access_token(refresh_token)
    new_access = (fresh.get("access_token") or "").strip()
    if not new_access:
        raise GoogleAuthError("Google не вернул новый access_token")
    new_refresh = (fresh.get("refresh_token") or "").strip() or refresh_token
    expires_in = int(fresh.get("expires_in") or 3600)
    payload = {
        "kind": "google_sheets",
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": int(time.time()) + expires_in - 60,
    }
    source.credentials = encrypt_credentials_blob(payload)
    await db.commit()
    return new_access


async def save_selected_spreadsheet(
    db: AsyncSession,
    tenant_id: int,
    *,
    spreadsheet_id: str,
    sheet_name: str,
    activate: bool = True,
) -> None:
    """Сохранить выбор пользователя в mapping_config; опционально активировать источник."""
    source = await _get_active_source(db, tenant_id)
    if not source:
        raise GoogleAuthError("Сначала пройдите OAuth Google")
    cfg = dict(source.mapping_config or {})
    cfg.update(
        {
            "version": 1,
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
        }
    )
    source.mapping_config = cfg
    if activate:
        source.active = True
    await db.commit()
