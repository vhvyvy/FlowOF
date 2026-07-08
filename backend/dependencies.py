from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import Tenant, User
from auth import decode_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_CREDS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Декодирует JWT и возвращает пользователя из таблицы users.

    Поддерживает оба формата токена:
    - Новый: {user_id, tenant_id, role, email}
    - Старый: {tenant_id, email} — ищет owner-пользователя по tenant_id
    """
    payload = decode_jwt(token)
    if payload is None:
        raise _CREDS_EXC

    # ── Новый формат: user_id в токене ──────────────────────────────────────
    user_id = payload.get("user_id")
    if user_id is not None:
        user = await db.get(User, int(user_id))
        if user and user.active:
            return user
        raise _CREDS_EXC

    # ── Старый формат: только tenant_id + email (обратная совместимость) ────
    tenant_id = payload.get("tenant_id")
    if tenant_id is not None:
        result = await db.execute(
            select(User).where(
                and_(User.tenant_id == int(tenant_id), User.role == "owner")
            )
        )
        user = result.scalar_one_or_none()
        if user and user.active:
            return user

    raise _CREDS_EXC


async def get_current_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Возвращает Tenant для текущего user.

    Требует роль 'owner' — автоматически закрывает все owner-эндпоинты
    от чаттеров, если те каким-то образом получат токен.
    """
    if user.role not in ("owner",):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только для владельцев агентства",
        )
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None or not tenant.active:
        raise _CREDS_EXC
    return tenant


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """Разрешает доступ только role='owner'."""
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только для владельцев агентства",
        )
    return user


async def require_chatter(user: User = Depends(get_current_user)) -> User:
    """Разрешает доступ только role='chatter'."""
    if user.role != "chatter":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для чаттеров",
        )
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Разрешает доступ только пользователям с is_admin=True в своём агентстве."""
    if not getattr(user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ только для администраторов агентства",
        )
    return user
