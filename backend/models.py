from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Date, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from database import Base


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


class Team(Base):
    """Agency team (separate Notion DB / economics)."""
    __tablename__ = "teams_mt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0)
    # Notion database ID for this team's transactions (no hyphens or with — normalized in API)
    notion_database_id = Column(String(64), nullable=True)
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


class ChatterMapping(Base):
    __tablename__ = "chatter_onlymonster_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    onlymonster_id = Column(String(255), nullable=False)
    display_names = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "onlymonster_id", name="uq_chatter_mapping_tenant_id"),
    )
