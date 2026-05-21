import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from dependencies import get_current_tenant
from models import Tenant
from auth import hash_password
from schemas import TenantCreate, TenantOut, TenantPasswordUpdate, AdminTenantListItem, AdminTenantUpdate

logger = logging.getLogger("flowof.admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


# ── Зависимости ───────────────────────────────────────────────────────────────

def _require_secret(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    """Старый метод через статичный секрет (для CLI/скриптов)."""
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def _require_is_admin(
    tenant: Tenant = Depends(get_current_tenant),
) -> Tenant:
    """JWT-авторизация: тенант должен иметь is_admin = True."""
    if not getattr(tenant, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для администраторов",
        )
    return tenant


# ── Эндпоинты для фронт-панели (JWT + is_admin) ───────────────────────────────

@router.get("/tenants", response_model=list[AdminTenantListItem])
async def list_tenants_admin(
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Список всех тенантов для фронт-панели администратора."""
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    return result.scalars().all()


@router.get("/tenants/{tenant_id}", response_model=AdminTenantListItem)
async def get_tenant_detail(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/tenants/{tenant_id}", response_model=AdminTenantListItem)
async def update_tenant(
    tenant_id: int,
    body: AdminTenantUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Изменить plan / active / is_admin тенанта."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if body.plan is not None:
        if body.plan not in ("basic", "pro"):
            raise HTTPException(status_code=422, detail="plan должен быть 'basic' или 'pro'")
        tenant.plan = body.plan
    if body.active is not None:
        tenant.active = body.active
    if body.is_admin is not None:
        tenant.is_admin = body.is_admin

    await db.commit()
    await db.refresh(tenant)
    logger.info("Admin updated tenant=%d plan=%s active=%s", tenant_id, tenant.plan, tenant.active)
    return tenant


@router.delete("/tenants/{tenant_id}", status_code=204)
async def deactivate_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Tenant = Depends(_require_is_admin),
):
    """Деактивировать тенанта (soft delete)."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.active = False
    await db.commit()
    logger.info("Admin deactivated tenant=%d", tenant_id)


# ── Устаревшие эндпоинты через X-Admin-Secret (оставлены для CLI) ─────────────

@router.post("/tenants", response_model=TenantOut, status_code=201, include_in_schema=False)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    existing = await db.execute(select(Tenant).where(Tenant.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    slug = body.email.split("@")[0].lower().replace(".", "-")
    tenant = Tenant(
        name=body.name,
        slug=slug,
        email=body.email.lower().strip(),
        password_hash=hash_password(body.password),
        plan=body.plan,
        notion_token=body.notion_token,
        onlymonster_key=body.onlymonster_key,
        onlymonster_account_ids=body.onlymonster_account_ids,
        openai_key=body.openai_key,
        active=True,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    logger.info("Created tenant id=%d email=%s", tenant.id, tenant.email)
    return tenant


@router.patch("/tenants/{tenant_id}/password", status_code=204, include_in_schema=False)
async def update_password(
    tenant_id: int,
    body: TenantPasswordUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.password_hash = hash_password(body.password)
    await db.commit()
    logger.info("Password updated for tenant=%d", tenant_id)


@router.patch("/tenants/{tenant_id}/toggle", response_model=TenantOut, include_in_schema=False)
async def toggle_active(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_secret),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.active = not tenant.active
    await db.commit()
    await db.refresh(tenant)
    logger.info("Tenant=%d active=%s", tenant_id, tenant.active)
    return tenant
