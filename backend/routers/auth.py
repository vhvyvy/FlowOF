import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import Tenant, User
from auth import verify_password, create_access_token, hash_password
from dependencies import get_current_tenant
from schemas import LoginRequest, TokenResponse, TenantOut, RegisterRequest, RegisterResponse

logger = logging.getLogger("flowof.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = body.email.lower().strip()

    # ── Поиск в таблице users (новая архитектура) ────────────────────────────
    user_result = await db.execute(
        select(User).where(User.email == email)
    )
    user = user_result.scalar_one_or_none()

    if user is not None:
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Аккаунт деактивирован",
            )
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль",
            )
        # Обновить last_login_at
        user.last_login_at = datetime.utcnow()
        # Мигрируем старый SHA-256 хэш → bcrypt при первом входе
        if not user.hashed_password.startswith("$2"):
            user.hashed_password = hash_password(body.password)
        await db.commit()

        token = create_access_token(
            tenant_id=user.tenant_id,
            email=user.email,
            user_id=user.id,
            role=user.role,
        )
        logger.info("Login success user=%d role=%s", user.id, user.role)
        return TokenResponse(access_token=token, role=user.role)

    # ── Fallback: старые tenants до миграции ─────────────────────────────────
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.email == email)
    )
    tenant = tenant_result.scalar_one_or_none()

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

    # Мигрируем SHA-256 → bcrypt
    if not stored_hash.startswith("$2"):
        tenant.password_hash = hash_password(body.password)

    # Создаём User на лету (migration might not have run for this tenant yet)
    new_user = User(
        tenant_id=tenant.id,
        email=email,
        hashed_password=tenant.password_hash or hash_password(body.password),
        role="owner",
        full_name=tenant.agency_name or tenant.name or "",
        is_admin=bool(getattr(tenant, "is_admin", False)),
        last_login_at=datetime.utcnow(),
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)
    await db.commit()

    token = create_access_token(
        tenant_id=tenant.id,
        email=email,
        user_id=new_user.id,
        role="owner",
    )
    logger.info("Login fallback (created user) tenant=%d", tenant.id)
    return TokenResponse(access_token=token, role="owner")


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    email = str(body.email).lower().strip()
    agency = body.agency_name.strip()

    # Проверяем на дубликат email в tenants и users
    existing_tenant = await db.execute(select(Tenant).where(Tenant.email == email))
    if existing_tenant.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован",
        )
    existing_user = await db.execute(select(User).where(User.email == email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email уже зарегистрирован",
        )

    slug = email.split("@")[0].lower().replace(".", "-")
    hashed = hash_password(body.password)

    tenant = Tenant(
        name=agency,
        slug=slug,
        email=email,
        password_hash=hashed,
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

    # Создаём User owner
    user = User(
        tenant_id=tenant.id,
        email=email,
        hashed_password=hashed,
        role="owner",
        full_name=agency,
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    await db.commit()

    token = create_access_token(
        tenant_id=tenant.id,
        email=email,
        user_id=user.id,
        role="owner",
    )
    logger.info("Register success user=%d tenant=%d email=%s", user.id, tenant.id, email)
    return RegisterResponse(
        access_token=token,
        token_type="bearer",
        onboarding_completed=bool(tenant.onboarding_completed),
        role="owner",
    )


@router.get("/me", response_model=TenantOut)
async def me(tenant: Tenant = Depends(get_current_tenant)):
    return tenant
