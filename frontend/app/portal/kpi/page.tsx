'use client'

import { useQuery } from '@tanstack/react-query'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'

interface KpiData {
  chatter: string
  ppv_open_rate: number | null
  apv: number | null
  total_chats: number | null
}

interface KpiResponse {
  kpi: KpiData | null
  has_onlymonster_key: boolean
}

function fmt(v: number | null | undefined, suffix = '', digits = 2): string {
  if (v == null) return '—'
  return `${v.toFixed(digits)}${suffix}`
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-700/30 last:border-0">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="text-sm font-semibold text-slate-100">{value}</p>
    </div>
  )
}

export default function PortalKpiPage() {
  const { month, year } = useMonthStore()

  const { data, isLoading, error } = useQuery<KpiResponse>({
    queryKey: ['portal-kpi', month, year],
    queryFn: () =>
      api.get<KpiResponse>(`/api/v1/me/kpi?month=${month}&year=${year}`).then(r => r.data),
    enabled: month > 0 && year > 0,
  })

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900">
        <h1 className="text-lg font-semibold text-slate-100">Мой KPI</h1>
      </header>

      <div className="flex-1 p-6 space-y-4 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить KPI</p>
          </div>
        )}

        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-6 space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex justify-between items-center">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-20" />
              </div>
            ))}
          </div>
        ) : !data?.has_onlymonster_key ? (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-8 text-center">
            <p className="text-slate-300 font-medium mb-2">Onlymonster не подключён</p>
            <p className="text-slate-500 text-sm">
              Агентство ещё не настроило интеграцию с Onlymonster.
              Обратитесь к владельцу агентства.
            </p>
          </div>
        ) : !data?.kpi ? (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-8 text-center">
            <p className="text-slate-400 text-sm">
              KPI-данных за этот месяц нет. Попробуйте выбрать другой период.
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4">
              Onlymonster метрики
            </p>
            <MetricRow label="PPV Open Rate" value={fmt(data.kpi.ppv_open_rate, '%', 1)} />
            <MetricRow label="APV (средняя цена PPV)" value={data.kpi.apv != null ? `$${data.kpi.apv.toFixed(2)}` : '—'} />
            <MetricRow label="Всего чатов" value={data.kpi.total_chats?.toLocaleString() ?? '—'} />
          </div>
        )}

        <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl p-4">
          <p className="text-xs text-slate-500 leading-relaxed">
            Метрики Onlymonster синхронизируются владельцем агентства. Если данных нет — попросите
            запустить синхронизацию в разделе KPI.
          </p>
        </div>
      </div>
    </div>
  )
}
