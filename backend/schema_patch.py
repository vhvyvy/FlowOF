"""
PostgreSQL: SQLAlchemy create_all does NOT add new columns to existing tables.
Apply lightweight ALTERs so production DBs stay compatible.
"""
from __future__ import annotations

import logging
import re

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
    # ── Авансы и штрафы чаттерам ─────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS chatter_adjustments (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
            chatter_id INTEGER REFERENCES chatters(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            amount NUMERIC NOT NULL,
            description TEXT,
            date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_by_user_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_adjustments_chatter_month ON chatter_adjustments(chatter_id, date)", False),
    # ── Исправить NULL в is_active / kpi_enabled для существующих строк ────────
    ("UPDATE mmr_seasons SET is_active = TRUE WHERE is_active IS NULL", False),
    ("UPDATE mmr_settings SET kpi_enabled = TRUE WHERE kpi_enabled IS NULL", False),
    # Укрепить DDL: NOT NULL DEFAULT TRUE на kpi_enabled
    ("ALTER TABLE mmr_settings ALTER COLUMN kpi_enabled SET NOT NULL", False),
    ("ALTER TABLE mmr_settings ALTER COLUMN kpi_enabled SET DEFAULT TRUE", False),
    # ── Миграция сезонов: закрыть «Весна 2026», открыть «Лето 2026» ────────────
    # Шаг 1: закрыть тестовый сезон «Весна 2026» (без записи season_results)
    (
        "UPDATE mmr_seasons SET is_active = FALSE, closed_at = NOW() "
        "WHERE name = 'Весна 2026' AND COALESCE(is_active, TRUE) = TRUE",
        False,
    ),
    # Шаг 2: создать сезон «Лето 2026» если его ещё нет
    (
        """INSERT INTO mmr_seasons (tenant_id, name, start_date, end_date, is_active)
           SELECT s.tenant_id, 'Лето 2026', '2026-06-01', '2026-08-31', TRUE
           FROM mmr_seasons s
           WHERE s.name = 'Весна 2026'
             AND NOT EXISTS (
                 SELECT 1 FROM mmr_seasons n
                 WHERE n.tenant_id = s.tenant_id AND n.name = 'Лето 2026'
             )
           LIMIT 1""",
        False,
    ),
    # Шаг 3: перенести mmr_events с event_date >= 2026-06-01 в «Лето 2026»
    (
        """UPDATE mmr_events e
           SET season_id = ns.id
           FROM mmr_seasons ns
           JOIN mmr_seasons os ON os.name = 'Весна 2026' AND os.tenant_id = ns.tenant_id
           WHERE ns.name = 'Лето 2026'
             AND e.season_id = os.id
             AND e.event_date >= '2026-06-01'""",
        False,
    ),
    # Шаг 4: скопировать записи chatter_mmr в новый сезон
    (
        """INSERT INTO chatter_mmr
               (tenant_id, chatter_id, season_id,
                current_mmr, peak_mmr, current_league, calibration_complete, days_active)
           SELECT cm.tenant_id, cm.chatter_id, ns.id,
                  cm.current_mmr, cm.peak_mmr, cm.current_league,
                  cm.calibration_complete, cm.days_active
           FROM chatter_mmr cm
           JOIN mmr_seasons os ON os.id = cm.season_id AND os.name = 'Весна 2026'
           JOIN mmr_seasons ns ON ns.name = 'Лето 2026' AND ns.tenant_id = os.tenant_id
           ON CONFLICT (tenant_id, chatter_id, season_id) DO UPDATE
           SET current_mmr          = EXCLUDED.current_mmr,
               peak_mmr             = EXCLUDED.peak_mmr,
               current_league       = EXCLUDED.current_league,
               calibration_complete = EXCLUDED.calibration_complete,
               days_active          = EXCLUDED.days_active""",
        False,
    ),
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
    # ── Аватарки пользователей ────────────────────────────────────────────────
    ("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_base64 TEXT", False),
    # ── Библиотека скриптов чаттеров ──────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS script_folders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_folders_user ON script_folders(user_id)", False),
    (
        """CREATE TABLE IF NOT EXISTS scripts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            folder_id INTEGER REFERENCES script_folders(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            copy_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS idx_scripts_user_folder ON scripts(user_id, folder_id)", False),
    # ── Agent events (memory layer, Этап 2) ───────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS agent_events (
            id                   SERIAL PRIMARY KEY,
            tenant_id            INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            title                TEXT NOT NULL,
            description          TEXT,
            entity_type          VARCHAR(64),
            entity_ref           VARCHAR(255),
            trigger_metric       VARCHAR(64),
            trigger_value_before NUMERIC(14, 4),
            status               VARCHAR(32) NOT NULL DEFAULT 'proposed',
            source               VARCHAR(32) NOT NULL DEFAULT 'chat',
            created_by           VARCHAR(32) NOT NULL DEFAULT 'agent',
            priority             VARCHAR(16) NOT NULL DEFAULT 'normal',
            created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
            review_date          DATE,
            closed_at            TIMESTAMP,
            outcome              TEXT,
            outcome_value_after  NUMERIC(14, 4),
            related_chat_id      VARCHAR(128)
        )""",
        False,
    ),
    ("CREATE INDEX IF NOT EXISTS ix_agent_events_tenant_status ON agent_events (tenant_id, status)", False),
    ("CREATE INDEX IF NOT EXISTS ix_agent_events_tenant_review ON agent_events (tenant_id, review_date)", False),
    ("CREATE INDEX IF NOT EXISTS ix_agent_events_tenant_entity ON agent_events (tenant_id, entity_type, entity_ref)", False),
    # ── Agency profile / semantic context (Этап 4) ────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS agency_profile (
            tenant_id              INTEGER PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            rpc_critical           NUMERIC(10, 4) NOT NULL DEFAULT 0.15,
            rpc_working_low        NUMERIC(10, 4) NOT NULL DEFAULT 0.25,
            rpc_strong             NUMERIC(10, 4) NOT NULL DEFAULT 0.50,
            open_rate_critical     NUMERIC(10, 2) NOT NULL DEFAULT 20.0,
            open_rate_working      NUMERIC(10, 2) NOT NULL DEFAULT 25.0,
            open_rate_strong       NUMERIC(10, 2) NOT NULL DEFAULT 35.0,
            priorities             TEXT,
            glossary               TEXT,
            target_notes           TEXT,
            updated_at             TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    # ── Daily Onlymonster KPI snapshots ─────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS chatter_kpi_daily (
            id            SERIAL PRIMARY KEY,
            tenant_id     INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            chatter       VARCHAR(255) NOT NULL,
            om_user_id    VARCHAR(64),
            date          DATE NOT NULL,
            ppv_open_rate NUMERIC(10, 2),
            apv           NUMERIC(10, 4),
            total_chats   INTEGER,
            source        VARCHAR(20) NOT NULL DEFAULT 'api',
            created_at    TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_chatter_kpi_daily_tcdate
           ON chatter_kpi_daily (tenant_id, chatter, date)""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_chatter_kpi_daily_tenant_date
           ON chatter_kpi_daily (tenant_id, date)""",
        False,
    ),
    # ── AI chat session history ──────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS ai_chat_messages (
            id         SERIAL PRIMARY KEY,
            tenant_id  INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            session_id VARCHAR(64) NOT NULL,
            role       VARCHAR(20) NOT NULL CHECK (role IN ('user','assistant')),
            content    TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session
           ON ai_chat_messages (tenant_id, session_id, created_at)""",
        False,
    ),

    # ═══════════════════════════════════════════════════════════════════════════
    # KPI Admin Cabinet — шаг 1.1: схема БД
    # NOTE: PostgreSQL enum types are created separately in _ENUM_PATCHES below
    # (DO blocks with EXCEPTION handlers corrupt asyncpg transaction state).
    # ═══════════════════════════════════════════════════════════════════════════

    # ── users: admin_shift_id (nullable FK → shifts_catalog) ─────────────────
    (
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS admin_shift_id INTEGER REFERENCES shifts_catalog(id)",
        False,
    ),

    # ── admin_cases (3.1) ─────────────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS admin_cases (
            id              SERIAL PRIMARY KEY,
            tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            admin_id        INTEGER NOT NULL REFERENCES users(id),
            om_user_id      VARCHAR(64) NOT NULL,
            metric_type     metric_type NOT NULL,
            stage           case_stage  NOT NULL DEFAULT 'detected',
            priority        case_priority NOT NULL DEFAULT 'normal',
            result          case_result,
            opened_at       TIMESTAMP NOT NULL DEFAULT NOW(),
            closed_at       TIMESTAMP,
            review_date     DATE,
            baseline_value  NUMERIC(14, 4),
            target_value    NUMERIC(14, 4),
            result_value    NUMERIC(14, 4),
            notes           TEXT,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    # Partial unique index: only one open case per (chatter, metric) per tenant
    (
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_cases_open_chatter_metric
           ON admin_cases (tenant_id, om_user_id, metric_type)
           WHERE stage IN ('detected','in_progress','hold','review_due')""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_admin_cases_admin_stage
           ON admin_cases (tenant_id, admin_id, stage)""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_admin_cases_chatter_metric
           ON admin_cases (tenant_id, om_user_id, metric_type)""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_admin_cases_review_date
           ON admin_cases (tenant_id, review_date)""",
        False,
    ),

    # ── case_stage_history (3.3) ──────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS case_stage_history (
            id          SERIAL PRIMARY KEY,
            case_id     INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
            from_stage  case_stage,
            to_stage    case_stage NOT NULL,
            changed_at  TIMESTAMP NOT NULL DEFAULT NOW(),
            changed_by  stage_changed_by NOT NULL,
            notes       TEXT
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_case_stage_history_case
           ON case_stage_history (case_id, changed_at)""",
        False,
    ),

    # ── baseline_snapshots (3.4) ──────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS baseline_snapshots (
            id              SERIAL PRIMARY KEY,
            case_id         INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
            snapshot_type   snapshot_type   NOT NULL,
            metric_type     metric_type     NOT NULL,
            metric_value    NUMERIC(14, 4)  NOT NULL,
            snapshot_date   DATE            NOT NULL,
            source          snapshot_source NOT NULL DEFAULT 'system_from_daily',
            created_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_baseline_snapshots_case
           ON baseline_snapshots (case_id, snapshot_type)""",
        False,
    ),

    # ── case_ledger (3.5) append-only ─────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS case_ledger (
            id          SERIAL PRIMARY KEY,
            tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            admin_id    INTEGER NOT NULL REFERENCES users(id),
            case_id     INTEGER REFERENCES admin_cases(id) ON DELETE SET NULL,
            event_type  ledger_event_type NOT NULL,
            points      NUMERIC(10, 2)    NOT NULL DEFAULT 0,
            notes       TEXT,
            created_at  TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_case_ledger_admin
           ON case_ledger (tenant_id, admin_id, created_at)""",
        False,
    ),

    # ── case_activities (admin portal UX) ─────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS case_activities (
            id             SERIAL PRIMARY KEY,
            tenant_id      INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            case_id        INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
            admin_id       INTEGER NOT NULL REFERENCES users(id),
            activity_type  activity_type_enum NOT NULL,
            text           TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 5000),
            created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_case_activities_case_created
           ON case_activities (tenant_id, case_id, created_at DESC)""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_case_activities_admin
           ON case_activities (tenant_id, admin_id, created_at DESC)""",
        False,
    ),
    (
        """CREATE TABLE IF NOT EXISTS case_activity_files (
            id             SERIAL PRIMARY KEY,
            activity_id    INTEGER NOT NULL REFERENCES case_activities(id) ON DELETE CASCADE,
            file_path      TEXT NOT NULL,
            original_name  TEXT,
            mime_type      TEXT,
            size_bytes     INTEGER,
            created_at     TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_case_activity_files_activity
           ON case_activity_files (activity_id)""",
        False,
    ),

    # ── kpi_config (3.6) ──────────────────────────────────────────────────────
    (
        """CREATE TABLE IF NOT EXISTS kpi_config (
            id                          SERIAL PRIMARY KEY,
            tenant_id                   INTEGER     NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            metric_type                 metric_type NOT NULL,
            noise_threshold_pct         NUMERIC(8, 2) NOT NULL DEFAULT 5,
            guardrail_metrics           JSONB        NOT NULL DEFAULT '[]',
            hold_days                   INTEGER      NOT NULL DEFAULT 21,
            detect_to_result_ratio_min  INTEGER      NOT NULL DEFAULT 15,
            calibration_days            INTEGER      NOT NULL DEFAULT 30,
            UNIQUE (tenant_id, metric_type)
        )""",
        False,
    ),

    # ── admin_kpi_snapshot (3.7) monthly rollup per admin ────────────────────
    (
        """CREATE TABLE IF NOT EXISTS admin_kpi_snapshot (
            tenant_id              INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            admin_id               INTEGER NOT NULL REFERENCES users(id),
            period_year            INTEGER NOT NULL,
            period_month           INTEGER NOT NULL,
            cases_opened           INTEGER NOT NULL DEFAULT 0,
            cases_closed_success   INTEGER NOT NULL DEFAULT 0,
            cases_closed_failed    INTEGER NOT NULL DEFAULT 0,
            cases_cancelled        INTEGER NOT NULL DEFAULT 0,
            guardrail_hits         INTEGER NOT NULL DEFAULT 0,
            total_points           NUMERIC(12, 2) NOT NULL DEFAULT 0,
            detect_result_ratio    NUMERIC(6, 2),
            is_calibration         BOOLEAN NOT NULL DEFAULT FALSE,
            UNIQUE (tenant_id, admin_id, period_year, period_month)
        )""",
        False,
    ),
    (
        """CREATE INDEX IF NOT EXISTS idx_admin_kpi_snapshot_admin
           ON admin_kpi_snapshot (tenant_id, admin_id)""",
        False,
    ),

    # ── admin_invites — инвайт-ссылки для регистрации администраторов ─────────
    (
        """CREATE TABLE IF NOT EXISTS admin_invites (
            id                SERIAL PRIMARY KEY,
            tenant_id         INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            token             VARCHAR(64) NOT NULL,
            admin_shift_id    INTEGER NOT NULL REFERENCES shifts_catalog(id),
            invited_email     VARCHAR(255),
            used_by_user_id   INTEGER REFERENCES users(id),
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            used_at           TIMESTAMP,
            expires_at        TIMESTAMP
        )""",
        False,
    ),
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_invites_token ON admin_invites (token)",
        False,
    ),
    (
        "CREATE INDEX IF NOT EXISTS idx_admin_invites_tenant ON admin_invites (tenant_id)",
        False,
    ),
]

# Catalog tables that should have UNIQUE(tenant_id, name).
# Each entry: (table_name, constraint_name)
_CATALOG_UNIQUE_CONSTRAINTS: list[tuple[str, str]] = [
    ("chatters",       "uq_chatters_tenant_name"),
    ("models",         "uq_models_tenant_name"),
    ("shifts_catalog", "uq_shifts_catalog_tenant_name"),
]

# ── KPI Admin Cabinet: PostgreSQL ENUM types ─────────────────────────────────
# DO blocks with EXCEPTION handlers cause asyncpg to misread the internal
# PostgreSQL subtransaction rollback as a failed outer transaction, which
# corrupts the connection state for all subsequent patches.
# Solution: check pg_type first in Python, CREATE only when missing.
# Each enum is applied in its own separate transaction for full isolation.
_ENUM_PATCHES: list[tuple[str, list[str]]] = [
    ("case_stage",        ["detected", "in_progress", "hold", "review_due", "closed", "cancelled"]),
    ("case_priority",     ["high", "normal", "low"]),
    ("case_result",       ["success", "failed", "cancelled"]),
    ("metric_type",       ["ppv_open_rate", "rpc", "apv", "total_chats", "revenue"]),
    ("snapshot_type",     ["baseline", "target", "result"]),
    ("snapshot_source",   ["system_from_daily", "system_from_monthly", "manual"]),
    ("ledger_event_type", [
        "case_opened", "case_closed_success", "case_closed_failed",
        "case_cancelled", "guardrail_triggered", "baseline_frozen",
    ]),
    ("stage_changed_by",  ["admin", "owner", "system"]),
    ("activity_type_enum", ["review", "training", "meeting", "observation", "note", "other"]),
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
    # ── Phase 0: enum types (must exist before tables that reference them) ───
    for enum_name, enum_values in _ENUM_PATCHES:
        try:
            async with engine.begin() as conn:
                exists = (await conn.execute(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM pg_type"
                        "  WHERE typname = :name AND typtype = 'e'"
                        ")"
                    ),
                    {"name": enum_name},
                )).scalar()
                if not exists:
                    vals_sql = ", ".join(f"'{v}'" for v in enum_values)
                    await conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({vals_sql})"))
                    logger.info("patch applied: enum %s", enum_name)
                else:
                    logger.debug("patch skip (exists): enum %s", enum_name)
        except Exception as e:
            logger.warning("schema_patch enum %s skipped: %s", enum_name, e)

    # ── Phase 1: regular DDL patches ─────────────────────────────────────────
    for sql, critical in _PATCHES:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            # Log table / index creations at INFO so they appear in Railway logs
            first_word = sql.strip().split()[0].upper()
            if first_word in ("CREATE", "ALTER"):
                logger.info("patch applied: %s", sql.strip()[:100])
        except Exception as e:
            if critical:
                logger.exception("schema_patch critical: %s — %s", sql[:120], e)
                raise
            logger.warning("schema_patch optional skip: %s — %s", sql[:120], e)

    # ── UNIQUE(tenant_id, name) on catalog tables ──────────────────────────
    # Check for duplicates first; skip the constraint if any remain so we
    # never crash startup.  Once duplicates are cleaned the constraint applies
    # on the next deploy automatically.
    for tbl, cname in _CATALOG_UNIQUE_CONSTRAINTS:
        try:
            async with engine.begin() as conn:
                # Check whether constraint already exists
                exists = (await conn.execute(
                    text(
                        "SELECT EXISTS ("
                        "  SELECT 1 FROM pg_constraint"
                        "  WHERE conname = :cname"
                        ")"
                    ),
                    {"cname": cname},
                )).scalar()
                if exists:
                    continue  # already applied on a previous deploy

                # Check for duplicate (tenant_id, name) pairs
                dup_q = await conn.execute(
                    text(
                        f"SELECT tenant_id, name, COUNT(*) AS cnt"
                        f" FROM {tbl}"
                        f" GROUP BY tenant_id, name"
                        f" HAVING COUNT(*) > 1"
                        f" LIMIT 5"
                    )
                )
                dups = dup_q.fetchall()
                if dups:
                    examples = "; ".join(
                        f"tenant={r[0]} name={r[1]!r} count={r[2]}" for r in dups
                    )
                    logger.warning(
                        "schema_patch: skipping UNIQUE(%s, tenant_id, name) — "
                        "duplicates still present: %s",
                        tbl, examples,
                    )
                    continue

                await conn.execute(
                    text(
                        f"ALTER TABLE {tbl}"
                        f" ADD CONSTRAINT {cname} UNIQUE (tenant_id, name)"
                    )
                )
                logger.info("schema_patch: added UNIQUE constraint %s on %s", cname, tbl)
        except Exception as e:
            logger.warning(
                "schema_patch optional skip: UNIQUE constraint %s on %s — %s",
                cname, tbl, e,
            )


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _norm_name(raw: str | None) -> str | None:
    """Normalize a catalog name: strip whitespace + leading @."""
    if not raw:
        return None
    s = str(raw).strip().lstrip("@").strip()
    return s or None


async def backfill_transaction_ids(session_factory) -> None:  # type: ignore[type-arg]
    """One-time idempotent migration: fill chatter_id / model_id / shift_catalog_id
    for legacy transactions that were saved with text fields only (no FK IDs).

    Matching is case-insensitive + strips leading '@'.  Catalog entries are
    created on-the-fly if not found — same logic as catalog_resolver.
    This function is safe to call on every startup: it only touches rows
    where the ID column is still NULL.
    """
    async with session_factory() as db:
        # Fetch all active tenants
        tenant_rows = await db.execute(text("SELECT id FROM tenants"))
        tenant_ids = [r[0] for r in tenant_rows]

    total_updated = 0
    for tid in tenant_ids:
        async with session_factory() as db:
            try:
                n = await _backfill_tenant(db, tid)
                total_updated += n
                if n:
                    logger.info("backfill_transaction_ids: tenant=%d updated=%d rows", tid, n)
            except Exception as exc:
                logger.exception("backfill_transaction_ids: tenant=%d error: %s", tid, exc)

    if total_updated:
        logger.info("backfill_transaction_ids: DONE total updated=%d", total_updated)
    else:
        logger.info("backfill_transaction_ids: nothing to backfill — all IDs already set")


async def _backfill_tenant(db, tenant_id: int) -> int:
    """Fill missing FK IDs for one tenant. Returns the number of rows updated."""
    updated = 0

    # ── 1. Build catalog look-ups (normalized_lower → id) ────────────────────

    cat_chatters_r = await db.execute(
        text("SELECT id, name FROM chatters WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    chatter_map: dict[str, int] = {}
    for row in cat_chatters_r.mappings():
        n = _norm_name(row["name"])
        if n:
            chatter_map[n.lower()] = int(row["id"])

    cat_models_r = await db.execute(
        text("SELECT id, name FROM models WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    model_map: dict[str, int] = {}
    for row in cat_models_r.mappings():
        n = _norm_name(row["name"])
        if n:
            model_map[n.lower()] = int(row["id"])

    cat_shifts_r = await db.execute(
        text("SELECT id, name FROM shifts_catalog WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    )
    shift_map: dict[str, int] = {}
    for row in cat_shifts_r.mappings():
        n = _norm_name(row["name"])
        if n:
            shift_map[n.lower()] = int(row["id"])

    # ── 2. Fetch legacy transactions missing at least one ID ─────────────────

    txns_r = await db.execute(
        text(
            """SELECT id, chatter, model, shift_name
               FROM transactions
               WHERE tenant_id = :tid
                 AND (
                       (chatter_id IS NULL      AND chatter    IS NOT NULL AND TRIM(chatter)    != '')
                    OR (model_id IS NULL         AND model      IS NOT NULL AND TRIM(model)      != '')
                    OR (shift_catalog_id IS NULL AND shift_name IS NOT NULL AND TRIM(shift_name) != '')
                 )"""
        ),
        {"tid": tenant_id},
    )
    txn_rows = list(txns_r.mappings())
    if not txn_rows:
        return 0

    # ── Helper: find-or-create in a catalog table ────────────────────────────

    async def _get_or_create_chatter(raw: str | None) -> int | None:
        n = _norm_name(raw)
        if not n:
            return None
        key = n.lower()
        if key in chatter_map:
            return chatter_map[key]
        r = await db.execute(
            text("INSERT INTO chatters (tenant_id, name, active) VALUES (:tid, :name, TRUE) RETURNING id"),
            {"tid": tenant_id, "name": n},
        )
        new_id = r.scalar()
        chatter_map[key] = new_id  # type: ignore[assignment]
        return new_id

    async def _get_or_create_model(raw: str | None) -> int | None:
        n = _norm_name(raw)
        if not n:
            return None
        key = n.lower()
        if key in model_map:
            return model_map[key]
        r = await db.execute(
            text("INSERT INTO models (tenant_id, name, active) VALUES (:tid, :name, TRUE) RETURNING id"),
            {"tid": tenant_id, "name": n},
        )
        new_id = r.scalar()
        model_map[key] = new_id  # type: ignore[assignment]
        return new_id

    async def _get_or_create_shift(raw: str | None) -> int | None:
        n = _norm_name(raw)
        if not n:
            return None
        if _UUID_RE.match(n):
            return None  # skip Notion UUIDs
        key = n.lower()
        if key in shift_map:
            return shift_map[key]
        r = await db.execute(
            text("INSERT INTO shifts_catalog (tenant_id, name, active) VALUES (:tid, :name, TRUE) RETURNING id"),
            {"tid": tenant_id, "name": n},
        )
        new_id = r.scalar()
        shift_map[key] = new_id  # type: ignore[assignment]
        return new_id

    # ── 3. Process each legacy transaction ────────────────────────────────────

    for row in txn_rows:
        txid = row["id"]
        cid = await _get_or_create_chatter(row.get("chatter"))
        mid = await _get_or_create_model(row.get("model"))
        sid = await _get_or_create_shift(row.get("shift_name"))

        await db.execute(
            text(
                """UPDATE transactions
                   SET chatter_id      = COALESCE(chatter_id,      :cid),
                       model_id        = COALESCE(model_id,        :mid),
                       shift_catalog_id = COALESCE(shift_catalog_id, :sid)
                   WHERE id = :txid"""
            ),
            {"cid": cid, "mid": mid, "sid": sid, "txid": txid},
        )
        updated += 1

    await db.commit()
    return updated


# ── KPI Config seed ────────────────────────────────────────────────────────────

async def seed_default_kpi_config(db, tenant_id: int) -> int:
    """Insert default kpi_config rows for all 5 standard metrics if not already present.

    Must be called explicitly from the service layer on first access — NOT auto-called
    at startup. Uses ON CONFLICT DO NOTHING so it is safe to call multiple times.

    Returns:
        Number of rows actually inserted (0 if all already existed).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from models import KpiConfig

    _DEFAULTS = [
        {
            "metric_type":               "ppv_open_rate",
            "noise_threshold_pct":       5,
            "guardrail_metrics":         ["revenue", "rpc"],
            "hold_days":                 21,
            "detect_to_result_ratio_min": 15,
            "calibration_days":          30,
        },
        {
            "metric_type":               "rpc",
            "noise_threshold_pct":       10,
            "guardrail_metrics":         ["revenue"],
            "hold_days":                 21,
            "detect_to_result_ratio_min": 15,
            "calibration_days":          30,
        },
        {
            "metric_type":               "apv",
            "noise_threshold_pct":       10,
            "guardrail_metrics":         [],
            "hold_days":                 21,
            "detect_to_result_ratio_min": 15,
            "calibration_days":          30,
        },
        {
            "metric_type":               "total_chats",
            "noise_threshold_pct":       5,
            "guardrail_metrics":         ["rpc", "apv"],
            "hold_days":                 21,
            "detect_to_result_ratio_min": 15,
            "calibration_days":          30,
        },
        {
            "metric_type":               "revenue",
            "noise_threshold_pct":       10,
            "guardrail_metrics":         [],
            "hold_days":                 21,
            "detect_to_result_ratio_min": 15,
            "calibration_days":          30,
        },
    ]

    # Single bulk INSERT … ON CONFLICT DO NOTHING for all 5 metrics.
    # KpiConfig.metric_type is typed as PG_ENUM(name='metric_type', create_type=False),
    # so SQLAlchemy automatically emits the correct cast — no ::metric_type literal needed.
    # guardrail_metrics is JSONB — asyncpg serialises Python list automatically.
    stmt = (
        pg_insert(KpiConfig)
        .values([{"tenant_id": tenant_id, **d} for d in _DEFAULTS])
        .on_conflict_do_nothing(index_elements=["tenant_id", "metric_type"])
    )
    result = await db.execute(stmt)
    created = result.rowcount if result.rowcount and result.rowcount > 0 else 0

    await db.commit()
    logger.info("seed_default_kpi_config: tenant=%s inserted=%s rows", tenant_id, created)
    return created
