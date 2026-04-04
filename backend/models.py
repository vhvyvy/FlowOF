from datetime import datetime, date as date_type
from sqlalchemy import (
    Boolean, Column, DateTime, Date, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=True)
    email = Column(String(255), unique=True, nullable=False)
    # Stores bcrypt hash (new) or SHA-256 hex (legacy) — auth.py handles both
    password_hash = Column(String(255), nullable=True)
    notion_token = Column(Text, nullable=True)
    onlymonster_key = Column(Text, nullable=True)
    onlymonster_account_ids = Column(Text, nullable=True)
    openai_key = Column(Text, nullable=True)
    plan = Column(String(50), default="basic")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    notion_id = Column(String(255), nullable=True, unique=False)
    date = Column(Date, nullable=True)
    model = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    vendor = Column(String(255), nullable=True)
    payment_method = Column(String(100), nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    model = Column(String(255), nullable=False)
    plan_amount = Column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "year", "month", "model", name="uq_plans_tenant_period_model"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings_mt"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_settings_tenant_key"),
    )


class ChatterMapping(Base):
    __tablename__ = "chatter_onlymonster_mapping"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    onlymonster_id = Column(String(255), nullable=False)
    display_names = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "onlymonster_id", name="uq_chatter_mapping_tenant_id"),
    )
