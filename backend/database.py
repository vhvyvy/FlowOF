import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("skynet.db")

_raw_url = os.getenv("DATABASE_URL", "")

# Normalize to asyncpg driver
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgresql://") and "+asyncpg" not in _raw_url:
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Strip sslmode from URL — asyncpg uses connect_args for SSL, not URL params
if "?sslmode=" in _raw_url:
    _raw_url = _raw_url.split("?sslmode=")[0]
elif "&sslmode=" in _raw_url:
    _raw_url = _raw_url.replace("&sslmode=require", "").replace("&sslmode=prefer", "")

DATABASE_URL: str = _raw_url

if not DATABASE_URL:
    logger.warning("DATABASE_URL is not set — database calls will fail at runtime")

engine = create_async_engine(
    DATABASE_URL or "postgresql+asyncpg://placeholder/placeholder",
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    connect_args={"ssl": "require"} if DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
