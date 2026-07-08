'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { TrendingUp, CheckCircle2, XCircle, AlertTriangle, Clock, Briefcase } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface KpiSnapshot {
  cases_opened: number
  cases_closed_success: number
  cases_closed_failed: number
  cases_cancelled: number
  guardrail_hits: number
  total_points: number
  detect_result_ratio: number | null
  is_calibration: boolean
}

interface Case {
  id: number
  om_user_id: string
  metric_type: string
  stage: string
  priority: string
  review_date: string | null
  baseline_value: number | null
  notes: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const METRIC_LABELS: Record<string, string> = {
  ppv_open_rate: 'PPV Open Rate',
  rpc: 'RPC',
  apv: 'APV',
  total_chats: 'Total Chats',
  revenue: 'Revenue',
}

const STAGE_LABELS: Record<string, string> = {
  detected: 'Обнаружен',
  in_progress: 'В работе',
  hold: 'Холд',
  review_due: 'Ожидает оценки',
  closed: 'Закрыт',
  cancelled: 'Отменён',
}

const STAGE_COLOR: Record<string, string> = {
  detected: 'bg-blue-500/15 text-blue-300',
  in_progress: 'bg-yellow-500/15 text-yellow-300',
  hold: 'bg-orange-500/15 text-orange-300',
  review_due: 'bg-red-500/15 text-red-300',
  closed: 'bg-green-500/15 text-green-300',
  cancelled: 'bg-slate-500/15 text-slate-400',
}

function StageBadge({ stage }: { stage: string }) {
  return (
    <span className={cn('text-xs font-medium px-2 py-0.5 rounded-full', STAGE_COLOR[stage] ?? 'bg-slate-700 text-slate-300')}>
      {STAGE_LABELS[stage] ?? stage}
    </span>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function KpiCard({ kpi }: { kpi: KpiSnapshot }) {
  const ratio = kpi.detect_result_ratio?.toFixed(1) ?? '—'
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-amber-400" />
          Мой KPI за месяц
        </h2>
        {kpi.is_calibration && (
          <span className="text-xs bg-amber-500/15 text-amber-300 px-2 py-0.5 rounded-full font-medium">
            Калибровка
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Metric label="Очки" value={kpi.total_points >= 0 ? `+${kpi.total_points}` : String(kpi.total_points)} accent={kpi.total_points >= 0 ? 'text-green-400' : 'text-red-400'} />
        <Metric label="Открыто" value={kpi.cases_opened} />
        <Metric label="Успешно" value={kpi.cases_closed_success} accent="text-green-400" />
        <Metric label="Провалено" value={kpi.cases_closed_failed} accent={kpi.cases_closed_failed > 0 ? 'text-red-400' : undefined} />
      </div>

      <div className="grid grid-cols-2 gap-3 pt-1 border-t border-slate-700/50">
        <Metric label="Guardrail" value={kpi.guardrail_hits} accent={kpi.guardrail_hits > 0 ? 'text-orange-400' : undefined} />
        <Metric label="Detect:Result" value={ratio} />
      </div>
    </div>
  )
}

function Metric({ label, value, accent }: { label: string; value: number | string; accent?: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500 mb-0.5">{label}</p>
      <p className={cn('text-lg font-bold text-slate-100', accent)}>{value}</p>
    </div>
  )
}

function HoldCaseCard({ c }: { c: Case }) {
  const daysLeft = c.review_date
    ? Math.ceil((new Date(c.review_date).getTime() - Date.now()) / 86400000)
    : null

  return (
    <Link
      href={`/admin-portal/cases/${c.id}`}
      className="flex items-center justify-between px-4 py-3 rounded-lg bg-slate-800/40 hover:bg-slate-800 border border-slate-700/50 transition-colors group"
    >
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-200 truncate">
          {c.om_user_id} · {METRIC_LABELS[c.metric_type] ?? c.metric_type}
        </p>
        <p className="text-xs text-slate-500 mt-0.5 truncate">
          {c.notes?.split('\n')[0]?.replace(/^(Чаттер|Диагноз): /, '') ?? '—'}
        </p>
      </div>
      <div className="flex items-center gap-3 shrink-0 ml-4">
        {daysLeft !== null && (
          <span className={cn('text-xs font-medium', daysLeft <= 3 ? 'text-red-400' : 'text-slate-400')}>
            <Clock className="h-3 w-3 inline mr-1" />
            {daysLeft <= 0 ? 'Сегодня' : `${daysLeft}д`}
          </span>
        )}
        <StageBadge stage={c.stage} />
      </div>
    </Link>
  )
}

function StageCounter({ cases }: { cases: Case[] }) {
  const counts: Record<string, number> = {}
  for (const c of cases) counts[c.stage] = (counts[c.stage] ?? 0) + 1

  const stages = ['detected', 'in_progress', 'hold', 'review_due']
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-4">
        <Briefcase className="h-4 w-4 text-amber-400" />
        Активные кейсы
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {stages.map(s => (
          <div key={s} className="text-center">
            <p className={cn('text-2xl font-bold', counts[s] ? 'text-slate-100' : 'text-slate-600')}>
              {counts[s] ?? 0}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">{STAGE_LABELS[s]}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AdminPortalOverview() {
  const { data: kpi, isLoading: kpiLoading } = useQuery<KpiSnapshot>({
    queryKey: ['admin-portal-kpi'],
    queryFn: () => api.get<KpiSnapshot>('/api/v1/admin-portal/me/kpi').then(r => r.data),
  })

  const { data: cases, isLoading: casesLoading } = useQuery<Case[]>({
    queryKey: ['admin-portal-cases-active'],
    queryFn: () =>
      api.get<Case[]>('/api/v1/admin-portal/cases').then(r => r.data),
  })

  const holdCases = (cases ?? [])
    .filter(c => c.stage === 'hold')
    .sort((a, b) => {
      if (!a.review_date) return 1
      if (!b.review_date) return -1
      return new Date(a.review_date).getTime() - new Date(b.review_date).getTime()
    })
    .slice(0, 5)

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100">Обзор</h1>
        <p className="text-sm text-slate-400 mt-0.5">Кабинет администратора</p>
      </div>

      {/* KPI */}
      {kpiLoading ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : kpi ? (
        <KpiCard kpi={kpi} />
      ) : null}

      {/* Stage counters */}
      {casesLoading ? (
        <Skeleton className="h-28 w-full rounded-xl" />
      ) : cases ? (
        <StageCounter cases={cases} />
      ) : null}

      {/* Hold cases */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <Clock className="h-4 w-4 text-orange-400" />
            Ближайшие HOLD-проверки
          </h2>
          <Link href="/admin-portal/cases?stage=hold" className="text-xs text-amber-400 hover:text-amber-300">
            Все →
          </Link>
        </div>

        {casesLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map(i => <Skeleton key={i} className="h-14 w-full rounded-lg" />)}
          </div>
        ) : holdCases.length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-4">Нет активных HOLD-кейсов</p>
        ) : (
          <div className="space-y-2">
            {holdCases.map(c => <HoldCaseCard key={c.id} c={c} />)}
          </div>
        )}
      </div>
    </div>
  )
}
