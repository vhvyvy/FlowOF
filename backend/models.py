from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Date, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from services.enum_types import (
    CASE_STAGE, CASE_PRIORITY, CASE_RESULT, CASE_TYPE,
    METRIC_TYPE, SNAPSHOT_TYPE, SNAPSHOT_TYPE_V2, SNAPSHOT_SOURCE,
    LEDGER_EVENT_TYPE, STAGE_CHANGED_BY, KPI_METRIC_TYPE, ACTIVITY_TYPE,
)

from database import Base


# ── MMR-система ───────────────────────────────────────────────────────────────

class MmrSettings(Base):
    """Настройки MMR для агентства (одна запись на tenant)."""
    __tablename__ = "mmr_settings"

    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    fin_overperform_threshold = Column(Numeric(5, 2), default=1.10)
    fin_underperform_threshold = Column(Numeric(5, 2), default=0.90)
    fin_overperform_points = Column(Integer, default=25)
    fin_perform_points = Column(Integer, default=15)
    fin_underperform_points = Column(Integer, default=-15)
    fin_empty_shift_points = Column(Integer, default=-15)
    kpi_threshold_high = Column(Numeric(5, 2), default=1.15)
    kpi_threshold_low = Column(Numeric(5, 2), default=0.85)
    kpi_high_points = Column(Integer, default=5)
    kpi_low_points = Column(Integer, default=-5)
    kpi_enabled = Column(Boolean, default=True)
    season_carry_over = Column(Numeric(4, 2), default=0.5)
    prize_1st = Column(Numeric(10, 2), default=200)
    prize_2nd = Column(Numeric(10, 2), default=150)
    prize_3rd = Column(Numeric(10, 2), default=100)
    calibration_days = Column(Integer, default=14)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MmrSeason(Base):
    """Сезон MMR-рейтинга (квартал)."""
    __tablename__ = "mmr_seasons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatterMmr(Base):
    """Текущее MMR-состояние чаттера в рамках сезона."""
    __tablename__ = "chatter_mmr"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    chatter_id = Column(Integer, ForeignKey("chatters.id", ondelete="CASCADE"), nullable=False)
    season_id = Column(Integer, ForeignKey("mmr_seasons.id", ondelete="CASCADE"), nullable=False)
    current_mmr = Column(Integer, default=0)
    peak_mmr = Column(Integer, default=0)
    current_league = Column(Text, nullable=True)
    calibration_complete = Column(Boolean, default=False)
    days_active = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "chatter_id", "season_id", name="uq_chatter_mmr"),
    )


