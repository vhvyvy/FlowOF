"""
Google Sheets / Drive API клиент.

Используем только публичные REST-эндпоинты Google + httpx (без google-python SDK,
чтобы не тащить лишние зависимости в Railway image).

Минимальные права: drive.readonly + spreadsheets.readonly.
"""
from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("flowof.google_sheets")


class GoogleAuthError(Exception):
    """Не получилось получить/обновить access_token (нужен повторный OAuth)."""


class GoogleSheetsService:
    """Тонкий клиент для Sheets/Drive поверх access_token."""

    def __init__(self, access_token: str, *, refresh_token: str | None = None):
        if not access_token:
            raise ValueError("access_token пустой")
        self.access_token = access_token.strip()
        self.refresh_token = (refresh_token or "").strip() or None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    # ─────────────────────────── List ───────────────────────────

    async def list_spreadsheets(self, *, page_size: int = 20) -> list[dict[str, Any]]:
        """Последние Google Sheets из Drive пользователя."""
        params = {
            "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            "fields": "files(id,name,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": page_size,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=self.headers,
                params=params,
            )
        if r.status_code == 401:
            raise GoogleAuthError("Access token истёк, нужен refresh")
        r.raise_for_status()
        return r.json().get("files", [])

    async def list_sheets(self, spreadsheet_id: str) -> list[dict[str, Any]]:
        """Имена/ID листов внутри таблицы."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
                headers=self.headers,
                params={"fields": "sheets.properties"},
            )
        if r.status_code == 401:
            raise GoogleAuthError("Access token истёк, нужен refresh")
        r.raise_for_status()
        out: list[dict[str, Any]] = []
        for s in r.json().get("sheets", []) or []:
            props = s.get("properties") or {}
            out.append({"id": props.get("sheetId"), "name": props.get("title", "")})
        return out

    # ─────────────────────────── Download ───────────────────────────

    async def download_as_csv(self, spreadsheet_id: str, sheet_name: str) -> str:
        """Скачать значения листа и собрать CSV-строку (utf-8)."""
        # Quote sheet name — пробелы/кириллица/символы.
        from urllib.parse import quote

        range_name = quote(sheet_name, safe="")
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{range_name}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self.headers)

        if r.status_code == 401:
            raise GoogleAuthError("Access token истёк, нужен refresh")
        r.raise_for_status()

        data = r.json()
        rows = data.get("values", []) or []
        if not rows:
            return ""

        # Выравниваем длину строк (Google режет хвостовые пустые ячейки) — иначе pandas путается.
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]

        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in normalized:
            writer.writerow(row)
        return buf.getvalue()

    # ─────────────────────────── Refresh ───────────────────────────

    @staticmethod
    async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
        """Обновить access_token через refresh_token. Возвращает {access_token, expires_in, ...}."""
        client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret:
            raise GoogleAuthError("GOOGLE_CLIENT_ID/SECRET не настроены")
        if not refresh_token:
            raise GoogleAuthError("refresh_token отсутствует")

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                },
            )
        if r.status_code != 200:
            raise GoogleAuthError(f"Token refresh failed: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    @staticmethod
    async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict[str, Any]:
        """Обменять authorization code на access/refresh токены."""
        client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
        if not client_id or not client_secret:
            raise GoogleAuthError("GOOGLE_CLIENT_ID/SECRET не настроены")

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if r.status_code != 200:
            raise GoogleAuthError(f"Code exchange failed: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        if "error" in data:
            raise GoogleAuthError(f"Google: {data.get('error_description') or data['error']}")
        return data
