import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Tenant
from auth import verify_password, create_access_token, hash_password
from dependencies import get_current_tenant
from schemas import LoginRequest, TokenResponse, TenantOut

logger = logging.getLogger("skynet.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Tenant).where(Tenant.email == body.email.lower().strip())
    )
    tenant = result.scalar_one_or_none()

    if tenant is None or not tenant.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    stored_hash = tenant.hashed_password or tenant.password_hash or ""
    if not verify_password(body.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    # Migrate legacy SHA-256 → bcrypt on first successful login
    if not stored_hash.startswith("$2"):
        tenant.hashed_password = hash_password(body.password)
        await db.commit()
        logger.info("Migrated password hash for tenant=%d to bcrypt", tenant.id)

    token = create_access_token(tenant.id, tenant.email)
    logger.info("Login success tenant=%d", tenant.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=TenantOut)
async def me(tenant: Tenant = Depends(get_current_tenant)):
    return tenant