class MmrEvent(Base):
    """Запись о начислении/снятии MMR-очков."""
    __tablename__ = "mmr_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id", ondelete="CASCADE"), nullable=False)
    season_id = Column(Integer, ForeignKey("mmr_seasons.id"), nullable=True)
    event_date = Column(Date, nullable=False)
    event_type = Column(Text, nullable=False)   # 'finance' | 'kpi'
    category = Column(Text, nullable=False)      # 'overperform' | 'perform' | etc.
    points = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    shift_id = Column(Integer, ForeignKey("shifts_catalog.id"), nullable=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SeasonResult(Base):
    """Итог чаттера по закрытому сезону."""
    __tablename__ = "season_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)
    season_id = Column(Integer, ForeignKey("mmr_seasons.id"), nullable=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id"), nullable=True)
    final_mmr = Column(Integer, nullable=True)
    final_league = Column(Text, nullable=True)
    rank = Column(Integer, nullable=True)
    prize_amount = Column(Numeric(10, 2), default=0)
    prize_paid = Column(Boolean, default=False)
    prize_paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatterAdjustment(Base):
    """Аванс или штраф для чаттера."""
    __tablename__ = "chatter_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id", ondelete="CASCADE"), nullable=False)
    type = Column(Text, nullable=False)       # 'advance' | 'penalty'
    amount = Column(Numeric(12, 2), nullable=False)
    description = Column(Text, nullable=True)
    date = Column(Date, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatterInvite(Base):
    """Одноразовая инвайт-ссылка для регистрации чаттера в личном кабинете."""
    __tablename__ = "chatter_invites"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id", ondelete="CASCADE"), nullable=False)
    token = Column(Text, unique=True, nullable=False, index=True)
    email = Column(Text, nullable=True)
    used = Column(Boolean, default=False, nullable=False)
    used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """Пользователь системы — owner агентства или chatter."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(Text, unique=True, nullable=False, index=True)
    hashed_password = Column(Text, nullable=False)
    role = Column(Text, nullable=False, default="owner")  # 'owner' | 'chatter'
    full_name = Column(Text, nullable=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id"), nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    admin_shift_id = Column(Integer, ForeignKey("shifts_catalog.id"), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    avatar_base64 = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    notion_token = Column(Text, nullable=True)
    onlymonster_key = Column(Text, nullable=True)
    onlymonster_account_ids = Column(Text, nullable=True)
    openai_key = Column(Text, nullable=True)
    plan = Column(String(50), default="basic")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Onboarding / import (Этап 1)
    onboarding_step = Column(Integer, default=0, nullable=False)
    onboarding_completed = Column(Boolean, default=False, nullable=False)
    source_type = Column(String(64), nullable=True)
    last_sync_at = Column(DateTime, nullable=True)
    currency = Column(String(8), default="USD", nullable=False)
    agency_name = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)


class TenantSource(Base):
    """Подключённые источники данных (Notion, Sheets, …)."""
    __tablename__ = "tenant_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(64), nullable=False)
    credentials = Column(JSONB, nullable=True)
    mapping_config = Column(JSONB, nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SyncLog(Base):
    """Журнал синхронизаций (все прогоны, включая ошибки)."""
    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(64), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    rows_imported = Column(Integer, default=0, nullable=False)
    rows_skipped = Column(Integer, default=0, nullable=False)
    status = Column(String(32), default="running", nullable=False)
    error_message = Column(Text, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    date = Column(Date, nullable=True)
    model = Column(String(255), nullable=True)
    chatter = Column(String(255), nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)
    month_source = Column(String(20), nullable=True)
    synced_at = Column(DateTime, nullable=True)
    shift_id = Column(String(100), nullable=True)
    shift_name = Column(String(255), nullable=True)
    notion_id = Column(String(255), nullable=True)
    # Which Notion database this row was synced from (for team routing)
    notion_database_id = Column(String(64), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("teams_mt.id"), nullable=True, index=True)
    # Ручной учёт: FK на справочники + признак источника
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True)
    chatter_id = Column(Integer, ForeignKey("chatters.id"), nullable=True)
    shift_catalog_id = Column(Integer, ForeignKey("shifts_catalog.id"), nullable=True)
    source = Column(String(50), nullable=True)  # 'manual' | 'import' | 'google_sheets'


class Team(Base):
    """Agency team (separate Notion DB / economics)."""
    __tablename__ = "teams_mt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0)
    # Notion database IDs for this team's transactions.
    # MAY contain multiple IDs separated by commas/newlines (one per month).
    notion_database_id = Column(Text, nullable=True)
    # Optional UI color key for team highlighting in shared dashboards/charts
    color_key = Column(String(32), nullable=True)
    # If True, use global app_settings for chatter tiers and admin % (applied to this team's revenue)
    inherit_economics = Column(Boolean, default=True)
    # When inherit_economics is False: cap chatter tier at this % (e.g. 22)
    chatter_max_pct = Column(Numeric(5, 2), nullable=True)
    # Default % for models without a plan (defaults to min(25, chatter_max))
    default_chatter_pct = Column(Numeric(5, 2), nullable=True)
    # Total admin pool as % of this team's revenue (e.g. 8 = two admins × 4%)
    admin_percent_total = Column(Numeric(5, 2), nullable=True)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    notion_id = Column(String(255), nullable=True)
    date = Column(Date, nullable=True)
    model = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    payment_method = Column(String(100), nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)
    # Ручной учёт / импорт: FK на справочники + источник + описание
    category_id = Column(Integer, ForeignKey("expense_categories.id"), nullable=True)
    model_id = Column(Integer, ForeignKey("models.id"), nullable=True)
    description = Column(Text, nullable=True)
    source = Column(String(50), nullable=True)  # 'manual' | 'import' | 'google_sheets'


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # No tenant_id in existing schema


class Plan(Base):
    __tablename__ = "plans"

    # Existing DB has no id column — composite PK
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    model = Column(String(255), nullable=False)
    plan_amount = Column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "year", "month", "model"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)


class AgentEvent(Base):
    """Agent memory layer — events with lifecycle tracking.

    Lifecycle: proposed → accepted → in_progress → review_due
               → closed_success / closed_failed / dismissed
    """
    __tablename__ = "agent_events"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id            = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    title                = Column(Text, nullable=False)
    description          = Column(Text, nullable=True)
    entity_type          = Column(String(64), nullable=True)   # 'chatter'/'model'/'shift'/'agency'
    entity_ref           = Column(String(255), nullable=True)  # chatter name / model name / etc.
    trigger_metric       = Column(String(64), nullable=True)   # 'rpc', 'revenue_mom', ...
    trigger_value_before = Column(Numeric(14, 4), nullable=True)
    status               = Column(String(32), nullable=False, default="proposed")
    source               = Column(String(32), nullable=False, default="chat")   # 'watcher'/'chat'/'user'
    created_by           = Column(String(32), nullable=False, default="agent")  # 'agent'/'owner'
    priority             = Column(String(16), nullable=False, default="normal") # 'high'/'normal'/'low'
    created_at           = Column(DateTime, nullable=False, default=datetime.utcnow)
    review_date          = Column(Date, nullable=True)
    closed_at            = Column(DateTime, nullable=True)
    outcome              = Column(Text, nullable=True)
    outcome_value_after  = Column(Numeric(14, 4), nullable=True)
    related_chat_id      = Column(String(128), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings_mt"

    # Actual PK in DB is composite (tenant_id, key) — no id column
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    key = Column(Text, nullable=False)
    value = Column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "key"),
    )


class ChatterKpi(Base):
    """Per-chatter Onlymonster metrics (multi-tenant)."""
    __tablename__ = "chatter_kpi_mt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    chatter = Column(String(255), nullable=False)  # onlymonster_id or display name
    ppv_open_rate = Column(Numeric(8, 2), nullable=True)
    apv = Column(Numeric(12, 2), nullable=True)
    total_chats = Column(Numeric(12, 0), nullable=True)
    model = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")

    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "month", "chatter", name="uq_chatter_kpi_mt"),
    )


class CatalogModel(Base):
    """Справочник: модели агентства."""
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CatalogChatter(Base):
    """Справочник: чаттеры."""
    __tablename__ = "chatters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ShiftCatalog(Base):
    """Справочник: смены (настраиваются пользователем)."""
    __tablename__ = "shifts_catalog"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ExpenseCategory(Base):
    """Справочник: категории расходов."""
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatterMapping(Base):
    __tablename__ = "chatter_onlymonster_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    onlymonster_id = Column(String(255), nullable=False)
    display_names = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "onlymonster_id", name="uq_chatter_mapping_tenant_id"),
    )


class ScriptFolder(Base):
    """Папка скриптов чаттера."""
    __tablename__ = "script_folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Script(Base):
    """Скрипт в библиотеке чаттера."""
    __tablename__ = "scripts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id = Column(Integer, ForeignKey("script_folders.id", ondelete="SET NULL"), nullable=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(Text, nullable=True)
    copy_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── KPI Admin Cabinet (шаг 1.1) ───────────────────────────────────────────────
# Enum columns are stored as String here so that SQLAlchemy create_all
# does not conflict with the PostgreSQL-native enum types created by
# schema_patch.  The PG enums are already enforced at the DB level.

class AdminCase(Base):
    """Кейс работы с чаттером (quantitative: один открытый per chatter×metric; qualitative: per category)."""
    __tablename__ = "admin_cases"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id      = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id       = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    om_user_id     = Column(String(64), nullable=False)
    case_type      = Column(CASE_TYPE, nullable=False, default="quantitative")
    category       = Column(String(100), nullable=True)
    metric_type    = Column(METRIC_TYPE, nullable=True)
    stage          = Column(CASE_STAGE, nullable=False, default="detected")
    priority       = Column(CASE_PRIORITY, nullable=False, default="normal")
    result         = Column(CASE_RESULT, nullable=True)
    opened_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    closed_at      = Column(DateTime, nullable=True)
    review_date    = Column(Date, nullable=True)
    baseline_value   = Column(Numeric(14, 4), nullable=True)
    target_value     = Column(Numeric(14, 4), nullable=True)
    result_value     = Column(Numeric(14, 4), nullable=True)
    baseline_version = Column(String(8), nullable=False, default="v1")
    is_early_month   = Column(Boolean, nullable=False, default=False)
    is_new_chatter   = Column(Boolean, nullable=False, default=False)
    notes            = Column(Text, nullable=True)
    created_at     = Column(DateTime, nullable=False, default=datetime.utcnow)

    activities = relationship(
        "CaseActivity",
        back_populates="case",
        cascade="all, delete-orphan",
    )


class CaseActivity(Base):
    """Запись активности админа по кейсу (review, training, note, …)."""
    __tablename__ = "case_activities"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id     = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id       = Column(Integer, ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id      = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    activity_type = Column(ACTIVITY_TYPE, nullable=False)
    text          = Column(Text, nullable=False)
    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    case  = relationship("AdminCase", back_populates="activities")
    admin = relationship("User", foreign_keys=[admin_id])
    files = relationship(
        "CaseActivityFile",
        back_populates="activity",
        cascade="all, delete-orphan",
    )


class CaseActivityFile(Base):
    """Вложение к активности (скриншот); file_path — относительный от FILE_STORAGE_ROOT."""
    __tablename__ = "case_activity_files"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    activity_id   = Column(Integer, ForeignKey("case_activities.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path     = Column(Text, nullable=False)
    original_name = Column(Text, nullable=True)
    mime_type     = Column(Text, nullable=True)
    size_bytes    = Column(Integer, nullable=True)
    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)

    activity = relationship("CaseActivity", back_populates="files")


class CaseStageHistory(Base):
    """Лог переходов стадий кейса."""
    __tablename__ = "case_stage_history"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    case_id    = Column(Integer, ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    from_stage = Column(CASE_STAGE, nullable=True)
    to_stage   = Column(CASE_STAGE, nullable=False)
    changed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    changed_by = Column(STAGE_CHANGED_BY, nullable=False)
    notes      = Column(Text, nullable=True)


class BaselineSnapshot(Base):
    """Снапшот значения метрики (baseline / target / result) для кейса."""
    __tablename__ = "baseline_snapshots"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    case_id             = Column(Integer, ForeignKey("admin_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    snapshot_type       = Column(SNAPSHOT_TYPE, nullable=False)
    snapshot_type_v2    = Column(SNAPSHOT_TYPE_V2, nullable=True)
    metric_type         = Column(METRIC_TYPE, nullable=False)
    metric_value        = Column(Numeric(14, 4), nullable=False)
    daily_value         = Column(Numeric(14, 4), nullable=True)
    week_avg_value      = Column(Numeric(14, 4), nullable=True)
    month_current_value = Column(Numeric(14, 4), nullable=True)
    prev_month_value    = Column(Numeric(14, 4), nullable=True)
    snapshot_date       = Column(Date, nullable=False)
    snapshot_as_of      = Column(Date, nullable=True)
    source              = Column(SNAPSHOT_SOURCE, nullable=False, default="system_from_daily")
    created_at          = Column(DateTime, nullable=False, default=datetime.utcnow)


class CaseLedger(Base):
    """Append-only журнал событий и очков по кейсам."""
    __tablename__ = "case_ledger"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id  = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    case_id    = Column(Integer, ForeignKey("admin_cases.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(LEDGER_EVENT_TYPE, nullable=False)
    points     = Column(Numeric(10, 2), nullable=False, default=0)
    notes      = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class KpiConfig(Base):
    """Настройки KPI-модуля для одной метрики одного тенанта."""
    __tablename__ = "kpi_config"

    id                        = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id                 = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    metric_type               = Column(KPI_METRIC_TYPE, nullable=False)
    noise_threshold_pct       = Column(Numeric(8, 2), nullable=False, default=5)
    guardrail_metrics         = Column(JSONB, nullable=False, default=list)
    hold_days                 = Column(Integer, nullable=False, default=21)
    detect_to_result_ratio_min = Column(Integer, nullable=False, default=15)
    calibration_days          = Column(Integer, nullable=False, default=30)


class AdminKpiSnapshot(Base):
    """Месячный срез KPI-показателей администратора."""
    __tablename__ = "admin_kpi_snapshot"

    # Composite PK — no auto-increment id (mirrors the DDL)
    tenant_id            = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    admin_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    period_year          = Column(Integer, nullable=False)
    period_month         = Column(Integer, nullable=False)
    cases_opened         = Column(Integer, nullable=False, default=0)
    cases_closed_success = Column(Integer, nullable=False, default=0)
    cases_closed_failed  = Column(Integer, nullable=False, default=0)
    cases_cancelled      = Column(Integer, nullable=False, default=0)
    guardrail_hits       = Column(Integer, nullable=False, default=0)
    total_points         = Column(Numeric(12, 2), nullable=False, default=0)
    detect_result_ratio  = Column(Numeric(6, 2), nullable=True)
    is_calibration       = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "admin_id", "period_year", "period_month"),
    )
