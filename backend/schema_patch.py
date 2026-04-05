"""
PostgreSQL: SQLAlchemy create_all does NOT add new columns to existing tables.
Apply lightweight ALTERs so production DBs stay compatible.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("skynet.schema")


async def apply_schema_patches(engine: AsyncEngine) -> None:
    """Idempotent column / index additions."""
    stmts = [
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS team_id INTEGER",
        "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS notion_database_id VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_team_id ON transactions (team_id)",
        "CREATE INDEX IF NOT EXISTS ix_transactions_notion_database_id ON transactions (notion_database_id)",
    ]
    async with engine.begin() as conn:
        for sql in stmts:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                logger.warning("schema_patch skip: %s — %s", sql[:60], e)
