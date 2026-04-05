'use client'

import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { Skeleton } from '@/components/ui/skeleton'
import { useFinance } from '@/lib/hooks/useFinance'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { useTeamStore } from '@/lib/hooks/useTeam'
import { formatCurrency } from '@/lib/utils'
import { DollarSign, TrendingDown, Percent, TrendingUp } from 'lucide-react'
import type { EconomicBreakdown } from '@/types'

function EcoCard({ label, amount, pct, color, note }: { label: string; amount: number; pct?: number; color: string; note?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{formatCurrency(amount)}</p>
      {pct !== undefined && (
        <p className="text-xs text-slate-500 mt-0.5">{pct}% от выручки{note && <span className="text-slate-600"> · {note}</span>}</p>
      )}
    </div>
  )
}

function EconomicSummary({ eco, revenue }: { eco: EconomicBreakdown; revenue: number }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">Экономическая модель</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
        <EcoCard label="Моделям"  amount={eco.model_cut}   pct={eco.model_pct}   color="text-rose-400" />
        <EcoCard label="Чаттерам" amount={eco.chatter_cut} pct={eco.chatter_pct} color="text-orange-400" note="по тирам планов" />
        <EcoCard label="Адмнам"   amount={eco.admin_cut}   pct={eco.admin_pct}   color="text-yellow-400" />
        {eco.use_withdraw && (
          <EcoCard label="Вывод" amount={eco.withdraw} pct={eco.withdraw_pct} color="text-slate-400" />
        )}
        {eco.use_retention && eco.retention > 0 && (
          <EcoCard label="Ретеншн (+2.5%)" amount={eco.retention} color="text-emerald-400" />
        )}
        {eco.db_expenses > 0 && (
          <EcoCard label="Прочие расходы" amount={eco.db_expenses} color="text-slate-400" />
        )}
      </div>
      {/* Bar visualization */}
      {revenue > 0 && (
        <div className="mt-2">
          <div className="flex h-3 rounded-full overflow-hidden gap-px">
            <div className="bg-rose-500/70"    style={{ width: `${eco.model_pct}%` }}    title={`Моделям ${eco.model_pct}%`} />
            <div className="bg-orange-500/70"  style={{ width: `${eco.chatter_pct}%` }}  title={`Чаттерам ${eco.chatter_pct}%`} />
            <div className="bg-yellow-500/70"  style={{ width: `${eco.admin_pct}%` }}    title={`Адмнам ${eco.admin_pct}%`} />
            {eco.use_withdraw && (
              <div className="bg-slate-500/70" style={{ width: `${eco.withdraw_pct}%` }} title={`Вывод ${eco.withdraw_pct}%`} />
            )}
            <div className="bg-indigo-500/80 flex-1" title="Агентство" />
          </div>
          <div className="flex items-center gap-4 mt-2 flex-wrap">
            {[
              { color: 'bg-rose-500/70',    label: `Моделям ${eco.model_pct}%` },
              { color: 'bg-orange-500/70',  label: `Чаттерам ${eco.chatter_pct}%` },
              { color: 'bg-yellow-500/70',  label: `Адмнам ${eco.admin_pct}%` },
              ...(eco.use_withdraw ? [{ color: 'bg-slate-500/70', label: `Вывод ${eco.withdraw_pct}%` }] : []),
              { color: 'bg-indigo-500/80',  label: `Агентство ${(100 - eco.model_pct - eco.chatter_pct - eco.admin_pct - (eco.use_withdraw ? eco.withdraw_pct : 0)).toFixed(1)}%` },
            ].map((item) => (
              <div key={item.label} className="flex items-center gap-1.5 text-xs text-slate-400">
                <span className={`w-2 h-2 rounded-sm ${item.color}`} />
                {item.label}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function FinancePage() {
  const { month, year } = useMonthStore()
  const { teamId } = useTeamStore()
  const { data, isLoading, error } = useFinance(month, year, teamId)

  return (
    <div className="flex flex-col h-full">
      <Header title="Финансы" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard label="Выручка"       value={formatCurrency(data.total_revenue)} delta={data.revenue_delta} icon={<DollarSign className="h-4 w-4" />} />
              <MetricCard label="Все расходы"   value={formatCurrency(data.total_expenses)} icon={<TrendingDown className="h-4 w-4" />} />
              <MetricCard label="Прибыль"       value={formatCurrency(data.total_profit)}   icon={<TrendingUp className="h-4 w-4" />} />
              <MetricCard label="Маржа"         value={`${data.margin}%`}                   icon={<Percent className="h-4 w-4" />} />
            </>
          ) : null}
        </div>

        {/* Economic model breakdown */}
        {isLoading ? (
          <Skeleton className="h-44 w-full rounded-xl" />
        ) : data?.economic ? (
          <EconomicSummary eco={data.economic} revenue={data.total_revenue} />
        ) : null}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Waterfall */}
          {isLoading ? (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <Skeleton className="h-4 w-28 mb-4" />
              <Skeleton className="h-[220px] w-full" />
            </div>
          ) : data ? (
            <WaterfallChart data={data.waterfall} />
          ) : null}

          {/* P&L Table */}
          {isLoading ? (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <Skeleton className="h-4 w-36 mb-4" />
              {Array.from({ length: 7 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full mb-2" />
              ))}
            </div>
          ) : data ? (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <p className="text-sm font-semibold text-slate-300 mb-4">P&L Отчёт</p>
              <div className="divide-y divide-slate-700/40">
                {data.pnl_rows.map((row, i) => (
                  <div
                    key={i}
                    className={`flex items-center justify-between py-2 ${row.is_total ? 'font-semibold' : 'pl-4'}`}
                  >
                    <span className={`text-sm ${
                      row.is_positive ? 'text-emerald-400' :
                      row.is_total ? 'text-slate-200' : 'text-slate-400'
                    }`}>
                      {row.label}
                    </span>
                    <span className={`text-sm ${
                      row.is_positive ? 'text-emerald-400' :
                      row.label.includes('Прибыль') ? (row.amount >= 0 ? 'text-emerald-400' : 'text-red-400') :
                      row.is_total ? 'text-slate-100' : 'text-slate-300'
                    }`}>
                      {row.is_positive ? '+' : ''}{formatCurrency(row.amount)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
