"""Онбординг: шаги квиза, статус, завершение."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant

logger = logging.getLogger("flowof.onboarding")

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

# Поля tenant, которые можно обновлять из шагов (без паролей/токенов)
_ALLOWED_DATA_KEYS = frozenset({"agency_name", "source_type", "currency", "name"})


class OnboardingStepRequest(BaseModel):
    step: int = Field(..., ge=1, le=5, description="Номер завершённого шага (1–5)")
    data: dict[str, Any] = Field(default_factory=dict)


class OnboardingStatusResponse(BaseModel):
    onboarding_completed: bool
    current_step: int  # последний сохранённый шаг в БД (0 = ещё не начали)
    source_type: Optional[str] = None
    agency_name: Optional[str] = None
    currency: str = "USD"
    next_ui_step: int  # какой экран показывать (1–5)


class OnboardingCompleteResponse(BaseModel):
    success: bool


def _next_ui_step(tenant: Tenant) -> int:
    s = tenant.onboarding_step or 0
    return max(1, min(s + 1, 5))


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(tenant: Tenant = Depends(get_current_tenant)):
    agency = tenant.agency_name or tenant.name
    cur = tenant.onboarding_step or 0
    return OnboardingStatusResponse(
        onboarding_completed=bool(tenant.onboarding_completed),
        current_step=cur,
        source_type=tenant.source_type,
        agency_name=agency,
        currency=(tenant.currency or "USD"),
        next_ui_step=_next_ui_step(tenant),
    )


@router.post("/step")
async def save_onboarding_step(
    body: OnboardingStepRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if tenant.onboarding_completed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Онбординг уже завершён",
        )

    tenant.onboarding_step = body.step

    for key, value in body.data.items():
        if key not in _ALLOWED_DATA_KEYS:
            continue
        if not hasattr(tenant, key):
            continue
        if value is None:
            setattr(tenant, key, None)
        elif isinstance(value, str):
            v = value.strip()
            setattr(tenant, key, v if v else None)
        elif isinstance(value, (int, float, bool)):
            setattr(tenant, key, value)

    if tenant.agency_name:
        tenant.name = tenant.agency_name

    await db.commit()
    await db.refresh(tenant)
    logger.info("onboarding step saved tenant=%d step=%d", tenant.id, body.step)
    return {"step": body.step, "saved": True, "next_ui_step": _next_ui_step(tenant)}


@router.post("/complete", response_model=OnboardingCompleteResponse)
async def complete_onboarding(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    tenant.onboarding_completed = True
    tenant.onboarding_step = max(tenant.onboarding_step or 0, 5)
    await db.commit()
    await db.refresh(tenant)
    logger.info("onboarding completed tenant=%d", tenant.id)
    return OnboardingCompleteResponse(success=True)
