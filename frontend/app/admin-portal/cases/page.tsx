'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowRight, Calendar } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Case {
  id: number
  om_user_id: string
  metric_type: string
  stage: string
  priority: string
  result: string | null
  opened_at: string
  review_date: string | null
  baseline_value: number | null
  notes: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const METRIC_LABELS: Record<string, string> = {
  ppv_open_rate: 'PPV Open Rate',
  rpc: 'RPC',
  apv: 'APV',
  total_chats: 'Total Chats',
  revenue: 'Revenue',
}

const STAGE_LABELS: Record<string, string> = {
  detected: 'Обнаружен',
  in_progress: 'В работе',
  hold: 'Холд',
  review_due: 'Ожидает оценки',
  closed: 'Закрыт',
  cancelled: 'Отменён',
}

const STAGE_COLOR: Record<string, string> = {
  detected: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
  in_progress: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30',
  hold: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  review_due: 'bg-red-500/15 text-red-300 border-red-500/30',
  closed: 'bg-green-500/15 text-green-300 border-green-500/30',
  cancelled: 'bg-slate-600/20 text-slate-400 border-slate-600/30',
}

const TABS = [
  { value: '', label: 'Все активные' },
  { value: 'detected', label: 'Обнаружен' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'hold', label: 'Холд' },
  { value: 'review_due', label: 'На проверке' },
]

function extractDiagnosis(notes: string | null): string {
  if (!notes) return '—'
  const line = notes.split('\n').find(l => l.startsWith('Диагноз:'))
  return line ? line.replace('Диагноз: ', '').trim() : notes.split('\n')[0] ?? '—'
}

function CaseCard({ c }: { c: Case }) {
  const diagnosis = extractDiagnosis(c.notes)
  const reviewDate = c.review_date ? new Date(c.review_date) : null
  const daysLeft = reviewDate
    ? Math.ceil((reviewDate.getTime() - Date.now()) / 86400000)
    : null

  return (
    <Link
      href={`/admin-portal/cases/${c.id}`}
      className="block bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/50 rounded-xl p-4 transition-colors group"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {/* Header row */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-slate-200 text-sm">{c.om_user_id}</span>
            <span className="text-slate-500 text-xs">·</span>
            <span className="text-xs text-amber-300 font-medium">
              {METRIC_LABELS[c.metric_type] ?? c.metric_type}
            </span>
            {c.priority === 'high' && (
              <span className="text-xs bg-red-500/15 text-red-300 px-1.5 py-0.5 rounded font-medium">Высокий</span>
            )}
          </div>

          {/* Diagnosis */}
          <p className="text-xs text-slate-400 mt-1.5 line-clamp-2">{diagnosis}</p>

          {/* Footer: baseline + review date */}
          <div className="flex items-center gap-4 mt-2.5 text-xs text-slate-500">
            {c.baseline_value != null && (
              <span>Baseline: <span className="text-slate-300 font-medium">{c.baseline_value}</span></span>
            )}
            {reviewDate && (
              <span className={cn('flex items-center gap-1', daysLeft !== null && daysLeft <= 3 ? 'text-red-400' : '')}>
                <Calendar className="h-3 w-3" />
                {reviewDate.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}
                {daysLeft !== null && (
                  <span className="ml-0.5">({daysLeft <= 0 ? 'сегодня' : `${daysLeft}д`})</span>
                )}
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <span className={cn('text-xs font-medium px-2 py-0.5 rounded-full border', STAGE_COLOR[c.stage] ?? 'bg-slate-700 text-slate-300 border-slate-600')}>
            {STAGE_LABELS[c.stage] ?? c.stage}
          </span>
          <ArrowRight className="h-4 w-4 text-slate-600 group-hover:text-amber-400 transition-colors" />
        </div>
      </div>
    </Link>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CasesPage() {
  const searchParams = useSearchParams()
  const initialStage = searchParams.get('stage') ?? ''
  const [activeTab, setActiveTab]       = useState(initialStage)
  const [includeClosed, setIncludeClosed] = useState(false)

  const queryStage   = activeTab || undefined
  const queryParams  = new URLSearchParams()
  if (queryStage) queryParams.set('stage', queryStage)
  if (includeClosed) queryParams.set('include_closed', 'true')

  const { data: cases, isLoading } = useQuery<Case[]>({
    queryKey: ['admin-portal-cases', queryStage, includeClosed],
    queryFn: () =>
      api.get<Case[]>(`/api/v1/admin-portal/cases?${queryParams.toString()}`).then(r => r.data),
  })

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-100">Мои кейсы</h1>
        <p className="text-sm text-slate-400 mt-0.5">Все кейсы, открытые вами</p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 flex-wrap mb-4">
        {TABS.map(tab => (
          <button
            key={tab.value}
            onClick={() => setActiveTab(tab.value)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              activeTab === tab.value
                ? 'bg-amber-500/20 text-amber-300'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
            )}
          >
            {tab.label}
          </button>
        ))}

        <label className="ml-auto flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={e => setIncludeClosed(e.target.checked)}
            className="accent-amber-500 h-3.5 w-3.5"
          />
          Показывать закрытые
        </label>
      </div>

      {/* Cases */}
      {isLoading ? (
        <div className="space-y-3">
          {[1,2,3].map(i => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
        </div>
      ) : !cases?.length ? (
        <div className="text-center py-16 text-slate-500">
          <p>Нет кейсов{activeTab ? ` со стадией «${STAGE_LABELS[activeTab]}»` : ''}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {cases.map(c => <CaseCard key={c.id} c={c} />)}
        </div>
      )}
    </div>
  )
}
