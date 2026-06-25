'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { DollarSign, TrendingUp, Target, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { formatCurrency } from '@/lib/utils'

const MONTHS_RU = [
  '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

interface Profile {
  full_name: string
  chatter_name: string
  agency_name: string
  email: string
  currency: string
}

interface Adjustment {
  id: number
  type: 'advance' | 'penalty'
  amount: number
  description: string | null
  date: string
}

interface ProfileEntry {
  name: string
  plan_amount: number
  revenue_on_it: number
  performance_pct: number | null
}

interface Overview {
  revenue: number
  transactions: number
  salary: number
  plan_amount: number
  plan_pct: number
  main_profile: ProfileEntry | null
  other_profiles: ProfileEntry[]
  daily_revenue: { date: string; amount: number }[]
  recent_transactions: { date: string; amount: number; model_name: string; shift_name: string }[]
  advances_total?: number
  penalties_total?: number
  to_pay?: number
  adjustments?: Adjustment[]
}

function MetricCard({
  label, value, icon, sub,
}: { label: string; value: string; icon: React.ReactNode; sub?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">{label}</p>
        <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-400">{icon}</div>
      </div>
      <p className="text-2xl font-bold text-slate-100">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

function pctColor(pct: number | null) {
  if (pct === null) return 'text-slate-400'
  if (pct >= 100) return 'text-emerald-400'
  if (pct >= 80)  return 'text-yellow-400'
  return 'text-red-400'
}

function pctBarColor(pct: number | null) {
  if (pct === null) return 'bg-slate-600'
  if (pct >= 100) return 'bg-emerald-500'
  if (pct >= 80)  return 'bg-yellow-500'
  if (pct >= 50)  return 'bg-sky-500'
  return 'bg-red-500'
}

function ProfileCard({ profile }: { profile: ProfileEntry | null | undefined }) {
  const hasPlan = profile && profile.plan_amount > 0
  const pct     = profile?.performance_pct ?? null
  const clamped = Math.min(pct ?? 0, 100)

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">Основная анкета</p>
        <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-400">
          <Target className="h-4 w-4" />
        </div>
      </div>

      {profile ? (
        <>
          <p className="text-base font-semibold text-slate-100 truncate mb-1">{profile.name || '—'}</p>
          <p className={`text-2xl font-bold ${pctColor(pct)}`}>
            {pct !== null ? `${pct.toFixed(1)}%` : '—'}
          </p>
          <div className="mt-2 h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${pctBarColor(pct)}`}
              style={{ width: `${clamped}%` }}
            />
          </div>
          {hasPlan && (
            <p className="text-xs text-slate-500 mt-2">
              {formatCurrency(profile.revenue_on_it)} из {formatCurrency(profile.plan_amount)} плана
            </p>
          )}
          {!hasPlan && (
            <p className="text-xs text-slate-500 mt-2">Нет плана на эту анкету</p>
          )}
        </>
      ) : (
        <p className="text-sm text-slate-500">Нет данных за месяц</p>
      )}
    </div>
  )
}

function SalaryCard({ overview }: { overview: Overview }) {
  const advances  = overview.advances_total  ?? 0
  const penalties = overview.penalties_total ?? 0
  const salary    = overview.salary          ?? 0
  const toPay     = overview.to_pay          ?? (salary - advances - penalties)
  const hasAdj    = advances > 0 || penalties > 0

  const parts: string[] = [`Начислено ${formatCurrency(salary)}`]
  if (advances  > 0) parts.push(`Аванс −${formatCurrency(advances)}`)
  if (penalties > 0) parts.push(`Штрафы −${formatCurrency(penalties)}`)

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">ЗП чистыми</p>
        <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-400">
          <TrendingUp className="h-4 w-4" />
        </div>
      </div>
      <p className="text-2xl font-bold text-slate-100">{formatCurrency(Math.max(0, toPay))}</p>
      {hasAdj && (
        <p className="text-xs text-slate-500 mt-1">{parts.join(' · ')}</p>
      )}
    </div>
  )
}

function FinancesBlock({ overview }: { overview: Overview }) {
  const [open, setOpen] = useState(false)
  const advances  = overview.advances_total  ?? 0
  const penalties = overview.penalties_total ?? 0
  const salary    = overview.salary          ?? 0
  const toPay     = overview.to_pay          ?? (salary - advances - penalties)
  const adjs      = overview.adjustments     ?? []

  // Hide if nothing interesting to show
  if (advances === 0 && penalties === 0) return null

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-5 py-4">
        <p className="text-sm font-semibold text-slate-300 mb-4">Откуда сумма</p>

        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-slate-400">Начислено по тиру</span>
            <span className="text-slate-200">{formatCurrency(salary)}</span>
          </div>
          {advances > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-sky-400">Получено авансом</span>
              <span className="text-sky-400">−{formatCurrency(advances)}</span>
            </div>
          )}
          {penalties > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-red-400">Штрафы</span>
              <span className="text-red-400">−{formatCurrency(penalties)}</span>
            </div>
          )}
          <div className="flex justify-between text-sm font-bold border-t border-slate-600/40 pt-2 mt-2">
            <span className="text-slate-100">= ЗП чистыми</span>
            <span className={toPay >= 0 ? 'text-emerald-400' : 'text-red-400'}>
              {formatCurrency(Math.max(0, toPay))}
            </span>
          </div>
        </div>

        {adjs.length > 0 && (
          <button
            onClick={() => setOpen(v => !v)}
            className="mt-3 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            Подробности
          </button>
        )}

        {open && adjs.length > 0 && (
          <div className="mt-2 space-y-1.5 border-t border-slate-700/40 pt-2">
            {adjs.map((a) => (
              <div key={a.id} className="flex items-center gap-2">
                <span className={`text-xs font-semibold ${a.type === 'advance' ? 'text-sky-400' : 'text-red-400'}`}>
                  {a.type === 'advance' ? 'Аванс' : 'Штраф'} {a.type === 'penalty' ? '−' : ''}{formatCurrency(a.amount)}
                </span>
                <span className="text-xs text-slate-500">{a.date.slice(5)}</span>
                {a.description && (
                  <span className="text-xs text-slate-400 truncate">{a.description}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function PortalOverviewPage() {
  const { month, year } = useMonthStore()

  const { data: profile } = useQuery<Profile>({
    queryKey: ['portal-profile'],
    queryFn: () => api.get<Profile>('/api/v1/me/profile').then(r => r.data),
  })

  const { data: overview, isLoading } = useQuery<Overview>({
    queryKey: ['portal-overview', month, year],
    queryFn: () =>
      api.get<Overview>(`/api/v1/me/overview?month=${month}&year=${year}`).then(r => r.data),
    enabled: month > 0 && year > 0,
  })

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900">
        <h1 className="text-lg font-semibold text-slate-100">Мой обзор</h1>
      </header>

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {/* Приветствие */}
        <div className="bg-gradient-to-r from-violet-500/10 to-slate-800/60 border border-violet-500/20 rounded-xl p-5">
          <p className="text-xl font-semibold text-slate-100">
            Привет, {profile?.full_name || profile?.chatter_name || '…'}!
          </p>
          {profile && (
            <p className="text-sm text-slate-400 mt-1">
              Агентство <span className="text-violet-300 font-medium">{profile.agency_name}</span>
              {' · '}
              {MONTHS_RU[month]} {year}
            </p>
          )}
        </div>

        {/* Метрики */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {isLoading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
                <Skeleton className="h-4 w-24 mb-3" />
                <Skeleton className="h-8 w-32" />
              </div>
            ))
          ) : overview ? (
            <>
              <MetricCard
                label="Моя выручка"
                value={formatCurrency(overview.revenue)}
                icon={<DollarSign className="h-4 w-4" />}
                sub={`${overview.transactions} транзакций`}
              />
              <SalaryCard overview={overview} />
              <ProfileCard profile={overview.main_profile} />
            </>
          ) : null}
        </div>

        {/* Другие анкеты */}
        {!isLoading && overview && overview.other_profiles && overview.other_profiles.length > 0 && (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-700/40">
              <p className="text-sm font-semibold text-slate-300">Другие мои анкеты</p>
            </div>
            <div className="divide-y divide-slate-700/30">
              {overview.other_profiles.map((p, i) => {
                const hasPlan = p.plan_amount > 0
                const pct = p.performance_pct
                return (
                  <div key={i} className="flex items-center justify-between px-5 py-3 gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-200 truncate">{p.name}</p>
                      <p className="text-xs text-slate-500 mt-0.5">
                        {formatCurrency(p.revenue_on_it)}
                        {hasPlan ? ` / ${formatCurrency(p.plan_amount)} плана` : ' · нет плана'}
                      </p>
                    </div>
                    <span className={`text-sm font-bold shrink-0 ${pctColor(pct)}`}>
                      {pct !== null ? `${pct.toFixed(1)}%` : '—'}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* График выручки по дням */}
        {!isLoading && overview && overview.daily_revenue.length > 0 && (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
            <p className="text-sm font-semibold text-slate-300 mb-4">Выручка по дням</p>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={overview.daily_revenue} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="portalGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  tickFormatter={(v: string) => v.slice(5)}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  tickFormatter={(v) => { const n = Number(v); return `$${n >= 1000 ? (n / 1000).toFixed(1) + 'k' : n}` }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#94a3b8', fontSize: 12 }}
                  itemStyle={{ color: '#e2e8f0', fontSize: 12 }}
                  formatter={(v) => [`$${Number(v).toLocaleString()}`, 'Выручка']}
                />
                <Area
                  type="monotone"
                  dataKey="amount"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  fill="url(#portalGrad)"
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Последние транзакции */}
        {!isLoading && overview && overview.recent_transactions.length > 0 && (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700/40">
              <p className="text-sm font-semibold text-slate-300">Последние транзакции</p>
              <Link
                href="/portal/transactions"
                className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
              >
                Все мои транзакции
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            <div className="divide-y divide-slate-700/30">
              {overview.recent_transactions.map((txn, i) => (
                <div key={i} className="flex items-center gap-4 px-5 py-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200 font-medium truncate">
                      {txn.model_name || '—'}
                    </p>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {txn.date}
                      {txn.shift_name ? ` · ${txn.shift_name}` : ''}
                    </p>
                  </div>
                  <p className="text-sm font-semibold text-emerald-400 shrink-0">
                    {formatCurrency(txn.amount)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Откуда сумма (авансы / штрафы) */}
        {!isLoading && overview && <FinancesBlock overview={overview} />}

        {!isLoading && overview && overview.transactions === 0 && (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-8 text-center">
            <p className="text-slate-400 text-sm">Транзакций за этот месяц нет</p>
          </div>
        )}
      </div>
    </div>
  )
}
