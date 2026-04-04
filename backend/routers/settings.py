import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, AppSetting
from schemas import SettingUpsert, SettingsResponse

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
