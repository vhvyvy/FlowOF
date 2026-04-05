"""
PostgreSQL: SQLAlchemy create_all does NOT add new columns to existing tables.
Apply lightweight ALTERs so production DBs stay compatible.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("flowof.schema")

# (sql, critical) — critical ALTERs raise on failure so missing columns do not cause 500s later
_PATCHES: list[tuple[str, bool]] = [
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS team_id INTEGER", True),
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS notion_database_id VARCHAR(64)", True),
    ("CREATE INDEX IF NOT EXISTS ix_transactions_team_id ON transactions (team_id)", False),
    ("CREATE INDEX IF NOT EXISTS ix_transactions_notion_database_id ON transactions (notion_database_id)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS notion_database_id VARCHAR(64)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS inherit_economics BOOLEAN DEFAULT TRUE", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS chatter_max_pct NUMERIC(5, 2)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS default_chatter_pct NUMERIC(5, 2)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS admin_percent_total NUMERIC(5, 2)", False),
]


async def apply_schema_patches(engine: AsyncEngine) -> None:
    """Idempotent column / index additions."""
    async with engine.begin() as conn:
        for sql, critical in _PATCHES:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                if critical:
                    logger.exception("schema_patch critical: %s — %s", sql[:120], e)
                    raise
                logger.warning("schema_patch optional skip: %s — %s", sql[:120], e)
