'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface LedgerEntry {
  id: number
  case_id: number | null
  event_type: string
  points: number
  notes: string | null
  created_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

const EVENT_LABELS: Record<string, string> = {
  case_opened:          'Кейс открыт',
  case_closed_success:  'Кейс успешно закрыт',
  case_closed_failed:   'Кейс закрыт (провал)',
  case_cancelled:       'Кейс отменён',
  guardrail_triggered:  'Сработал guardrail',
  baseline_frozen:      'Baseline заморожен',
}

const EVENT_COLOR: Record<string, string> = {
  case_opened:          'text-slate-400',
  case_closed_success:  'text-green-400',
  case_closed_failed:   'text-red-400',
  case_cancelled:       'text-slate-500',
  guardrail_triggered:  'text-orange-400',
  baseline_frozen:      'text-blue-400',
}

function PointsBadge({ points }: { points: number }) {
  if (points === 0) return <span className="text-xs text-slate-500">0</span>
  return (
    <span className={cn(
      'text-sm font-bold tabular-nums',
      points > 0 ? 'text-green-400' : 'text-red-400',
    )}>
      {points > 0 ? '+' : ''}{points}
    </span>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const now = new Date()
  const [year, setYear]   = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)

  function prev() {
    if (month === 1) { setYear(y => y - 1); setMonth(12) }
    else setMonth(m => m - 1)
  }
  function next() {
    const cur = month === now.getMonth() + 1 && year === now.getFullYear()
    if (cur) return
    if (month === 12) { setYear(y => y + 1); setMonth(1) }
    else setMonth(m => m + 1)
  }
  const isCurrent = month === now.getMonth() + 1 && year === now.getFullYear()

  const { data: entries, isLoading } = useQuery<LedgerEntry[]>({
    queryKey: ['admin-portal-ledger', year, month],
    queryFn: () =>
      api.get<LedgerEntry[]>(`/api/v1/admin-portal/me/ledger?year=${year}&month=${month}`)
        .then(r => r.data),
  })

  const totalPoints = (entries ?? []).reduce((s, e) => s + e.points, 0)
  const successCount  = (entries ?? []).filter(e => e.event_type === 'case_closed_success').length
  const failedCount   = (entries ?? []).filter(e => e.event_type === 'case_closed_failed').length
  const guardrailCount = (entries ?? []).filter(e => e.event_type === 'guardrail_triggered').length

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-100">История очков</h1>
        <p className="text-sm text-slate-400 mt-0.5">Все события ledger по вашим кейсам</p>
      </div>

      {/* Month picker */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={prev}
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-sm font-semibold text-slate-200 min-w-[120px] text-center">
          {MONTHS_RU[month - 1]} {year}
        </span>
        <button
          onClick={next}
          disabled={isCurrent}
          className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors disabled:opacity-30"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Summary */}
      {!isLoading && entries && entries.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {[
            { label: 'Итог очков', value: totalPoints >= 0 ? `+${totalPoints}` : String(totalPoints), accent: totalPoints >= 0 ? 'text-green-400' : 'text-red-400' },
            { label: 'Успехов',    value: successCount,   accent: successCount  > 0 ? 'text-green-400' : 'text-slate-400' },
            { label: 'Провалов',   value: failedCount,    accent: failedCount   > 0 ? 'text-red-400'   : 'text-slate-400' },
            { label: 'Guardrail',  value: guardrailCount, accent: guardrailCount > 0 ? 'text-orange-400' : 'text-slate-400' },
          ].map(({ label, value, accent }) => (
            <div key={label} className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-3 text-center">
              <p className={cn('text-xl font-bold', accent)}>{value}</p>
              <p className="text-xs text-slate-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Events list */}
      {isLoading ? (
        <div className="space-y-2">
          {[1,2,3,4].map(i => <Skeleton key={i} className="h-16 w-full rounded-xl" />)}
        </div>
      ) : !entries?.length ? (
        <div className="text-center py-12 text-slate-500">
          <p>Событий за {MONTHS_RU[month - 1]} {year} нет</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map(e => (
            <div
              key={e.id}
              className="flex items-center justify-between px-4 py-3 bg-slate-800/40 border border-slate-700/50 rounded-xl"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={cn('text-sm font-medium', EVENT_COLOR[e.event_type] ?? 'text-slate-300')}>
                    {EVENT_LABELS[e.event_type] ?? e.event_type}
                  </span>
                  {e.case_id && (
                    <Link
                      href={`/admin-portal/cases/${e.case_id}`}
                      className="text-xs text-amber-400 hover:text-amber-300"
                    >
                      Кейс #{e.case_id}
                    </Link>
                  )}
                </div>
                {e.notes && (
                  <p className="text-xs text-slate-500 mt-0.5 truncate max-w-sm">{e.notes}</p>
                )}
                <p className="text-xs text-slate-600 mt-0.5">
                  {new Date(e.created_at).toLocaleDateString('ru-RU', {
                    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
                  })}
                </p>
              </div>
              <div className="ml-4 shrink-0">
                <PointsBadge points={e.points} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
