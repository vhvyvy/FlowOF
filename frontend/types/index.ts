// ── Auth ──────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface TenantOut {
  id: number
  name: string
  slug: string | null
  email: string
  plan: string
  active: boolean
  created_at: string
}

// ── Overview ──────────────────────────────────────────────────────────────────

export interface DailyRevenue {
  date: string
  amount: number
}

export interface OverviewResponse {
  revenue: number
  expenses: number
  profit: number
  margin: number
  transactions_count: number
  revenue_delta: number
  profit_delta: number
  daily_revenue: DailyRevenue[]
}

// ── Finance ───────────────────────────────────────────────────────────────────

export interface PnlRow {
  label: string
  amount: number
  is_total: boolean
  is_positive?: boolean
}

export interface WaterfallItem {
  name: string
  value: number
  type: 'revenue' | 'expense' | 'result' | 'retention'
}

export interface EconomicBreakdown {
  model_cut: number
  chatter_cut: number
  chatter_cut_gross?: number
  admin_cut: number
  withdraw: number
  retention: number
  total_payouts: number
  db_expenses: number
  total_costs: number
  model_pct: number
  chatter_pct: number
  admin_pct: number
  withdraw_pct: number
  use_withdraw: boolean
  use_retention: boolean
}

export interface FinanceResponse {
  total_revenue: number
  total_expenses: number
  total_profit: number
  margin: number
  revenue_delta: number
  pnl_rows: PnlRow[]
  waterfall: WaterfallItem[]
  expenses_by_category: { category: string; amount: number }[]
  economic: EconomicBreakdown
}

export interface OverviewResponse {
  revenue: number
  expenses: number
  profit: number
  margin: number
  transactions_count: number
  revenue_delta: number
  profit_delta: number
  daily_revenue: { date: string; amount: number }[]
  economic?: EconomicBreakdown
}

// ── Chatters ──────────────────────────────────────────────────────────────────

export type ChatterStatus = 'top' | 'ok' | 'risk' | 'miss'

export interface ChatterModelBreakdown {
  model: string
  revenue: number
  tier_pct: number
  cut: number
  retention: number
  net_cut: number
  plan_amount: number
  plan_completion: number
}

export interface ChatterRow {
  name: string
  revenue: number
  transactions: number
  rpc: number
  chatter_pct: number
  chatter_cut: number
  status: ChatterStatus
  models: ChatterModelBreakdown[]
}

export interface ChattersResponse {
  chatters: ChatterRow[]
  total_revenue: number
  plan_completion: number
}

// ── KPI ───────────────────────────────────────────────────────────────────────

export interface KpiRow {
  chatter: string
  onlymonster_id: string | null
  // From transactions
  revenue: number
  transactions: number
  avg_check: number
  share_pct: number
  payout: number
  // Onlymonster metrics
  ppv_open_rate: number | null
  apv: number | null
  total_chats: number | null
  rpc: number | null
  ppv_sold: number | null
  apc_per_chat: number | null
  volume_rating: number | null
  // Composite scores
  conversion_score: number | null
  monetization_depth: number | null
  productivity_index: number | null
  efficiency_ratio: number | null
  source: string | null
  // Month-over-month deltas
  revenue_delta?: number | null
  rpc_delta?: number | null
  ppv_open_rate_delta?: number | null
  total_chats_delta?: number | null
}

export interface KpiResponse {
  rows: KpiRow[]
  total_revenue: number
  total_transactions: number
  avg_rpc: number | null
  has_onlymonster_key: boolean
}

export interface KpiMappingOut {
  id: number
  onlymonster_id: string
  display_names: string | null
}

export interface KpiSyncResult {
  synced: number
  message: string
}

// ── Events ────────────────────────────────────────────────────────────────────

export interface EventOut {
  id: number
  date: string
  description: string | null
}

export interface EventCreate {
  date: string
  description: string
}

// ── Plans ─────────────────────────────────────────────────────────────────────

export interface PlanOut {
  model: string
  plan_amount: number
  actual: number
  completion_pct: number
}

export interface PlansResponse {
  plans: PlanOut[]
  weighted_completion: number
}

// ── Structure ─────────────────────────────────────────────────────────────────

export interface ChatterInModel {
  chatter: string
  revenue: number
}

export interface ModelShare {
  model: string
  revenue: number
  share_pct: number
  plan_amount: number
  plan_completion: number
  chatters: ChatterInModel[]
}

export interface ChatterShare {
  chatter: string
  revenue: number
  share_pct: number
  transactions: number
}

export interface StructureResponse {
  total_revenue: number
  models: ModelShare[]
  chatters: ChatterShare[]
  economic: EconomicBreakdown
}

// ── UI helpers ────────────────────────────────────────────────────────────────

export interface MonthYear {
  month: number
  year: number
}
