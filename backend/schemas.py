from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Tenant ────────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str
    email: str
    password: str
    plan: str = "basic"
    notion_token: Optional[str] = None
    onlymonster_key: Optional[str] = None
    onlymonster_account_ids: Optional[str] = None
    openai_key: Optional[str] = None


class TenantOut(BaseModel):
    id: int
    name: str
    slug: Optional[str]
    email: str
    plan: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantPasswordUpdate(BaseModel):
    password: str


# ── Overview ──────────────────────────────────────────────────────────────────

class DailyRevenue(BaseModel):
    date: str
    amount: float


class OverviewResponse(BaseModel):
    revenue: float
    expenses: float
    profit: float
    margin: float
    transactions_count: int
    revenue_delta: float
    profit_delta: float
    daily_revenue: list[DailyRevenue]


# ── Finance ───────────────────────────────────────────────────────────────────

class PnlRow(BaseModel):
    label: str
    amount: float
    is_total: bool = False


class WaterfallItem(BaseModel):
    name: str
    value: float
    type: str  # "revenue" | "expense" | "result"


class FinanceResponse(BaseModel):
    total_revenue: float
    total_expenses: float
    total_profit: float
    margin: float
    revenue_delta: float
    pnl_rows: list[PnlRow]
    waterfall: list[WaterfallItem]
    expenses_by_category: list[dict]


# ── Chatters ──────────────────────────────────────────────────────────────────

class ChatterRow(BaseModel):
    name: str
    revenue: float
    transactions: int
    rpc: float
    chatter_pct: float
    chatter_cut: float
    status: str  # "top" | "ok" | "risk" | "miss"


class ChattersResponse(BaseModel):
    chatters: list[ChatterRow]
    total_revenue: float
    plan_completion: float


# ── KPI ───────────────────────────────────────────────────────────────────────

class KpiRow(BaseModel):
    chatter: str
    onlymonster_id: Optional[str]
    messages_sent: int
    revenue: float
    rpc: float


class KpiResponse(BaseModel):
    rows: list[KpiRow]
    total_messages: int
    total_revenue: float
    avg_rpc: float


# ── Events ────────────────────────────────────────────────────────────────────

class EventCreate(BaseModel):
    date: date
    description: str


class EventOut(BaseModel):
    id: int
    date: date
    description: Optional[str]

    model_config = {"from_attributes": True}


# ── Plans ─────────────────────────────────────────────────────────────────────

class PlanUpsert(BaseModel):
    model: str
    plan_amount: float


class PlanOut(BaseModel):
    model: str
    plan_amount: float
    actual: float = 0.0
    completion_pct: float = 0.0

    model_config = {"from_attributes": True}


class PlansResponse(BaseModel):
    plans: list[PlanOut]
    weighted_completion: float


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingUpsert(BaseModel):
    key: str
    value: str


class SettingsResponse(BaseModel):
    settings: dict[str, str]
