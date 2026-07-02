'use client'

import { useState } from 'react'
import { DollarSign, TrendingUp, Percent, Receipt, Download } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { RevenueChart, RevenueChartSkeleton } from '@/components/charts/RevenueChart'
import { useOverview } from '@/lib/hooks/useOverview'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { useTeamStore } from '@/lib/hooks/useTeam'
import { teamColor } from '@/lib/teamColors'
import { formatCurrency } from '@/lib/utils'
import { resolveApiBaseURL } from '@/lib/api'
import { AgentInsights } from '@/components/agent/AgentInsights'

function fmtForecast(v?: number | null) {
  if (v == null) return undefined
  if (v >= 1000) return `$${(v / 1000).toFixed(1)}k`
  return `$${v.toFixed(0)}`
}

export default function OverviewPage() {
  const { month, year } = useMonthStore()
  const { teamId } = useTeamStore()
  const { data, isLoading, error } = useOverview(month, year, teamId)
  const [exporting, setExporting] = useState(false)

  async function handleExport() {
    setExporting(true)
    try {
      const base = resolveApiBaseURL()
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null
      const res = await fetch(`${base}/api/v1/export/overview?month=${month}&year=${year}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error('Ошибка сервера')
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `overview_${year}_${String(month).padStart(2, '0')}.csv`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) { console.error(e) }
    finally { setExporting(false) }
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Overview" actions={
        <button
          onClick={handleExport}
          disabled={exporting || isLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700/60 hover:bg-slate-700 disabled:opacity-50 border border-slate-600/50 text-slate-300 text-sm rounded-lg transition-colors"
        >
          <Download className="h-4 w-4" />
          {exporting ? 'Экспорт...' : 'Экспорт CSV'}
        </button>
      } />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {/* Agent memory insights */}
        <AgentInsights />

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {isLoading ? (
            <>
              <MetricCardSkeleton />
              <MetricCardSkeleton />
              <MetricCardSkeleton />
              <MetricCardSkeleton />
            </>
          ) : data ? (
            <>
              <MetricCard
                label="Выручка"
                value={formatCurrency(data.revenue)}
                delta={data.is_current_month ? undefined : data.revenue_delta}
                forecast={data.is_current_month ? fmtForecast(data.revenue_forecast) : undefined}
                forecastLabel="Прогноз на месяц:"
                icon={<DollarSign className="h-4 w-4" />}
              />
              <MetricCard
                label="Прибыль"
                value={formatCurrency(data.profit)}
                delta={data.is_current_month ? undefined : data.profit_delta}
                forecast={data.is_current_month ? fmtForecast(data.profit_forecast) : undefined}
                forecastLabel="Прогноз на месяц:"
                icon={<TrendingUp className="h-4 w-4" />}
              />
              <MetricCard
                label="Маржа"
                value={`${data.margin}%`}
                icon={<Percent className="h-4 w-4" />}
              />
              <MetricCard
                label="Транзакции"
                value={data.transactions_count.toLocaleString()}
                icon={<Receipt className="h-4 w-4" />}
              />
            </>
          ) : null}
        </div>

        {!isLoading && data && teamId === 'all' && (data.teams_breakdown?.length ?? 0) > 1 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">По командам</p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {(data.teams_breakdown ?? []).map((t) => {
                const c = teamColor(t.team_id)
                return (
                  <div
                    key={t.team_id}
                    className={`rounded-xl p-4 border bg-slate-800/50 ${c.text} ${c.border} ${c.bg}`}
                  >
                    <p className="text-sm font-medium text-slate-200 flex items-center gap-2">
                      <span className={`inline-block h-2 w-2 rounded-full ${c.dot}`} />
                      {t.name}
                    </p>
                    <p className="text-lg font-bold mt-1">{formatCurrency(t.revenue)}</p>
                    <div className="text-xs text-slate-500 mt-2 space-y-0.5">
                      <p>Чаттеры: {formatCurrency(t.chatter_cut)}</p>
                      <p>Админы: {formatCurrency(t.admin_cut)}</p>
                      <p className="text-slate-400">
                        Маржа {t.margin}% · прибыль {formatCurrency(t.profit)}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Revenue chart */}
        {isLoading ? (
          <RevenueChartSkeleton />
        ) : data ? (
          <RevenueChart data={data.daily_revenue} />
        ) : null}

        {/* Expenses summary */}
        {!isLoading && data && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <p className="text-sm text-slate-400 mb-2">Расходы</p>
              <p className="text-2xl font-bold text-slate-100">{formatCurrency(data.expenses)}</p>
            </div>
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <p className="text-sm text-slate-400 mb-2">Маржинальность</p>
              <p className="text-2xl font-bold text-slate-100">{data.margin}%</p>
              <p className="text-xs text-slate-500 mt-1">Прибыль / Выручка</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
