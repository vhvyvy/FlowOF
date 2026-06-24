'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { DollarSign, TrendingUp, Target, ArrowRight } from 'lucide-react'
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

interface Overview {
  revenue: number
  transactions: number
  salary: number
  plan_amount: number
  plan_pct: number
  daily_revenue: { date: string; amount: number }[]
  recent_transactions: { date: string; amount: number; model_name: string; shift_name: string }[]
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

function PlanBar({ pct }: { pct: number }) {
  const clamped = Math.min(pct, 100)
  const color = pct >= 100 ? 'bg-emerald-500' : pct >= 70 ? 'bg-sky-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wide">Выполнение плана</p>
        <div className="p-1.5 bg-violet-500/10 rounded-lg text-violet-400">
          <Target className="h-4 w-4" />
        </div>
      </div>
      <p className="text-2xl font-bold text-slate-100">{pct.toFixed(1)}%</p>
      <div className="mt-3 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${clamped}%` }} />
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
              <MetricCard
                label="Моя зарплата"
                value={formatCurrency(overview.salary)}
                icon={<TrendingUp className="h-4 w-4" />}
                sub="По тиру агентства"
              />
              <PlanBar pct={overview.plan_pct} />
            </>
          ) : null}
        </div>

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
                  tickFormatter={(v: number) => `$${v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v}`}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#94a3b8', fontSize: 12 }}
                  itemStyle={{ color: '#e2e8f0', fontSize: 12 }}
                  formatter={(v: number) => [`$${v.toLocaleString()}`, 'Выручка']}
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

        {!isLoading && overview && overview.transactions === 0 && (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-8 text-center">
            <p className="text-slate-400 text-sm">Транзакций за этот месяц нет</p>
          </div>
        )}
      </div>
    </div>
  )
}
