'use client'

import { useQuery } from '@tanstack/react-query'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { formatCurrency } from '@/lib/utils'

interface TxnItem {
  date: string
  amount: number
  model_name: string
  shift_name: string
}

export default function PortalTransactionsPage() {
  const { month, year } = useMonthStore()

  const { data, isLoading, error } = useQuery<{ items: TxnItem[] }>({
    queryKey: ['portal-transactions', month, year],
    queryFn: () =>
      api.get<{ items: TxnItem[] }>(`/api/v1/me/transactions?month=${month}&year=${year}`).then(r => r.data),
    enabled: month > 0 && year > 0,
  })

  const items = data?.items ?? []
  const total = items.reduce((s, t) => s + t.amount, 0)

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-slate-100">Мои транзакции</h1>
        {!isLoading && items.length > 0 && (
          <div className="text-right">
            <p className="text-xs text-slate-500">{items.length} транзакций</p>
            <p className="text-sm font-semibold text-emerald-400">{formatCurrency(total)}</p>
          </div>
        )}
      </header>

      <div className="flex-1 p-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4">
            <p className="text-sm text-red-400">Не удалось загрузить транзакции</p>
          </div>
        )}

        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="px-5 py-3 border-b border-slate-700/30 flex items-center gap-4">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-4 w-16" />
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-10 text-center">
            <p className="text-slate-400 text-sm">Транзакций за этот месяц нет</p>
          </div>
        ) : (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-700/20">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Дата</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Анкета</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Смена</th>
                  <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Сумма</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {items.map((txn, i) => (
                  <tr key={i} className="hover:bg-slate-700/20 transition-colors">
                    <td className="px-5 py-3 text-sm text-slate-400">{txn.date}</td>
                    <td className="px-5 py-3 text-sm text-slate-200">{txn.model_name || '—'}</td>
                    <td className="px-5 py-3 text-sm text-slate-400">{txn.shift_name || '—'}</td>
                    <td className="px-5 py-3 text-sm font-semibold text-emerald-400 text-right">
                      {formatCurrency(txn.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
