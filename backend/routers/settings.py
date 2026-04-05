import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, AppSetting
from pydantic import BaseModel
from typing import Optional
from schemas import SettingUpsert, SettingsResponse


class ProfileOut(BaseModel):
    name: str
    email: str
    has_onlymonster_key: bool
    onlymonster_key_preview: Optional[str] = None  # masked


class ProfileUpdate(BaseModel):
    onlymonster_key: Optional[str] = None
    onlymonster_account_ids: Optional[str] = None

logger = logging.getLogger("skynet.settings")
router = APIRouter(prefix="/api/v1", tags=["settings"])

DEFAULTS = {
    "model_percent": "23",
    "chatter_percent": "25",
    "admin_percent": "9",
    "withdraw_percent": "6",
    "use_withdraw": "1",
    "use_retention": "1",
}


@router.get("/profile", response_model=ProfileOut)
async def get_profile(
    tenant: Tenant = Depends(get_current_tenant),
):
    key = tenant.onlymonster_key or ""
    preview = f"{key[:6]}…{key[-4:]}" if len(key) > 10 else ("••••" if key else None)
    return ProfileOut(
        name=tenant.name,
        email=tenant.email,
        has_onlymonster_key=bool(key),
        onlymonster_key_preview=preview,
    )


@router.patch("/profile", response_model=ProfileOut)
async def update_profile(
    body: ProfileUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(select(Tenant).where(Tenant.id == tenant.id))
        t = result.scalar_one()
        if body.onlymonster_key is not None:
            # empty string = clear key
            t.onlymonster_key = body.onlymonster_key.strip() or None
        if body.onlymonster_account_ids is not None:
            t.onlymonster_account_ids = body.onlymonster_account_ids.strip() or None
        await db.commit()
        await db.refresh(t)
        key = t.onlymonster_key or ""
        preview = f"{key[:6]}…{key[-4:]}" if len(key) > 10 else ("••••" if key else None)
        return ProfileOut(
            name=t.name,
            email=t.email,
            has_onlymonster_key=bool(key),
            onlymonster_key_preview=preview,
        )
    except Exception as e:
        logger.error("profile update error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка сохранения профиля")


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(AppSetting).where(AppSetting.tenant_id == tenant.id)
        )
        rows = result.scalars().all()
        data = {**DEFAULTS, **{r.key: r.value for r in rows}}
        return SettingsResponse(settings=data)
    except Exception as e:
        logger.error("settings get error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка загрузки настроек")


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    body: dict[str, str],
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        allowed_keys = set(DEFAULTS.keys())
        for key, value in body.items():
            if key not in allowed_keys:
                continue
            stmt = (
                pg_insert(AppSetting)
                .values(tenant_id=tenant.id, key=key, value=value)
                .on_conflict_do_update(
                    index_elements=["tenant_id", "key"],
                    set_={"value": value},
                )
            )
            await db.execute(stmt)
        await db.commit()

        result = await db.execute(
            select(AppSetting).where(AppSetting.tenant_id == tenant.id)
        )
        rows = result.scalars().all()
        data = {**DEFAULTS, **{r.key: r.value for r in rows}}
        return SettingsResponse(settings=data)
    except Exception as e:
        logger.error("settings put error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail="Ошибка сохранения настроек")
