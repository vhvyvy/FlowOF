"""Заглушка Google Sheets (отдельная фаза: OAuth + адаптер)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/google-sheets/status")
async def get_google_sheets_status():
    return {
        "available": False,
        "phase": "later",
        "message": "Интеграция Google Таблиц запланирована отдельной фазой (OAuth2 и адаптер).",
    }
