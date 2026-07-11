'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  FolderOpen,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useAdminsReview,
  useRecalcSnapshots,
  type AdminListItem,
} from '@/lib/hooks/useAdminsReview'
import { cn } from '@/lib/utils'

type SortKey = 'total_points' | 'cases_closed_success' | 'cases_closed_failed' | 'open_cases_count'

function currentMonthLabel(): string {
  const d = new Date()
  return d.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })
}

function formatUpdatedAgo(ts: number): string {
  const mins = Math.floor((Date.now() - ts) / 60_000)
  if (mins < 1) return 'только что'
  if (mins === 1) return '1 минуту назад'
  if (mins < 5) return `${mins} минуты назад`
  return `${mins} минут назад`
}

function kpiPointsClass(points: number): string {
  if (points >= 20) return 'text-emerald-400'
  if (points < 0) return 'text-red-400'
  return 'text-slate-100'
}

function formatDetectRatio(ratio: number | null): string {
  if (ratio == null) return '—'
  return ratio.toFixed(2)
}

function sortAdmins(admins: AdminListItem[], key: SortKey, desc: boolean): AdminListItem[] {
  const sorted = [...admins].sort((a, b) => {
    let av = 0
    let bv = 0
    if (key === 'total_points') {
      av = a.current_month_kpi.total_points
      bv = b.current_month_kpi.total_points
    } else if (key === 'cases_closed_success') {
      av = a.current_month_kpi.cases_closed_success
      bv = b.current_month_kpi.cases_closed_success
    } else if (key === 'cases_closed_failed') {
      av = a.current_month_kpi.cases_closed_failed
      bv = b.current_month_kpi.cases_closed_failed
    } else {
      av = a.open_cases_count
      bv = b.open_cases_count
    }
    return av - bv
  })
  return desc ? sorted.reverse() : sorted
}

function SortHeader({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'text-left text-xs font-semibold uppercase tracking-wider transition-colors',
        active ? 'text-indigo-300' : 'text-slate-500 hover:text-slate-300',
      )}
    >
      {label}
    </button>
  )
}

