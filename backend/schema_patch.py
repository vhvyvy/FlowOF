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
    # Multi-DB on a team: notion_database_id can hold several IDs (comma/newline separated)
    ("ALTER TABLE teams_mt ALTER COLUMN notion_database_id TYPE TEXT", False),
    # Admin panel
    ("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE", False),
    # Этап 1: справочники ручного учёта
    (
        """CREATE TABLE IF NOT EXISTS models (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_models_tenant_id ON models (tenant_id)", False),
    (
        """CREATE TABLE IF NOT EXISTS chatters (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_chatters_tenant_id ON chatters (tenant_id)", False),
    (
        """CREATE TABLE IF NOT EXISTS shifts_catalog (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            sort_order INTEGER DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_shifts_catalog_tenant_id ON shifts_catalog (tenant_id)", False),
    (
        """CREATE TABLE IF NOT EXISTS expense_categories (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_expense_categories_tenant_id ON expense_categories (tenant_id)", False),
    # Этап 2: новые колонки в transactions и expenses для ручного учёта
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS model_id INTEGER REFERENCES models(id)", False),
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS chatter_id INTEGER REFERENCES chatters(id)", False),
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS shift_catalog_id INTEGER REFERENCES shifts_catalog(id)", False),
    ("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source TEXT", False),
    ("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES expense_categories(id)", False),
    ("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS model_id INTEGER REFERENCES models(id)", False),
    ("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS description TEXT", False),
    ("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS source TEXT", False),
    # Бэкфилл: заполнить model_id/chatter_id/shift_catalog_id для ранее импортированных строк.
    # Шаг 1 — создать записи в справочниках для имён, которых там ещё нет
    (
        """INSERT INTO models (tenant_id, name, active)
           SELECT DISTINCT t.tenant_id, t.model, true
           FROM transactions t
           WHERE t.model IS NOT NULL AND t.model <> '' AND t.model_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM models m WHERE m.tenant_id = t.tenant_id AND m.name = t.model
             )""",
        False,
    ),
    (
        """INSERT INTO chatters (tenant_id, name, active)
           SELECT DISTINCT t.tenant_id, t.chatter, true
           FROM transactions t
           WHERE t.chatter IS NOT NULL AND t.chatter <> '' AND t.chatter_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM chatters c WHERE c.tenant_id = t.tenant_id AND c.name = t.chatter
             )""",
        False,
    ),
    (
        """INSERT INTO shifts_catalog (tenant_id, name, active)
           SELECT DISTINCT t.tenant_id, t.shift_name, true
           FROM transactions t
           WHERE t.shift_name IS NOT NULL AND t.shift_name <> ''
             AND t.shift_catalog_id IS NULL
             AND t.shift_name NOT SIMILAR TO
                 '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
             AND NOT EXISTS (
                 SELECT 1 FROM shifts_catalog sc
                 WHERE sc.tenant_id = t.tenant_id AND sc.name = t.shift_name
             )""",
        False,
    ),
    # Шаг 2 — проставить FK по совпадению имени
    (
        """UPDATE transactions t
           SET model_id = m.id
           FROM models m
           WHERE t.tenant_id = m.tenant_id
             AND t.model = m.name
             AND t.model_id IS NULL
             AND t.model IS NOT NULL AND t.model <> ''""",
        False,
    ),
    (
        """UPDATE transactions t
           SET chatter_id = c.id
           FROM chatters c
           WHERE t.tenant_id = c.tenant_id
             AND t.chatter = c.name
             AND t.chatter_id IS NULL
             AND t.chatter IS NOT NULL AND t.chatter <> ''""",
        False,
    ),
    (
        """UPDATE transactions t
           SET shift_catalog_id = sc.id
           FROM shifts_catalog sc
           WHERE t.tenant_id = sc.tenant_id
             AND t.shift_name = sc.name
             AND t.shift_catalog_id IS NULL
             AND t.shift_name IS NOT NULL AND t.shift_name <> ''""",
        False,
    ),
    # Проставить source для ранее импортированных строк (NULL → определяем по notion_id)
    (
        """UPDATE transactions
           SET source = CASE
               WHEN notion_id LIKE 'gsheet:%'   THEN 'google_sheets'
               WHEN notion_id LIKE 'file_ai:%'  THEN 'import'
               WHEN notion_id LIKE 'excel:%'    THEN 'import'
               ELSE 'import'
           END
           WHERE source IS NULL AND notion_id IS NOT NULL""",
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
