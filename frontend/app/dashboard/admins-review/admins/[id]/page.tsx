'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useAdminCases,
  useAdminDetail,
  useAdminKpiHistory,
  useAdminLedger,
  type AdminCaseOut,
} from '@/lib/hooks/useAdminDetail'
import { useRecalcSnapshots } from '@/lib/hooks/useAdminsReview'
import {
  CASE_TYPE_LABELS,
  ledgerEventLabel,
} from '@/lib/adminReviewLabels'
import { STAGE_LABELS_OWNER, fmtRuDate } from '@/lib/qualitativeCase'
import { cn } from '@/lib/utils'

const OPEN_STAGES = new Set([
  'detected',
  'in_progress',
  'hold',
  'review_due',
  'awaiting_review',
])

const STAGE_FILTER_OPTIONS = [
  'detected',
  'in_progress',
  'hold',
  'review_due',
  'awaiting_review',
  'closed',
  'cancelled',
] as const

type TypeFilter = 'all' | 'quantitative' | 'qualitative'
type PeriodMode = 'current' | 'previous' | 'history'

function currentPeriod(): { year: number; month: number } {
  const d = new Date()
  return { year: d.getFullYear(), month: d.getMonth() + 1 }
}

function previousPeriod(): { year: number; month: number } {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)
  return { year: d.getFullYear(), month: d.getMonth() + 1 }
}

function periodLabel(year: number, month: number): string {
  return new Date(year, month - 1, 1).toLocaleDateString('ru-RU', {
    month: 'long',
    year: 'numeric',
  })
}

function currentMonthLabel(): string {
  const { year, month } = currentPeriod()
  return periodLabel(year, month)
}

function caseInPeriod(openedAt: string, year: number, month: number): boolean {
  const [y, m] = openedAt.split('-').map(Number)
  return y === year && m === month
}

function kpiPointsClass(points: number): string {
  if (points >= 20) return 'text-emerald-400'
  if (points < 0) return 'text-red-400'
  return 'text-slate-100'
}

function ledgerPointsClass(points: number): string {
  if (points > 0) return 'text-emerald-400'
  if (points < 0) return 'text-red-400'
  return 'text-slate-400'
}

function formatDetectRatio(ratio: number | null): string {
  if (ratio == null) return '—'
  return ratio.toFixed(2)
}

function formatLedgerDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function caseTypeChip(caseItem: AdminCaseOut): string {
  if (caseItem.case_type === 'qualitative') {
    return caseItem.category ?? 'Качественный'
  }
  return caseItem.metric_type ?? 'Количественный'
}

