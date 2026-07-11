"""Delete temporary screenshot test mapping from chatter_onlymonster_mapping."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import DATABASE_URL, _asyncpg_connect_args

OM_ID = os.environ.get("TEST_OM_ID", "9900719")

_engine = create_async_engine(
    DATABASE_URL,
    connect_args={**_asyncpg_connect_args(DATABASE_URL), "timeout": 120},
)
Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


async def main() -> None:
    if not DATABASE_URL:
        raise SystemExit("Set DATABASE_URL")
    async with Session() as db:
        result = await db.execute(
            text(
                "DELETE FROM chatter_onlymonster_mapping "
                "WHERE onlymonster_id = :om_id RETURNING tenant_id, display_names"
            ),
            {"om_id": OM_ID},
        )
        rows = result.fetchall()
        await db.commit()
        if rows:
            print(f"Deleted {len(rows)} row(s) for om_id={OM_ID}: {rows}")
        else:
            print(f"No rows found for om_id={OM_ID}")
    await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
