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
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS color_key VARCHAR(32)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS inherit_economics BOOLEAN DEFAULT TRUE", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS chatter_max_pct NUMERIC(5, 2)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS default_chatter_pct NUMERIC(5, 2)", False),
    ("ALTER TABLE teams_mt ADD COLUMN IF NOT EXISTS admin_percent_total NUMERIC(5, 2)", False),
    # Этап 1: onboarding + источники + журнал синков (дублирует Alembic 20260405_01 для деплоев без migrate)
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_step INTEGER NOT NULL DEFAULT 0", False),
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE", False),
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS source_type VARCHAR(64)", False),
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMP", False),
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS currency VARCHAR(8) NOT NULL DEFAULT 'USD'", False),
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS agency_name VARCHAR(255)", False),
    (
        """CREATE TABLE IF NOT EXISTS tenant_sources (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_type VARCHAR(64) NOT NULL,
            credentials JSONB,
            mapping_config JSONB,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_tenant_sources_tenant_id ON tenant_sources (tenant_id)", False),
    (
        """CREATE TABLE IF NOT EXISTS sync_log (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_type VARCHAR(64),
            started_at TIMESTAMP NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMP,
            rows_imported INTEGER NOT NULL DEFAULT 0,
            rows_skipped INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            error_message TEXT
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_sync_log_tenant_id ON sync_log (tenant_id)", False),
    # Старые тенанты без agency_name — не блокировать онбордингом (новые с регистрации заполняют agency_name)
    (
        "UPDATE tenants SET onboarding_completed = TRUE WHERE agency_name IS NULL "
        "AND COALESCE(onboarding_completed, FALSE) = FALSE",
        False,
    ),
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
