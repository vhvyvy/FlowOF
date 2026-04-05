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
    expenses: float        # total costs (payouts + db_expenses)
    profit: float
    margin: float
    transactions_count: int
    revenue_delta: float
    profit_delta: float
    daily_revenue: list[DailyRevenue]
    economic: Optional[EconomicBreakdown] = None


# ── Finance ───────────────────────────────────────────────────────────────────

class PnlRow(BaseModel):
    label: str
    amount: float
    is_total: bool = False
    is_positive: bool = False  # retention — зелёная строка


class WaterfallItem(BaseModel):
    name: str
    value: float
    type: str  # "revenue" | "expense" | "result" | "retention"


class EconomicBreakdown(BaseModel):
    model_cut: float
    chatter_cut: float
    admin_cut: float
    withdraw: float
    retention: float
    total_payouts: float
    db_expenses: float
    total_costs: float
    model_pct: float
    chatter_pct: float
    admin_pct: float
    withdraw_pct: float
    use_withdraw: bool
    use_retention: bool


class FinanceResponse(BaseModel):
    total_revenue: float
    total_expenses: float   # total_costs including payouts
    total_profit: float
    margin: float
    revenue_delta: float
    pnl_rows: list[PnlRow]
    waterfall: list[WaterfallItem]
    expenses_by_category: list[dict]
    economic: EconomicBreakdown


# ── Chatters ──────────────────────────────────────────────────────────────────

class ChatterModelBreakdown(BaseModel):
    model: str
    revenue: float
    tier_pct: float        # e.g. 25.0
    cut: float             # gross before retention
    retention: float       # 2.5% if enabled, else 0
    net_cut: float         # cut - retention
    plan_amount: float     # 0 = нет плана
    plan_completion: float # 0 = нет плана


class ChatterRow(BaseModel):
    name: str
    revenue: float
    transactions: int
    rpc: float
    chatter_pct: float
    chatter_cut: float
    status: str  # "top" | "ok" | "risk" | "miss"
    models: list[ChatterModelBreakdown] = []


class ChattersResponse(BaseModel):
    chatters: list[ChatterRow]
    total_revenue: float
    plan_completion: float


# ── KPI ───────────────────────────────────────────────────────────────────────

class KpiRow(BaseModel):
    chatter: str
    onlymonster_id: Optional[str] = None
    # From transactions
    revenue: float
    transactions: int           # выходы / смены
    avg_check: float            # revenue / transactions
    share_pct: float            # % от общей выручки
    payout: float               # расчётная оплата (net)
    # From Onlymonster
    ppv_open_rate: Optional[float] = None   # %
    apv: Optional[float] = None             # avg price per sold PPV
    total_chats: Optional[int] = None
    rpc: Optional[float] = None             # revenue / total_chats
    ppv_sold: Optional[float] = None        # revenue / apv
    apc_per_chat: Optional[float] = None    # ppv_sold / total_chats
    volume_rating: Optional[float] = None   # total_chats * ppv_open_rate/100
    # Composite scores
    conversion_score: Optional[float] = None    # ppv_open_rate * apc_per_chat
    monetization_depth: Optional[float] = None  # (rpc/apv)*100
    productivity_index: Optional[float] = None
    efficiency_ratio: Optional[float] = None
    source: Optional[str] = None


class KpiResponse(BaseModel):
    rows: list[KpiRow]
    total_revenue: float
    total_transactions: int
    avg_rpc: Optional[float] = None
    has_onlymonster_key: bool = False


class KpiMappingCreate(BaseModel):
    onlymonster_id: str
    display_name: str


class KpiMappingOut(BaseModel):
    id: int
    onlymonster_id: str
    display_names: Optional[str]

    model_config = {"from_attributes": True}


class KpiSyncResult(BaseModel):
    synced: int
    message: str


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


# ── Structure ─────────────────────────────────────────────────────────────────

class ChatterInModel(BaseModel):
    chatter: str
    revenue: float


class ModelShare(BaseModel):
    model: str
    revenue: float
    share_pct: float
    plan_amount: float
    plan_completion: float  # 0.0 if no plan
    chatters: list[ChatterInModel] = []


class ChatterShare(BaseModel):
    chatter: str
    revenue: float
    share_pct: float
    transactions: int


class StructureResponse(BaseModel):
    total_revenue: float
    models: list[ModelShare]
    chatters: list[ChatterShare]
    economic: EconomicBreakdown


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingUpsert(BaseModel):
    key: str
    value: str


class SettingsResponse(BaseModel):
    settings: dict[str, str]
