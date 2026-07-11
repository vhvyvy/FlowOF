"""Print owner JWT for tenant=1 (screenshots)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from database import _asyncpg_connect_args
from models import User
from auth import create_access_token

_db_url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@"
    "ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb",
)
if "?sslmode=" in _db_url:
    _db_url = _db_url.split("?sslmode=")[0]
_engine = create_async_engine(
    _db_url, connect_args={**_asyncpg_connect_args(_db_url), "timeout": 120}
)
Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


async def main() -> None:
    async with Session() as db:
        owner = (
            await db.execute(
                select(User).where(
                    User.tenant_id == 1,
                    User.role == "owner",
                    User.active == True,  # noqa: E712
                ).limit(1)
            )
        ).scalar_one()
        print(
            create_access_token(
                tenant_id=owner.tenant_id,
                email=owner.email,
                user_id=owner.id,
                role=owner.role,
            )
        )
    await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