export default function AdminsReviewPage() {
  const router = useRouter()
  const { data, isLoading, dataUpdatedAt } = useAdminsReview()
  const recalc = useRecalcSnapshots()

  const [sortKey, setSortKey] = useState<SortKey>('total_points')
  const [sortDesc, setSortDesc] = useState(true)
  const [lastRecalcAt, setLastRecalcAt] = useState<number | null>(null)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const threshold = data?.detect_result_ratio_threshold ?? 15
  const admins = useMemo(
    () => sortAdmins(data?.admins ?? [], sortKey, sortDesc),
    [data?.admins, sortKey, sortDesc],
  )

  const updatedTs = lastRecalcAt ?? dataUpdatedAt

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDesc((d) => !d)
    } else {
      setSortKey(key)
      setSortDesc(true)
    }
  }

  function showToast(msg: string) {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  async function handleRecalc() {
    try {
      const result = await recalc.mutateAsync(undefined)
      setLastRecalcAt(new Date(result.cached_at).getTime())
      const n = result.recalculated
      const word = n === 1 ? 'админ' : n < 5 ? 'админа' : 'админов'
      showToast(`Пересчитано ${n} ${word}`)
    } catch {
      showToast('Ошибка пересчёта KPI')
    }
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 shadow-2xl text-sm text-slate-100 max-w-xs">
          {toastMsg}
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-2">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Обзор админов</h1>
          <p className="text-xs text-slate-500 mt-1">
            Данные за {currentMonthLabel()}. Последнее обновление:{' '}
            {isLoading ? '…' : formatUpdatedAgo(updatedTs)}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="gap-2 text-slate-400 hover:text-slate-200 shrink-0"
          disabled={recalc.isPending}
          onClick={handleRecalc}
        >
          {recalc.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Пересчитать сейчас
        </Button>
      </div>

      {isLoading ? (
        <div className="mt-6 space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl" />
          ))}
        </div>
      ) : admins.length === 0 ? (
        <div className="mt-8 flex flex-col items-center justify-center py-16 px-6 rounded-xl border border-slate-700/50 bg-slate-800/30 text-center">
          <ShieldCheck className="h-10 w-10 text-slate-600 mb-3" />
          <p className="text-sm text-slate-400 max-w-md">
            В агентстве пока нет админов. Пригласите первого через раздел{' '}
            <Link href="/dashboard/admins" className="text-amber-400 hover:underline">
              Админы
            </Link>
            .
          </p>
        </div>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-xl border border-slate-700/50">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/60">
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Админ
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Смена
                </th>
                <th className="px-3 py-3 text-left">
                  <SortHeader
                    label="KPI-балл"
                    active={sortKey === 'total_points'}
                    onClick={() => toggleSort('total_points')}
                  />
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Открыто
                </th>
                <th className="px-3 py-3 text-right">
                  <SortHeader
                    label="Успех"
                    active={sortKey === 'cases_closed_success'}
                    onClick={() => toggleSort('cases_closed_success')}
                  />
                </th>
                <th className="px-3 py-3 text-right">
                  <SortHeader
                    label="Провал"
                    active={sortKey === 'cases_closed_failed'}
                    onClick={() => toggleSort('cases_closed_failed')}
                  />
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Отменено
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Guardrail
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  D:R
                </th>
                <th className="px-3 py-3 text-right">
                  <SortHeader
                    label="Открытых кейсов"
                    active={sortKey === 'open_cases_count'}
                    onClick={() => toggleSort('open_cases_count')}
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {admins.map((admin) => {
                const kpi = admin.current_month_kpi
                const ratio = kpi.detect_result_ratio
                const ratioOver = ratio != null && ratio > threshold
                return (
                  <tr
                    key={admin.id}
                    onClick={() => router.push(`/dashboard/admins-review/admins/${admin.id}`)}
                    className="border-b border-slate-700/30 hover:bg-slate-800/50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <div>
                          <p className="font-medium text-slate-100">{admin.name ?? '—'}</p>
                          <p className="text-xs text-slate-500">{admin.email}</p>
                        </div>
                        {kpi.is_calibration && (
                          <Badge className="bg-sky-500/15 text-sky-300 border-sky-500/30 text-[10px]">
                            Калибровка
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-slate-300">{admin.shift_name ?? '—'}</td>
                    <td className="px-3 py-3">
                      <span
                        className={cn(
                          'text-lg font-semibold tabular-nums',
                          kpiPointsClass(kpi.total_points),
                        )}
                      >
                        {kpi.total_points.toFixed(1)}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right text-slate-300 tabular-nums">
                      {kpi.cases_opened}
                    </td>
                    <td className="px-3 py-3 text-right text-emerald-400 tabular-nums">
                      {kpi.cases_closed_success}
                    </td>
                    <td className="px-3 py-3 text-right text-red-400 tabular-nums">
                      {kpi.cases_closed_failed}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-500 tabular-nums">
                      {kpi.cases_cancelled}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-3 text-right tabular-nums',
                        kpi.guardrail_hits > 0 ? 'text-amber-400' : 'text-slate-600',
                      )}
                    >
                      {kpi.guardrail_hits}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span
                        className={cn(
                          'tabular-nums',
                          ratioOver ? 'text-red-400' : 'text-slate-400',
                        )}
                        title={
                          ratioOver
                            ? `Порог: ${threshold}, применён антифарм ×0.5`
                            : undefined
                        }
                      >
                        {formatDetectRatio(ratio)}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      <span className="inline-flex items-center gap-1 text-slate-300 tabular-nums">
                        <FolderOpen className="h-3.5 w-3.5 text-slate-500" />
                        {admin.open_cases_count}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
