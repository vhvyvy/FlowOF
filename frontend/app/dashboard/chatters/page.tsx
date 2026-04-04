'use client'

import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useChatters } from '@/lib/hooks/useChatters'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import type { ChatterStatus } from '@/types'
import { DollarSign, Users, Target } from 'lucide-react'

const STATUS_BADGE: Record<ChatterStatus, { label: string; variant: 'success' | 'default' | 'warning' | 'danger' }> = {
  top: { label: 'Топ', variant: 'success' },
  ok: { label: 'Норм', variant: 'default' },
  risk: { label: 'Риск', variant: 'warning' },
  miss: { label: 'Провал', variant: 'danger' },
}

export default function ChattersPage() {
  const { month, year } = useMonthStore()
  const { data, isLoading, error } = useChatters(month, year)

  return (
    <div className="flex flex-col h-full">
      <Header title="Чаттеры" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Summary metrics */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {isLoading ? (
            Array.from({ length: 3 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard
                label="Общая выручка"
                value={formatCurrency(data.total_revenue)}
                icon={<DollarSign className="h-4 w-4" />}
              />
              <MetricCard
                label="Чаттеров"
                value={data.chatters.length.toString()}
                icon={<Users className="h-4 w-4" />}
              />
              <MetricCard
                label="Выполнение плана"
                value={`${data.plan_completion}%`}
                icon={<Target className="h-4 w-4" />}
              />
            </>
          ) : null}
        </div>

        {/* Chatters table */}
        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
            <Skeleton className="h-4 w-28 mb-4" />
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full mb-2" />
            ))}
          </div>
        ) : data && data.chatters.length > 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="p-5 border-b border-slate-700/50">
              <p className="text-sm font-medium text-slate-400">Рейтинг чаттеров</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left px-5 py-3 text-xs font-medium text-slate-500">Чаттер</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">Выручка</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">Транзакции</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">RPC</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">% чаттера</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">Выплата</th>
                    <th className="text-center px-5 py-3 text-xs font-medium text-slate-500">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {data.chatters.map((chatter) => {
                    const status = STATUS_BADGE[chatter.status]
                    return (
                      <tr key={chatter.name} className="hover:bg-slate-700/20 transition-colors">
                        <td className="px-5 py-3 text-sm font-medium text-slate-200">
                          {chatter.name}
                        </td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">
                          {formatCurrency(chatter.revenue)}
                        </td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">
                          {chatter.transactions}
                        </td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">
                          ${chatter.rpc}
                        </td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">
                          {chatter.chatter_pct}%
                        </td>
                        <td className="px-5 py-3 text-sm font-medium text-emerald-400 text-right">
                          {formatCurrency(chatter.chatter_cut)}
                        </td>
                        <td className="px-5 py-3 text-center">
                          <Badge variant={status.variant}>{status.label}</Badge>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : data ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-10 text-center">
            <p className="text-slate-500">Нет данных за выбранный период</p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
