import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Tenant
from auth import hash_password
from schemas import TenantCreate, TenantOut, TenantPasswordUpdate

logger = logging.getLogger("skynet.admin")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")


def _require_admin(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    result = await db.execute(select(Tenant).order_by(Tenant.id))
    return result.scalars().all()


@router.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    # Check email uniqueness
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


@router.patch("/tenants/{tenant_id}/password", status_code=204)
async def update_password(
    tenant_id: int,
    body: TenantPasswordUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.password_hash = hash_password(body.password)
    await db.commit()
    logger.info("Password updated for tenant=%d", tenant_id)


@router.patch("/tenants/{tenant_id}/toggle", response_model=TenantOut)
async def toggle_active(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_admin),
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
