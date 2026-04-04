'use client'

import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { WaterfallChart } from '@/components/charts/WaterfallChart'
import { Skeleton } from '@/components/ui/skeleton'
import { useFinance } from '@/lib/hooks/useFinance'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import { DollarSign, TrendingDown, Percent } from 'lucide-react'

export default function FinancePage() {
  const { month, year } = useMonthStore()
  const { data, isLoading, error } = useFinance(month, year)

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
              <MetricCard
                label="Выручка"
                value={formatCurrency(data.total_revenue)}
                delta={data.revenue_delta}
                icon={<DollarSign className="h-4 w-4" />}
              />
              <MetricCard
                label="Расходы"
                value={formatCurrency(data.total_expenses)}
                icon={<TrendingDown className="h-4 w-4" />}
              />
              <MetricCard
                label="Прибыль"
                value={formatCurrency(data.total_profit)}
                icon={<DollarSign className="h-4 w-4" />}
              />
              <MetricCard
                label="Маржа"
                value={`${data.margin}%`}
                icon={<Percent className="h-4 w-4" />}
              />
            </>
          ) : null}
        </div>

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

          {/* Expenses by category */}
          {isLoading ? (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <Skeleton className="h-4 w-36 mb-4" />
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full mb-2" />
              ))}
            </div>
          ) : data ? (
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
              <p className="text-sm font-medium text-slate-400 mb-4">Расходы по категориям</p>
              <div className="space-y-2">
                {data.expenses_by_category.map((row) => (
                  <div key={row.category} className="flex items-center justify-between py-1">
                    <span className="text-sm text-slate-300">{row.category}</span>
                    <span className="text-sm font-medium text-slate-100">
                      {formatCurrency(row.amount)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {/* P&L Table */}
        {!isLoading && data && (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
            <p className="text-sm font-medium text-slate-400 mb-4">P&L Отчёт</p>
            <div className="divide-y divide-slate-700/50">
              {data.pnl_rows.map((row, i) => (
                <div
                  key={i}
                  className={`flex items-center justify-between py-2.5 ${
                    row.is_total ? 'font-semibold' : 'pl-4'
                  }`}
                >
                  <span
                    className={`text-sm ${row.is_total ? 'text-slate-200' : 'text-slate-400'}`}
                  >
                    {row.label}
                  </span>
                  <span
                    className={`text-sm ${
                      row.is_total
                        ? row.label.includes('Прибыль')
                          ? 'text-emerald-400'
                          : 'text-slate-100'
                        : 'text-slate-300'
                    }`}
                  >
                    {formatCurrency(row.amount)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
