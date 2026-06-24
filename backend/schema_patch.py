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
    # Бэкфилл expenses: заполнить category_id и model_id для ранее импортированных расходов
    (
        """INSERT INTO expense_categories (tenant_id, name, active)
           SELECT DISTINCT e.tenant_id, e.category, true
           FROM expenses e
           WHERE e.category IS NOT NULL AND e.category <> '' AND e.category_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM expense_categories ec
                 WHERE ec.tenant_id = e.tenant_id AND ec.name = e.category
             )""",
        False,
    ),
    (
        """UPDATE expenses e
           SET category_id = ec.id
           FROM expense_categories ec
           WHERE e.tenant_id = ec.tenant_id
             AND e.category = ec.name
             AND e.category_id IS NULL
             AND e.category IS NOT NULL AND e.category <> ''""",
        False,
    ),
    (
        """INSERT INTO models (tenant_id, name, active)
           SELECT DISTINCT e.tenant_id, e.model, true
           FROM expenses e
           WHERE e.model IS NOT NULL AND e.model <> '' AND e.model_id IS NULL
             AND NOT EXISTS (
                 SELECT 1 FROM models m WHERE m.tenant_id = e.tenant_id AND m.name = e.model
             )""",
        False,
    ),
    (
        """UPDATE expenses e
           SET model_id = m.id
           FROM models m
           WHERE e.tenant_id = m.tenant_id
             AND e.model = m.name
             AND e.model_id IS NULL
             AND e.model IS NOT NULL AND e.model <> ''""",
        False,
    ),
    # Проставить source для расходов
    (
        """UPDATE expenses
           SET source = 'import'
           WHERE source IS NULL AND notion_id IS NOT NULL""",
        False,
    ),
    # ── Этап 1 личного кабинета: таблица users ────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'owner',
            full_name TEXT,
            chatter_id INTEGER REFERENCES chatters(id),
            is_admin BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            last_login_at TIMESTAMP
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)", False),
    ("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)", False),
    # Миграция: для каждого tenant создать user role='owner' (если ещё нет)
    (
        """INSERT INTO users (tenant_id, email, hashed_password, role, full_name, is_admin, active)
           SELECT t.id,
                  t.email,
                  COALESCE(t.password_hash, ''),
                  'owner',
                  COALESCE(t.agency_name, t.name, ''),
                  COALESCE(t.is_admin, FALSE),
                  TRUE
           FROM tenants t
           WHERE NOT EXISTS (
               SELECT 1 FROM users u
               WHERE u.tenant_id = t.id AND u.role = 'owner'
           )
             AND t.email IS NOT NULL""",
        False,
    ),
    # ── Этап 2 личного кабинета: инвайты (создаём ПОСЛЕ users) ───────────────
    (
        """CREATE TABLE IF NOT EXISTS chatter_invites (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            token TEXT UNIQUE NOT NULL,
            email TEXT,
            used BOOLEAN NOT NULL DEFAULT FALSE,
            used_at TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            created_by_user_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_invites_token ON chatter_invites(token)", False),
    # ── MMR-система рейтинга чаттеров ─────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS mmr_settings (
            tenant_id INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            fin_overperform_threshold NUMERIC DEFAULT 1.10,
            fin_underperform_threshold NUMERIC DEFAULT 0.90,
            fin_overperform_points INTEGER DEFAULT 25,
            fin_perform_points INTEGER DEFAULT 15,
            fin_underperform_points INTEGER DEFAULT -15,
            fin_empty_shift_points INTEGER DEFAULT -15,
            kpi_threshold_high NUMERIC DEFAULT 1.15,
            kpi_threshold_low NUMERIC DEFAULT 0.85,
            kpi_high_points INTEGER DEFAULT 5,
            kpi_low_points INTEGER DEFAULT -5,
            kpi_enabled BOOLEAN DEFAULT TRUE,
            season_carry_over NUMERIC DEFAULT 0.5,
            prize_1st NUMERIC DEFAULT 200,
            prize_2nd NUMERIC DEFAULT 150,
            prize_3rd NUMERIC DEFAULT 100,
            calibration_days INTEGER DEFAULT 14,
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE TABLE IF NOT EXISTS mmr_seasons (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            closed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_seasons_tenant_active ON mmr_seasons(tenant_id, is_active)", False),
    (
        """CREATE TABLE IF NOT EXISTS chatter_mmr (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            season_id INTEGER REFERENCES mmr_seasons(id) ON DELETE CASCADE,
            current_mmr INTEGER DEFAULT 0,
            peak_mmr INTEGER DEFAULT 0,
            current_league TEXT,
            calibration_complete BOOLEAN DEFAULT FALSE,
            days_active INTEGER DEFAULT 0,
            UNIQUE(tenant_id, chatter_id, season_id)
        )""",
        False,
    ),
    (
        """CREATE TABLE IF NOT EXISTS mmr_events (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            season_id INTEGER REFERENCES mmr_seasons(id),
            event_date DATE NOT NULL,
            event_type TEXT NOT NULL,
            category TEXT NOT NULL,
            points INTEGER NOT NULL,
            description TEXT,
            shift_id INTEGER REFERENCES shifts_catalog(id),
            model_id INTEGER REFERENCES models(id),
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_mmr_events_chatter ON mmr_events(chatter_id, event_date)", False),
    ("CREATE INDEX IF NOT EXISTS idx_mmr_events_season ON mmr_events(season_id, points)", False),
    (
        """CREATE TABLE IF NOT EXISTS season_results (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id),
            season_id INTEGER REFERENCES mmr_seasons(id),
            chatter_id INTEGER REFERENCES chatters(id),
            final_mmr INTEGER,
            final_league TEXT,
            rank INTEGER,
            prize_amount NUMERIC DEFAULT 0,
            prize_paid BOOLEAN DEFAULT FALSE,
            prize_paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    # ── История KPI чаттеров (для MMR Этап 4) ────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS chatter_kpi_history (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            ppv_open_rate NUMERIC,
            rpc NUMERIC,
            conversion NUMERIC,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(tenant_id, chatter_id, date)
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_kpi_history_chatter ON chatter_kpi_history(chatter_id, date)", False),
    # ── Исправить NULL в is_active для существующих сезонов ──────────────────
    ("UPDATE mmr_seasons SET is_active = TRUE WHERE is_active IS NULL", False),
    # ── Повторная попытка создать MMR-таблицы (идемпотентно, IF NOT EXISTS) ───
    # chatter_mmr и season_results могли не создаться если предыдущие запуски
    # прерывались из-за InFailedSqlTransaction. Повтор в отдельной транзакции.
    (
        """CREATE TABLE IF NOT EXISTS chatter_mmr (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            season_id INTEGER REFERENCES mmr_seasons(id) ON DELETE CASCADE,
            current_mmr INTEGER NOT NULL DEFAULT 0,
            peak_mmr INTEGER NOT NULL DEFAULT 0,
            current_league TEXT,
            calibration_complete BOOLEAN NOT NULL DEFAULT FALSE,
            days_active INTEGER NOT NULL DEFAULT 0,
            UNIQUE (tenant_id, chatter_id, season_id)
        )""",
        False,
    ),
    (
        """CREATE TABLE IF NOT EXISTS season_results (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            season_id INTEGER REFERENCES mmr_seasons(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            final_mmr INTEGER,
            final_league TEXT,
            rank INTEGER,
            prize_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            prize_paid BOOLEAN NOT NULL DEFAULT FALSE,
            prize_paid_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
]


async def apply_schema_patches(engine: AsyncEngine) -> None:
    """
    Idempotent column / index additions.

    Each patch runs in its OWN transaction so that a single failure does not
    put the connection into InFailedSqlTransaction state and block all
    subsequent patches.  (PostgreSQL aborts every statement in a transaction
    after the first error, causing perfectly valid CREATE TABLE statements to
    be silently skipped when they share a transaction with a failed ALTER.)
    """
    for sql, critical in _PATCHES:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception as e:
            if critical:
                logger.exception("schema_patch critical: %s — %s", sql[:120], e)
                raise
            logger.warning("schema_patch optional skip: %s — %s", sql[:120], e)
