import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Tenant
from auth import verify_password, create_access_token, hash_password
from dependencies import get_current_tenant
from schemas import LoginRequest, TokenResponse, TenantOut, RegisterRequest, RegisterResponse

logger = logging.getLogger("flowof.auth")
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

    stored_hash = tenant.password_hash or ""
    if not verify_password(body.password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    # Migrate legacy SHA-256 → bcrypt on first successful login
    if not stored_hash.startswith("$2"):
        tenant.password_hash = hash_password(body.password)
        await db.commit()
        logger.info("Migrated password hash for tenant=%d to bcrypt", tenant.id)

    token = create_access_token(tenant.id, tenant.email)
    logger.info("Login success tenant=%d", tenant.id)
    return TokenResponse(access_token=token)


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = str(body.email).lower().strip()
    agency = body.agency_name.strip()
    existing = await db.execute(select(Tenant).where(Tenant.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован",
        )

    slug = email.split("@")[0].lower().replace(".", "-")

    tenant = Tenant(
        name=agency,
        slug=slug,
        email=email,
        password_hash=hash_password(body.password),
        agency_name=agency,
        onboarding_step=0,
        onboarding_completed=False,
        currency="USD",
        plan="basic",
        active=True,
    )
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)

    token = create_access_token(tenant.id, tenant.email)
    logger.info("Register success tenant=%d email=%s", tenant.id, tenant.email)
    return RegisterResponse(
        access_token=token,
        token_type="bearer",
        onboarding_completed=bool(tenant.onboarding_completed),
    )


@router.get("/me", response_model=TenantOut)
async def me(tenant: Tenant = Depends(get_current_tenant)):
    return tenant
