"""
Google OAuth + перечисление Spreadsheets/Sheets.

Маршруты (все под /api/v1/google):
    GET  /auth-url               — URL для редиректа на Google consent screen
    GET  /callback               — Google редиректит сюда с ?code&state
    GET  /status                 — текущее состояние подключения тенанта
    GET  /spreadsheets           — список таблиц пользователя (из Drive)
    GET  /sheets/{spreadsheet_id} — список листов внутри таблицы
    POST /disconnect             — деактивировать подключение
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, decode_jwt
from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from services.google_sheets_service import GoogleAuthError, GoogleSheetsService
from services.google_unify import (
    SOURCE_TYPE,
    _get_active_source,
    get_google_access_token,
    save_google_tokens,
)

logger = logging.getLogger("flowof.google_auth")

router = APIRouter(prefix="/api/v1/google", tags=["google"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_SCOPES = " ".join(
    [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
)


def _client_credentials() -> tuple[str, str, str]:
    client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    redirect_uri = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth не настроен (GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI)",
        )
    return client_id, client_secret, redirect_uri


def _frontend_url() -> str:
    return (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")


# ─────────────────────────── OAuth ───────────────────────────


@router.get("/auth-url")
async def get_google_auth_url(
    tenant: Tenant = Depends(get_current_tenant),
) -> dict[str, str]:
    """Вернуть URL для Google consent screen. state = короткий JWT с tenant_id."""
    client_id, _, redirect_uri = _client_credentials()
    # state — JWT (используем существующий SECRET_KEY) с tenant_id; срок жизни короткий.
    state_token = create_access_token(tenant.id, tenant.email or "")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_token,
    }
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Google возвращает code+state → меняем на токены, сохраняем, редирект на фронт."""
    frontend = _frontend_url()
    if error:
        return RedirectResponse(f"{frontend}/onboarding?google_error={error}")

    payload = decode_jwt(state)
    if not payload or "tenant_id" not in payload:
        return RedirectResponse(f"{frontend}/onboarding?google_error=invalid_state")
    tenant_id = int(payload["tenant_id"])

    _, _, redirect_uri = _client_credentials()
    try:
        tokens = await GoogleSheetsService.exchange_code_for_tokens(code, redirect_uri)
    except GoogleAuthError as e:
        logger.warning("Google code exchange failed tenant=%s: %s", tenant_id, e)
        return RedirectResponse(f"{frontend}/onboarding?google_error=token_exchange_failed")

    access_token = (tokens.get("access_token") or "").strip()
    if not access_token:
        return RedirectResponse(f"{frontend}/onboarding?google_error=no_access_token")

    await save_google_tokens(
        db,
        tenant_id,
        access_token=access_token,
        refresh_token=(tokens.get("refresh_token") or "").strip() or None,
        expires_in=int(tokens.get("expires_in") or 3600),
    )

    return RedirectResponse(f"{frontend}/onboarding?google_connected=true")


# ─────────────────────────── State / lists ───────────────────────────


@router.get("/status")
async def get_google_status(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Состояние Google-подключения тенанта."""
    src = await _get_active_source(db, tenant.id)
    if not src:
        return {"connected": False, "active": False, "spreadsheet_id": None, "sheet_name": None}
    cfg = src.mapping_config or {}
    return {
        "connected": True,
        "active": bool(src.active),
        "spreadsheet_id": cfg.get("spreadsheet_id"),
        "sheet_name": cfg.get("sheet_name"),
    }


@router.get("/spreadsheets")
async def list_spreadsheets(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    try:
        access_token = await get_google_access_token(db, tenant.id)
    except GoogleAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    svc = GoogleSheetsService(access_token)
    try:
        files = await svc.list_spreadsheets()
    except GoogleAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.warning("list_spreadsheets failed tenant=%s: %s", tenant.id, e)
        raise HTTPException(status_code=502, detail="Не удалось получить список таблиц Google") from e
    return {"spreadsheets": files}


@router.get("/sheets/{spreadsheet_id}")
async def list_sheets(
    spreadsheet_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    try:
        access_token = await get_google_access_token(db, tenant.id)
    except GoogleAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    svc = GoogleSheetsService(access_token)
    try:
        sheets = await svc.list_sheets(spreadsheet_id)
    except GoogleAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception as e:
        logger.warning("list_sheets failed tenant=%s sid=%s: %s", tenant.id, spreadsheet_id, e)
        raise HTTPException(status_code=502, detail="Не удалось получить листы таблицы") from e
    return {"sheets": sheets}


# ─────────────────────────── Disconnect ───────────────────────────


@router.post("/disconnect")
async def disconnect_google(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    src = await _get_active_source(db, tenant.id)
    if not src:
        return {"ok": True}
    src.active = False
    await db.commit()
    logger.info("google disconnected tenant=%s source_type=%s", tenant.id, SOURCE_TYPE)
    return {"ok": True}
