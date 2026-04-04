from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import Tenant
from auth import decode_jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_tenant(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_jwt(token)
    if payload is None:
        raise credentials_exception

    tenant_id: int | None = payload.get("tenant_id")
    if tenant_id is None:
        raise credentials_exception

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()

    if tenant is None or not tenant.active:
        raise credentials_exception

    return tenant
