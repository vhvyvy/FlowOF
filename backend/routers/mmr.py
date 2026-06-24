"""
MMR-роутер (Этап 1): только ручной пересчёт.
Этапы 2-5 добавят остальные эндпоинты.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner
from models import User
from services.mmr_service import MMRService

router = APIRouter(prefix="/api/v1/mmr", tags=["mmr"])


class RecalculateRequest(BaseModel):
    date: date


@router.post("/recalculate")
async def recalculate_day(
    body: RecalculateRequest,
    owner: User = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """
    Ручной пересчёт MMR за конкретный день.
    Идемпотентен — предыдущие события за этот день сначала удаляются.
    """
    try:
        service = MMRService(db)
        result = await service.process_day(owner.tenant_id, body.date)
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
