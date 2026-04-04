'use client'

import { useQuery } from '@tanstack/react-query'
import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Skeleton } from '@/components/ui/skeleton'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import api from '@/lib/api'
import type { KpiResponse } from '@/types'
import { MessageSquare, DollarSign, Zap } from 'lucide-react'

export default function KpiPage() {
  const { month, year } = useMonthStore()

  const { data, isLoading, error } = useQuery<KpiResponse>({
    queryKey: ['kpi', month, year],
    queryFn: () => api.get<KpiResponse>(`/api/v1/kpi?month=${month}&year=${year}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })

  return (
    <div className="flex flex-col h-full">
      <Header title="KPI Чаттеров" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {isLoading ? (
            Array.from({ length: 3 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard
                label="Всего сообщений"
                value={data.total_messages.toLocaleString()}
                icon={<MessageSquare className="h-4 w-4" />}
              />
              <MetricCard
                label="Общая выручка"
                value={formatCurrency(data.total_revenue)}
                icon={<DollarSign className="h-4 w-4" />}
              />
              <MetricCard
                label="Средний RPC"
                value={`$${data.avg_rpc}`}
                icon={<Zap className="h-4 w-4" />}
              />
            </>
          ) : null}
        </div>

        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full mb-2" />
            ))}
          </div>
        ) : data && data.rows.length > 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="p-5 border-b border-slate-700/50">
              <p className="text-sm font-medium text-slate-400">KPI по чаттерам</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left px-5 py-3 text-xs font-medium text-slate-500">Чаттер</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">Сообщения</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">Выручка</th>
                    <th className="text-right px-5 py-3 text-xs font-medium text-slate-500">RPC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {data.rows.map((row) => (
                    <tr key={row.chatter} className="hover:bg-slate-700/20 transition-colors">
                      <td className="px-5 py-3 text-sm font-medium text-slate-200">{row.chatter}</td>
                      <td className="px-5 py-3 text-sm text-slate-300 text-right">
                        {row.messages_sent.toLocaleString()}
                      </td>
                      <td className="px-5 py-3 text-sm text-slate-300 text-right">
                        {formatCurrency(row.revenue)}
                      </td>
                      <td className="px-5 py-3 text-sm font-medium text-indigo-300 text-right">
                        ${row.rpc}
                      </td>
                    </tr>
                  ))}
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
