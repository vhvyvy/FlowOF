'use client'

import { useQuery } from '@tanstack/react-query'
import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Skeleton } from '@/components/ui/skeleton'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import api from '@/lib/api'
import { Users, DollarSign, Calendar, TrendingUp, Percent } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'

// ── Types ────────────────────────────────────────────────────────────────────

interface ShiftRow {
  name: string
  revenue: number
  transactions: number
  chatters: number
  models: number
  active_days: number
  avg_check: number
  revenue_per_chatter: number | null
  revenue_per_model: number | null
  productivity_per_day: number | null
  share_pct: number
  admin_payout: number
  plan_completion: number | null
  avg_ppv_open_rate: number | null
  avg_apv: number | null
  total_chats_sum: number | null
}

interface ShiftsResponse {
  shifts: ShiftRow[]
  total_revenue: number
  admin_pct: number
  admin_payout_total: number
  admin_payout_each: number
  shifts_count: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const SHIFT_COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e', '#a78bfa']

function fmt(v: number | null | undefined, prefix = '', suffix = '', digits = 2): string {
  if (v == null) return '—'
  return `${prefix}${v.toFixed(digits)}${suffix}`
}

function fmtPct(v: number | null | undefined) {
  return v == null ? '—' : `${v.toFixed(1)}%`
}

function planColor(v: number | null): string {
  if (v == null) return 'text-slate-500'
  if (v >= 100) return 'text-emerald-400'
  if (v >= 80) return 'text-yellow-400'
  return 'text-rose-400'
}

// ── Shift Card ────────────────────────────────────────────────────────────────

function ShiftCard({ shift, index, adminPct }: { shift: ShiftRow; index: number; adminPct: number }) {
  const color = SHIFT_COLORS[index % SHIFT_COLORS.length]
  const hasOmData = shift.avg_ppv_open_rate != null || shift.avg_apv != null

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-700/40"
        style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-sm font-bold"
          style={{ backgroundColor: color + '33', border: `1px solid ${color}55` }}>
          {index + 1}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate">{shift.name}</p>
          <p className="text-xs text-slate-500">{shift.active_days} активных дней · {shift.chatters} чаттеров · {shift.models} анкет</p>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold" style={{ color }}>{formatCurrency(shift.revenue)}</p>
          <p className="text-xs text-slate-500">{shift.share_pct}% от выручки</p>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-slate-700/30">
        {[
          { label: 'Транзакций', value: shift.transactions.toLocaleString() },
          { label: 'Средний чек', value: formatCurrency(shift.avg_check) },
          { label: '$/день', value: fmt(shift.productivity_per_day, '$') },
          { label: '$/чаттер', value: fmt(shift.revenue_per_chatter, '$') },
        ].map(({ label, value }) => (
          <div key={label} className="bg-slate-800/40 px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">{label}</p>
            <p className="text-sm font-medium text-slate-200">{value}</p>
          </div>
        ))}
      </div>

      {/* Onlymonster metrics (if available) */}
      {hasOmData && (
        <div className="grid grid-cols-3 gap-px bg-slate-700/30 border-t border-slate-700/30">
          {[
            { label: 'Ср. PPV Open Rate', value: fmtPct(shift.avg_ppv_open_rate) },
            { label: 'Ср. APV', value: fmt(shift.avg_apv, '$') },
            { label: 'Total Chats', value: shift.total_chats_sum?.toLocaleString() ?? '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-slate-800/30 px-4 py-3">
              <p className="text-xs text-slate-500 mb-0.5">{label}</p>
              <p className="text-sm font-medium text-slate-300">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Footer: plan + payout */}
      <div className="flex items-center justify-between px-5 py-3 border-t border-slate-700/40">
        <div className="flex items-center gap-4">
          {shift.plan_completion != null && (
            <div>
              <p className="text-xs text-slate-500">Выполнение плана</p>
              <p className={`text-sm font-bold ${planColor(shift.plan_completion)}`}>
                {shift.plan_completion.toFixed(1)}%
              </p>
            </div>
          )}
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">Выплата админу ({adminPct}%)</p>
          <p className="text-sm font-bold text-yellow-400">{formatCurrency(shift.admin_payout)}</p>
        </div>
      </div>
    </div>
  )
}

// ── Revenue Bar Chart ─────────────────────────────────────────────────────────

function RevenueChart({ shifts }: { shifts: ShiftRow[] }) {
  const data = shifts.map((s, i) => ({
    name: s.name.length > 12 ? s.name.slice(0, 12) + '…' : s.name,
    revenue: s.revenue,
    payout: s.admin_payout,
    color: SHIFT_COLORS[i % SHIFT_COLORS.length],
  }))

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">Выручка по сменам</p>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} barCategoryGap="30%">
          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} width={50} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#94a3b8', fontSize: 12 }}
            itemStyle={{ color: '#e2e8f0', fontSize: 12 }}
            formatter={(v) => [typeof v === 'number' ? formatCurrency(v) : v, 'Выручка']}
          />
          <Bar dataKey="revenue" radius={[6, 6, 0, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.color} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Productivity Comparison ───────────────────────────────────────────────────

function ProductivityTable({ shifts }: { shifts: ShiftRow[] }) {
  const sorted = [...shifts].sort((a, b) => (b.productivity_per_day ?? 0) - (a.productivity_per_day ?? 0))
  const maxProd = sorted[0]?.productivity_per_day ?? 1

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/40">
        <p className="text-sm font-semibold text-slate-300">Сравнение продуктивности</p>
        <p className="text-xs text-slate-500 mt-0.5">$/день — выручка на активный день смены</p>
      </div>
      <div className="divide-y divide-slate-700/30">
        {sorted.map((s, i) => {
          const pct = maxProd > 0 && s.productivity_per_day ? (s.productivity_per_day / maxProd) * 100 : 0
          const color = SHIFT_COLORS[shifts.indexOf(s) % SHIFT_COLORS.length]
          return (
            <div key={s.name} className="px-5 py-3 flex items-center gap-4">
              <span className="text-xs text-slate-600 w-4">{i + 1}</span>
              <span className="text-sm text-slate-300 w-32 truncate">{s.name}</span>
              <div className="flex-1 bg-slate-700/40 rounded-full h-2">
                <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
              </div>
              <span className="text-sm font-mono font-medium text-slate-200 w-24 text-right">
                {fmt(s.productivity_per_day, '$')} / день
              </span>
              {s.plan_completion != null && (
                <span className={`text-xs font-medium w-16 text-right ${planColor(s.plan_completion)}`}>
                  план {s.plan_completion.toFixed(0)}%
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ShiftsPage() {
  const { month, year } = useMonthStore()

  const { data, isLoading, error } = useQuery<ShiftsResponse>({
    queryKey: ['shifts', month, year],
    queryFn: () => api.get<ShiftsResponse>(`/api/v1/shifts?month=${month}&year=${year}`).then(r => r.data),
    enabled: month > 0 && year > 0,
  })

  const shifts = data?.shifts ?? []
  const adminPctEach = data ? (data.admin_pct / Math.max(data.shifts_count, 1)) : 0

  return (
    <div className="flex flex-col h-full">
      <Header title="Смены / Админы" />

      <div className="flex-1 p-6 space-y-5 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-rose-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard label="Выручка" value={formatCurrency(data.total_revenue)} icon={<DollarSign className="h-4 w-4" />} />
              <MetricCard label="Смен" value={String(data.shifts_count)} icon={<Users className="h-4 w-4" />} />
              <MetricCard
                label={`Итого админам (${data.admin_pct}%)`}
                value={formatCurrency(data.admin_payout_total)}
                icon={<Percent className="h-4 w-4" />}
              />
              <MetricCard
                label={`Каждому (${adminPctEach.toFixed(1)}%)`}
                value={formatCurrency(data.admin_payout_each)}
                icon={<TrendingUp className="h-4 w-4" />}
              />
            </>
          ) : null}
        </div>

        {/* Admin pool explanation */}
        {data && data.shifts_count > 0 && (
          <div className="bg-yellow-500/5 border border-yellow-500/20 rounded-xl px-5 py-3 flex items-center gap-3">
            <Percent className="h-4 w-4 text-yellow-400 shrink-0" />
            <p className="text-xs text-slate-400">
              <span className="text-yellow-300 font-medium">Admin pool {data.admin_pct}%</span> от общей выручки{' '}
              {formatCurrency(data.total_revenue)} = <span className="text-yellow-300 font-medium">{formatCurrency(data.admin_payout_total)}</span>.
              Делится равномерно на {data.shifts_count} смены → по{' '}
              <span className="text-yellow-300 font-medium">{formatCurrency(data.admin_payout_each)}</span> каждой.
              Изменить % можно в <a href="/dashboard/settings" className="text-indigo-400 underline">Настройках</a>.
            </p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-44 w-full rounded-xl" />)}
          </div>
        ) : shifts.length === 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-12 text-center">
            <Users className="h-10 w-10 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400 font-medium">Нет данных по сменам</p>
            <p className="text-slate-600 text-sm mt-1">Убедитесь, что в транзакциях заполнено поле «Смена»</p>
          </div>
        ) : (
          <>
            {/* Shift cards */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {shifts.map((s, i) => (
                <ShiftCard key={s.name} shift={s} index={i} adminPct={adminPctEach} />
              ))}
            </div>

            {/* Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <RevenueChart shifts={shifts} />
              <ProductivityTable shifts={shifts} />
            </div>

            {/* Detailed table */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-700/40">
                <p className="text-sm font-semibold text-slate-300">Детальная таблица</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-700/50">
                      {['Смена', 'Выручка', 'Транзакций', 'Чаттеров', 'Анкет', 'Дней', 'Ср. чек', '$/день', '$/чаттер', '$/анкету', 'PPV OR', 'APV', 'Chats', 'План %', 'Доля', 'Выплата'].map(h => (
                        <th key={h} className="px-3 py-3 text-left text-xs font-medium text-slate-500 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/25">
                    {shifts.map((s, i) => (
                      <tr key={s.name} className="hover:bg-slate-700/15 transition-colors">
                        <td className="px-3 py-3 font-medium text-slate-200 whitespace-nowrap flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full inline-block shrink-0" style={{ backgroundColor: SHIFT_COLORS[i % SHIFT_COLORS.length] }} />
                          {s.name}
                        </td>
                        <td className="px-3 py-3 text-emerald-400 font-mono">{formatCurrency(s.revenue)}</td>
                        <td className="px-3 py-3 text-slate-300">{s.transactions}</td>
                        <td className="px-3 py-3 text-slate-300">{s.chatters}</td>
                        <td className="px-3 py-3 text-slate-300">{s.models}</td>
                        <td className="px-3 py-3 text-slate-300">{s.active_days}</td>
                        <td className="px-3 py-3 text-slate-300">{formatCurrency(s.avg_check)}</td>
                        <td className="px-3 py-3 text-slate-300">{fmt(s.productivity_per_day, '$')}</td>
                        <td className="px-3 py-3 text-slate-300">{fmt(s.revenue_per_chatter, '$')}</td>
                        <td className="px-3 py-3 text-slate-300">{fmt(s.revenue_per_model, '$')}</td>
                        <td className="px-3 py-3 text-indigo-300">{fmtPct(s.avg_ppv_open_rate)}</td>
                        <td className="px-3 py-3 text-slate-300">{fmt(s.avg_apv, '$')}</td>
                        <td className="px-3 py-3 text-slate-300">{s.total_chats_sum?.toLocaleString() ?? '—'}</td>
                        <td className={`px-3 py-3 font-medium ${planColor(s.plan_completion)}`}>{fmtPct(s.plan_completion)}</td>
                        <td className="px-3 py-3 text-slate-400">{s.share_pct}%</td>
                        <td className="px-3 py-3 text-yellow-400 font-medium">{formatCurrency(s.admin_payout)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
