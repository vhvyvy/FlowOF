'use client'

import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useChatters } from '@/lib/hooks/useChatters'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import type { ChatterStatus } from '@/types'
import { DollarSign, Users, Target, TrendingUp } from 'lucide-react'

const STATUS_BADGE: Record<ChatterStatus, { label: string; variant: 'success' | 'default' | 'warning' | 'danger' }> = {
  top:  { label: 'Топ',    variant: 'success' },
  ok:   { label: 'Норм',   variant: 'default' },
  risk: { label: 'Риск',   variant: 'warning' },
  miss: { label: 'Провал', variant: 'danger'  },
}

function tierStyle(pct: number): { color: string; bg: string; label: string } {
  if (pct >= 25)   return { color: 'text-emerald-400', bg: 'bg-emerald-500/15 border-emerald-500/30', label: '≥100%' }
  if (pct >= 24)   return { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', label: '≥90%'  }
  if (pct >= 23)   return { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', label: '≥80%'  }
  if (pct >= 22)   return { color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/20',         label: '≥70%'  }
  if (pct >= 21)   return { color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/20',         label: '≥60%'  }
  if (pct >= 20)   return { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/20',   label: '≥50%'  }
  if (pct > 0)     return { color: 'text-orange-400',  bg: 'bg-orange-500/10 border-orange-500/20',   label: 'mixed' }
  return             { color: 'text-slate-500',    bg: 'bg-slate-700/30 border-slate-600/30',     label: 'нет плана' }
}

function planCompletionColor(completion: number) {
  if (completion >= 100) return 'text-emerald-400'
  if (completion >= 70)  return 'text-sky-400'
  if (completion >= 50)  return 'text-yellow-400'
  return 'text-red-400'
}

export default function ChattersPage() {
  const { month, year } = useMonthStore()
  const { data, isLoading, error } = useChatters(month, year)

  const completion  = data?.plan_completion ?? 0
  const totalPayout = data?.chatters.reduce((s, c) => s + c.chatter_cut, 0) ?? 0
  const tier        = tierStyle(completion >= 100 ? 25 : completion >= 90 ? 24 : completion >= 80 ? 23 : completion >= 70 ? 22 : completion >= 60 ? 21 : completion >= 50 ? 20 : 0)

  return (
    <div className="flex flex-col h-full">
      <Header title="Чаттеры" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard label="Общая выручка"    value={formatCurrency(data.total_revenue)} icon={<DollarSign className="h-4 w-4" />} />
              <MetricCard label="Чаттеров"          value={data.chatters.length.toString()}    icon={<Users className="h-4 w-4" />} />
              <MetricCard label="Выполнение плана"  value={`${completion}%`}                   icon={<Target className="h-4 w-4" />} />
              <MetricCard label="Итого выплаты"     value={formatCurrency(totalPayout)}         icon={<TrendingUp className="h-4 w-4" />} />
            </>
          ) : null}
        </div>

        {/* Active tier banner */}
        {!isLoading && data && (
          <div className={`flex items-center justify-between px-5 py-3.5 rounded-xl border ${tier.bg}`}>
            <div className="flex items-center gap-3">
              <span className={`text-2xl font-bold ${tier.color}`}>{activePct > 0 ? `${activePct}%` : '—'}</span>
              <div>
                <p className={`text-sm font-semibold ${tier.color}`}>
                  {completion >= 50 ? `Тир по анкетам: каждая анкета считается отдельно` : 'Планы не установлены или выполнение < 50%'}
                </p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Выполнение плана: <span className={`font-semibold ${planCompletionColor(completion)}`}>{completion}%</span>
                  {activePct > 0 && (
                    <span className="ml-2 text-slate-500">· Тиры: ≥100%→25%, ≥90%→24%, ≥80%→23%, ≥70%→22%, ≥60%→21%, ≥50%→20%</span>
                  )}
                </p>
              </div>
            </div>
            <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${tier.bg} ${tier.color}`}>{tier.label}</span>
          </div>
        )}

        {/* Table */}
        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : data && data.chatters.length > 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50 bg-slate-700/20">
                    <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Чаттер</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Выручка</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Транзакции</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">RPC</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">% тира</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Выплата</th>
                    <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {data.chatters.map((chatter) => {
                    const status = STATUS_BADGE[chatter.status]
                    const ts = tierStyle(chatter.chatter_pct)
                    return (
                      <tr key={chatter.name} className="hover:bg-slate-700/20 transition-colors">
                        <td className="px-5 py-3 text-sm font-medium text-slate-200">{chatter.name}</td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">{formatCurrency(chatter.revenue)}</td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">{chatter.transactions}</td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">${chatter.rpc}</td>
                        <td className="px-5 py-3 text-right">
                          {chatter.chatter_pct > 0 ? (
                            <span className={`inline-flex items-center gap-1 text-sm font-bold px-2 py-0.5 rounded-lg border ${ts.bg} ${ts.color}`}>
                              {chatter.chatter_pct}%
                            </span>
                          ) : (
                            <span className="text-slate-600 text-sm">—</span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-sm font-semibold text-right">
                          {chatter.chatter_cut > 0 ? (
                            <span className={ts.color}>{formatCurrency(chatter.chatter_cut)}</span>
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
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
