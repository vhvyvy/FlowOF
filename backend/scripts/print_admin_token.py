"""Print JWT for first active admin (screenshot scripts)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local")
os.environ.setdefault("FILE_STORAGE_ROOT", "./local_storage")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from database import _asyncpg_connect_args
from models import User
from auth import create_access_token

_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url:
    raise SystemExit("Set DATABASE_URL")
if "?sslmode=" in _db_url:
    _db_url = _db_url.split("?sslmode=")[0]
_engine = create_async_engine(
    _db_url, connect_args={**_asyncpg_connect_args(_db_url), "timeout": 120}
)
Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


async def main() -> None:
    tenant_filter = os.environ.get("TENANT_ID")
    async with Session() as db:
        q = select(User).where(User.is_admin == True, User.active == True)  # noqa: E712
        if tenant_filter:
            q = q.where(User.tenant_id == int(tenant_filter))
        q = q.order_by(User.tenant_id, User.id).limit(1)
        admin = (await db.execute(q)).scalar_one()
        token = create_access_token(
            tenant_id=admin.tenant_id,
            email=admin.email,
            user_id=admin.id,
            role=admin.role,
        )
        print(token)
    await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