export default function AdminDetailPage() {
  const params = useParams()
  const router = useRouter()
  const adminId = Number(params.id)

  const { data: detail, isLoading: detailLoading } = useAdminDetail(adminId)
  const { data: cases, isLoading: casesLoading } = useAdminCases(adminId)
  const { data: history } = useAdminKpiHistory(adminId)
  const recalc = useRecalcSnapshots()

  const [periodMode, setPeriodMode] = useState<PeriodMode>('current')
  const [historyYear, setHistoryYear] = useState<number | null>(null)
  const [historyMonth, setHistoryMonth] = useState<number | null>(null)
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [stageFilter, setStageFilter] = useState<Set<string>>(new Set())
  const [openOnly, setOpenOnly] = useState(false)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const selectedPeriod = useMemo(() => {
    if (periodMode === 'current') return currentPeriod()
    if (periodMode === 'previous') return previousPeriod()
    if (historyYear != null && historyMonth != null) {
      return { year: historyYear, month: historyMonth }
    }
    return currentPeriod()
  }, [periodMode, historyYear, historyMonth])

  const { data: ledger, isLoading: ledgerLoading } = useAdminLedger(
    adminId,
    selectedPeriod.year,
    selectedPeriod.month,
  )

  const historyOptions = useMemo(() => {
    const cur = currentPeriod()
    const prev = previousPeriod()
    const skip = new Set([
      `${cur.year}-${cur.month}`,
      `${prev.year}-${prev.month}`,
    ])
    return (history ?? [])
      .filter((h) => !skip.has(`${h.period_year}-${h.period_month}`))
      .slice(0, 12)
  }, [history])

  const filteredCases = useMemo(() => {
    const list = cases ?? []
    return list.filter((c) => {
      if (!caseInPeriod(c.opened_at, selectedPeriod.year, selectedPeriod.month)) {
        return false
      }
      if (typeFilter !== 'all' && c.case_type !== typeFilter) return false
      if (stageFilter.size > 0 && !stageFilter.has(c.stage)) return false
      if (openOnly && !OPEN_STAGES.has(c.stage)) return false
      return true
    })
  }, [cases, selectedPeriod, typeFilter, stageFilter, openOnly])

  const ledgerTotal = useMemo(
    () => (ledger ?? []).reduce((sum, e) => sum + e.points, 0),
    [ledger],
  )

  const threshold = detail?.detect_result_ratio_threshold ?? 15
  const kpi = detail?.current_kpi
  const ratio = kpi?.detect_result_ratio ?? null
  const ratioOver = ratio != null && ratio > threshold

  function showToast(msg: string) {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  async function handleRecalc() {
    try {
      await recalc.mutateAsync(adminId)
      showToast('KPI администратора пересчитан')
    } catch {
      showToast('Ошибка пересчёта KPI')
    }
  }

  function toggleStage(stage: string) {
    setStageFilter((prev) => {
      const next = new Set(prev)
      if (next.has(stage)) next.delete(stage)
      else next.add(stage)
      return next
    })
  }

  function selectHistory(year: number, month: number) {
    setPeriodMode('history')
    setHistoryYear(year)
    setHistoryMonth(month)
  }

  if (detailLoading) {
    return (
      <div className="p-6 max-w-[1200px] mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="p-6 max-w-[1200px] mx-auto">
        <p className="text-slate-400">Администратор не найден</p>
        <Link
          href="/dashboard/admins-review"
          className="text-amber-400 hover:underline text-sm mt-2 inline-block"
        >
          ← К обзору
        </Link>
      </div>
    )
  }

  const { admin } = detail
  const periodTitle = periodLabel(selectedPeriod.year, selectedPeriod.month)

  return (
    <div className="p-6 max-w-[1200px] mx-auto">
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 shadow-2xl text-sm text-slate-100 max-w-xs">
          {toastMsg}
        </div>
      )}

      {/* Header */}
      <div className="mb-6">
        <Link
          href="/dashboard/admins-review"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-4"
        >
          <ArrowLeft className="h-4 w-4" />
          К обзору
        </Link>

        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-slate-100">
                {admin.name ?? '—'}
              </h1>
              {detail.is_calibration && (
                <Badge className="bg-sky-500/15 text-sky-300 border-sky-500/30 text-[10px]">
                  Калибровка
                </Badge>
              )}
            </div>
            <p className="text-sm text-slate-500 mt-0.5">{admin.email}</p>
            {admin.shift_name && (
              <Badge
                variant="outline"
                className="mt-2 text-xs border-slate-600 text-slate-300"
              >
                {admin.shift_name}
              </Badge>
            )}
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
            Пересчитать этого админа
          </Button>
        </div>
      </div>

      {/* KPI panel — always current month */}
      <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-5 mb-6">
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">
          KPI за {currentMonthLabel()}
        </p>
        <div className="flex flex-wrap items-end gap-6">
          <div>
            <p className="text-xs text-slate-500 mb-1">Балл</p>
            <span
              className={cn(
                'text-3xl font-bold tabular-nums',
                kpiPointsClass(kpi?.total_points ?? 0),
              )}
            >
              {(kpi?.total_points ?? 0).toFixed(1)}
            </span>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <div>
              <span className="text-slate-500">Открыто: </span>
              <span className="text-slate-200 tabular-nums">{kpi?.cases_opened ?? 0}</span>
            </div>
            <div>
              <span className="text-slate-500">Успех: </span>
              <span className="text-emerald-400 tabular-nums">
                {kpi?.cases_closed_success ?? 0}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Провал: </span>
              <span className="text-red-400 tabular-nums">
                {kpi?.cases_closed_failed ?? 0}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Отменено: </span>
              <span className="text-slate-400 tabular-nums">{kpi?.cases_cancelled ?? 0}</span>
            </div>
            <div>
              <span className="text-slate-500">Guardrail: </span>
              <span
                className={cn(
                  'tabular-nums',
                  (kpi?.guardrail_hits ?? 0) > 0 ? 'text-amber-400' : 'text-slate-600',
                )}
              >
                {kpi?.guardrail_hits ?? 0}
              </span>
            </div>
            <div>
              <span className="text-slate-500">D:R: </span>
              <span
                className={cn('tabular-nums', ratioOver ? 'text-red-400' : 'text-slate-400')}
                title={
                  ratioOver
                    ? `Порог: ${threshold}, применён антифарм ×0.5`
                    : undefined
                }
              >
                {formatDetectRatio(ratio)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Открытых кейсов: </span>
              <span className="inline-flex items-center gap-1 text-slate-200 tabular-nums">
                <FolderOpen className="h-3.5 w-3.5 text-slate-500" />
                {detail.open_cases_count}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Period switcher */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        <span className="text-xs text-slate-500 mr-1">Период:</span>
        {(['current', 'previous'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => {
              setPeriodMode(mode)
              setHistoryYear(null)
              setHistoryMonth(null)
            }}
            className={cn(
              'text-xs px-3 py-1.5 rounded-lg border transition-colors',
              periodMode === mode
                ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-200'
                : 'border-slate-700 text-slate-400 hover:text-slate-200',
            )}
          >
            {mode === 'current' ? 'Текущий' : 'Предыдущий'}
          </button>
        ))}
        {historyOptions.length > 0 && (
          <div className="relative">
            <select
              value={
                periodMode === 'history' && historyYear != null && historyMonth != null
                  ? `${historyYear}-${historyMonth}`
                  : ''
              }
              onChange={(e) => {
                const v = e.target.value
                if (!v) return
                const [y, m] = v.split('-').map(Number)
                selectHistory(y, m)
              }}
              className={cn(
                'text-xs px-3 py-1.5 rounded-lg border bg-slate-800/60 appearance-none pr-7',
                periodMode === 'history'
                  ? 'border-indigo-500/40 text-indigo-200'
                  : 'border-slate-700 text-slate-400',
              )}
            >
              <option value="">Ранее ▾</option>
              {historyOptions.map((h) => (
                <option
                  key={`${h.period_year}-${h.period_month}`}
                  value={`${h.period_year}-${h.period_month}`}
                >
                  {periodLabel(h.period_year, h.period_month)}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Cases section */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-200 mb-3">
          Кейсы за {periodTitle}
        </h2>

        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="text-xs text-slate-500">Тип:</span>
          {(['all', 'quantitative', 'qualitative'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTypeFilter(t)}
              className={cn(
                'text-xs px-2.5 py-1 rounded-full border transition-colors',
                typeFilter === t
                  ? 'bg-slate-600/50 border-slate-500 text-slate-100'
                  : 'border-slate-700 text-slate-500 hover:text-slate-300',
              )}
            >
              {t === 'all' ? 'Все' : CASE_TYPE_LABELS[t]}
            </button>
          ))}
          <span className="text-xs text-slate-500 ml-2">Стадия:</span>
          {STAGE_FILTER_OPTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => toggleStage(s)}
              className={cn(
                'text-xs px-2.5 py-1 rounded-full border transition-colors',
                stageFilter.has(s)
                  ? 'bg-slate-600/50 border-slate-500 text-slate-100'
                  : 'border-slate-700 text-slate-500 hover:text-slate-300',
              )}
            >
              {STAGE_LABELS_OWNER[s] ?? s}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setOpenOnly((v) => !v)}
            className={cn(
              'text-xs px-2.5 py-1 rounded-full border transition-colors ml-1',
              openOnly
                ? 'bg-amber-500/15 border-amber-500/30 text-amber-300'
                : 'border-slate-700 text-slate-500 hover:text-slate-300',
            )}
          >
            Только открытые
          </button>
        </div>

        {casesLoading ? (
          <Skeleton className="h-32 w-full rounded-xl" />
        ) : filteredCases.length === 0 ? (
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 py-10 text-center text-sm text-slate-500">
            Нет кейсов за выбранный период
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-700/50">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-800/60">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Чаттер
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Тип
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Стадия
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Открыт
                  </th>
                  <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-500 uppercase">
                    Холд
                  </th>
                </tr>
              </thead>
              <tbody>
                {filteredCases.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() =>
                      router.push(`/dashboard/admins-review/cases/${c.id}`)
                    }
                    className="border-b border-slate-700/30 hover:bg-slate-800/50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5">
                      <p className="text-slate-100">
                        {c.chatter_display_name || c.om_user_id}
                      </p>
                      <p className="text-xs text-slate-500">{c.om_user_id}</p>
                    </td>
                    <td className="px-3 py-2.5 text-slate-300 text-xs">
                      {caseTypeChip(c)}
                    </td>
                    <td className="px-3 py-2.5 text-slate-300 text-xs">
                      {STAGE_LABELS_OWNER[c.stage] ?? c.stage}
                    </td>
                    <td className="px-3 py-2.5 text-slate-400 text-xs">
                      {fmtRuDate(c.opened_at)}
                    </td>
                    <td className="px-3 py-2.5 text-right text-slate-400 tabular-nums text-xs">
                      {c.hold_days ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Ledger section */}
      <section>
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold text-slate-200">
            Ledger за {periodTitle}
          </h2>
          {!ledgerLoading && (ledger?.length ?? 0) > 0 && (
            <span className="text-xs text-slate-500">
              Итого:{' '}
              <span
                className={cn('font-medium tabular-nums', ledgerPointsClass(ledgerTotal))}
              >
                {ledgerTotal > 0 ? '+' : ''}
                {ledgerTotal.toFixed(1)}
              </span>
            </span>
          )}
        </div>

        {ledgerLoading ? (
          <Skeleton className="h-32 w-full rounded-xl" />
        ) : !ledger?.length ? (
          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 py-10 text-center text-sm text-slate-500">
            Нет событий за выбранный период
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-700/50">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-800/60">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Событие
                  </th>
                  <th className="px-3 py-2.5 text-right text-xs font-semibold text-slate-500 uppercase">
                    Баллы
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Кейс
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold text-slate-500 uppercase">
                    Дата
                  </th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((e) => (
                  <tr
                    key={e.id}
                    className="border-b border-slate-700/30 hover:bg-slate-800/40"
                  >
                    <td className="px-4 py-2.5 text-slate-200">
                      {ledgerEventLabel(e.event_type)}
                      {e.notes && (
                        <p className="text-xs text-slate-500 mt-0.5 truncate max-w-xs">
                          {e.notes}
                        </p>
                      )}
                    </td>
                    <td
                      className={cn(
                        'px-3 py-2.5 text-right tabular-nums font-medium',
                        ledgerPointsClass(e.points),
                      )}
                    >
                      {e.points > 0 ? '+' : ''}
                      {e.points.toFixed(1)}
                    </td>
                    <td className="px-3 py-2.5">
                      {e.case_id != null ? (
                        <Link
                          href={`/dashboard/admins-review/cases/${e.case_id}`}
                          className="text-amber-400 hover:underline text-xs"
                          onClick={(ev) => ev.stopPropagation()}
                        >
                          #{e.case_id}
                        </Link>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-slate-400 text-xs whitespace-nowrap">
                      {formatLedgerDate(e.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
