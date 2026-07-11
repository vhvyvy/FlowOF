'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, Loader2, AlertCircle, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { getUserIdFromToken } from '@/lib/auth'
import CaseActivities from '@/components/admin-portal/CaseActivities'
import { MetricV2Block } from '@/components/admin-portal/MetricV2Block'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Snapshot {
  id: number
  snapshot_type: string
  snapshot_type_v2?: string | null
  metric_type: string
  metric_value: number
  daily_value?: number | null
  week_avg_value?: number | null
  month_current_value?: number | null
  prev_month_value?: number | null
  snapshot_date: string
  snapshot_as_of?: string | null
  source: string
}

interface HistoryEntry {
  id: number
  from_stage: string | null
  to_stage: string
  changed_at: string
  changed_by: string
  notes: string | null
}

interface MetricPoint {
  value: number | null
  date_label: string | null
}

interface CaseDetail {
  id: number
  admin_id: number
  om_user_id: string
  case_type: string
  category: string | null
  metric_type: string | null
  stage: string
  priority: string
  result: string | null
  opened_at: string
  closed_at: string | null
  review_date: string | null
  baseline_value: number | null
  result_value: number | null
  baseline_version?: string
  is_early_month?: boolean
  is_new_chatter?: boolean
  notes: string | null
  snapshots: Snapshot[]
  history: HistoryEntry[]
  today_metric: MetricPoint
  week_avg_metric: MetricPoint
  month_metric: MetricPoint
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
  detected: 'Обнаружен', in_progress: 'В работе', hold: 'Холд',
  review_due: 'На проверке', awaiting_review: 'Ожидает оценки',
  closed: 'Закрыт', cancelled: 'Отменён',
}

const STAGE_DESCRIPTION: Record<string, string> = {
  detected:
    'Обнаружена проблема. Baseline заморожен, план действий ещё не готов.',
  in_progress: 'Работа с чаттером идёт. Скоро уйдём в HOLD-период.',
  hold: 'HOLD-период. Метрику не трогаем, ждём review_date для проверки результата.',
  review_due:
    'Пришло время проверить результат. Система сравнила baseline и текущее значение.',
  awaiting_review: 'Отправлено на оценку владельцу. Ждём решения.',
  cancelled: 'Кейс отменён.',
}

const CLOSED_RESULT_DESCRIPTION: Record<string, string> = {
  success: 'Кейс закрыт успешно.',
  failed: 'Кейс закрыт без результата.',
  cancelled: 'Кейс отменён.',
}

/** Подсказки для кнопок FSM (native title, как в chatters/page). */
const ACTION_TOOLTIPS = {
  detected_to_in_progress:
    'Начать работу с чаттером. Дальше можно перейти в HOLD-период до review_date.',
  detected_to_cancelled: 'Отменить кейс. -1 очко в ledger.',
  in_progress_to_hold:
    'Уйти в HOLD-период. После review_date система автоматически проверит результат.',
  in_progress_to_cancelled: 'Отменить кейс. -1 очко в ledger.',
  hold_to_cancelled:
    'Отменить кейс на HOLD-периоде. Используй, если чаттер уволился, метрика уехала по независимой причине, или кейс потерял смысл. -1 очко в ledger.',
  review_due_to_success:
    'Закрыть как успех. +10 очков в ledger (если нет guardrail).',
  review_due_to_failed: 'Закрыть без результата. -3 очка в ledger.',
  hold_to_awaiting_review:
    'Отправить кейс на оценку владельцу. Овнер решит: сработало, не помогло или вернуть на доработку.',
} as const

function stageDescription(stage: string, result?: string | null): string {
  if (stage === 'closed') {
    return CLOSED_RESULT_DESCRIPTION[result ?? ''] ?? 'Кейс закрыт.'
  }
  return STAGE_DESCRIPTION[stage] ?? ''
}

const STAGE_COLOR: Record<string, string> = {
  detected: 'bg-blue-500/15 text-blue-300',
  in_progress: 'bg-yellow-500/15 text-yellow-300',
  hold: 'bg-orange-500/15 text-orange-300',
  review_due: 'bg-red-500/15 text-red-300',
  awaiting_review: 'bg-violet-500/15 text-violet-300',
  closed: 'bg-green-500/15 text-green-300',
  cancelled: 'bg-slate-600/20 text-slate-400',
}

function getSentForReviewAt(history: HistoryEntry[]): string | null {
  const entries = history.filter(h => h.to_stage === 'awaiting_review')
  if (!entries.length) return null
  return entries[entries.length - 1].changed_at
}

function formatSentForReviewDisplay(iso: string): string {
  const then = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - then.getTime()) / 86400000)
  if (diffDays < 1) return 'менее суток назад'
  if (diffDays <= 7) return `${diffDays} дней назад`
  return then.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function isHoldReviewReady(reviewDate: string | null): boolean {
  if (!reviewDate) return false
  const end = new Date(reviewDate)
  end.setHours(0, 0, 0, 0)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return today >= end
}

function isQualitative(c: CaseDetail): boolean {
  return (c.case_type ?? 'quantitative') === 'qualitative'
}

const CHANGED_BY_LABEL: Record<string, string> = {
  admin: 'Администратор', system: 'Система', owner: 'Овнер',
}

function StageBadge({ stage }: { stage: string }) {
  return (
    <span className={cn('text-xs font-semibold px-2.5 py-1 rounded-full', STAGE_COLOR[stage] ?? 'bg-slate-700 text-slate-300')}>
      {STAGE_LABELS[stage] ?? stage}
    </span>
  )
}

function StageStatusBlock({
  stage,
  result,
  align = 'end',
}: {
  stage: string
  result?: string | null
  align?: 'start' | 'end'
}) {
  const desc = stageDescription(stage, result)
  return (
    <div
      className={cn(
        'flex flex-col gap-1 max-w-[320px]',
        align === 'end' ? 'items-end text-right' : 'items-start text-left',
      )}
    >
      <span className="text-sm font-semibold text-slate-100">
        {STAGE_LABELS[stage] ?? stage}
      </span>
      <StageBadge stage={stage} />
      {desc && <p className="text-xs text-slate-500 leading-snug">{desc}</p>}
    </div>
  )
}

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtVal(metric: string | null, v: number | null): string {
  if (v == null || !metric) return '—'
  if (metric === 'ppv_open_rate') return `${v.toFixed(1)}%`
  if (metric === 'total_chats')   return String(Math.round(v))
  if (metric === 'revenue')       return `$${v.toFixed(0)}`
  return `$${v.toFixed(2)}`
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-3">
      <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</h2>
      {children}
    </div>
  )
}

// ── HOLD test trigger ─────────────────────────────────────────────────────────

function HoldTestButton({ caseId, onDone }: { caseId: number; onDone: () => void }) {
  const [running, setRunning] = useState(false)
  const [toast, setToast]     = useState<string | null>(null)

  async function runReview() {
    setRunning(true)
    setToast(null)
    try {
      const res = await api.post('/api/v1/admin-portal/cases/run-review-now?force_all_hold=true')
      const stats = res.data
      setToast(
        `Проверка запущена: обработано ${stats.processed ?? 0}, закрыто ${stats.closed_success ?? 0}. Обновляю…`
      )
      setTimeout(() => {
        onDone()
        setToast(null)
      }, 1200)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setToast(detail ?? 'Ошибка при запуске проверки')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      {toast && (
        <div className="mb-2 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          {toast}
        </div>
      )}
      <button
        onClick={runReview}
        disabled={running}
        title="Только для отладки: запускает HOLD-проверку немедленно, игнорируя review_date"
        className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-amber-400 transition-colors disabled:opacity-50"
      >
        {running
          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
          : <Zap className="h-3.5 w-3.5" />
        }
        Проверить сейчас (тест)
      </button>
    </div>
  )
}

// ── Action buttons by stage ───────────────────────────────────────────────────

interface ActionsProps {
  caseDetail: CaseDetail
  onAction: () => void
}

function CaseActions({ caseDetail, onAction }: ActionsProps) {
  const qc = useQueryClient()
  const { id } = caseDetail
  const stage = caseDetail.stage
  const qualitative = isQualitative(caseDetail)

  const [loading, setLoading]           = useState(false)
  const [resultNotes, setResultNotes]   = useState('')
  const [error, setError]               = useState<string | null>(null)

  async function patchStage(newStage: string, notes?: string) {
    setLoading(true); setError(null)
    try {
      await api.patch(`/api/v1/admin-portal/cases/${id}/stage`, { new_stage: newStage, notes })
      qc.invalidateQueries({ queryKey: ['admin-portal-case', String(id)] })
      qc.invalidateQueries({ queryKey: ['admin-portal-cases-active'] })
      onAction()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Ошибка')
    } finally { setLoading(false) }
  }

  async function postTransition(targetStage: string, notes?: string) {
    setLoading(true); setError(null)
    try {
      await api.post(`/api/v1/admin-portal/cases/${id}/transition`, { target_stage: targetStage, notes })
      qc.invalidateQueries({ queryKey: ['admin-portal-case', String(id)] })
      qc.invalidateQueries({ queryKey: ['admin-portal-cases-active'] })
      onAction()
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      const detail = resp?.data?.detail
      if (resp?.status === 422 && typeof detail === 'string' && detail.includes('HOLD')) {
        setError('Дождитесь окончания HOLD-периода')
      } else {
        setError(typeof detail === 'string' ? detail : 'Ошибка')
      }
    } finally { setLoading(false) }
  }

  async function closeCase(result: 'success' | 'failed' | 'cancelled') {
    setLoading(true); setError(null)
    try {
      await api.post(`/api/v1/admin-portal/cases/${id}/close`, { result, result_notes: resultNotes })
      qc.invalidateQueries({ queryKey: ['admin-portal-case', String(id)] })
      qc.invalidateQueries({ queryKey: ['admin-portal-cases-active'] })
      onAction()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Ошибка')
    } finally { setLoading(false) }
  }

  if (['closed', 'cancelled'].includes(stage)) {
    return (
      <Section title="Статус">
        <StageStatusBlock stage={stage} result={caseDetail.result} />
        {caseDetail.result && stage === 'closed' && (
          <span className={cn(
            'inline-flex text-xs font-medium px-2 py-0.5 rounded-full mt-2',
            caseDetail.result === 'success' ? 'bg-green-500/15 text-green-300'
            : 'bg-red-500/15 text-red-300',
          )}>
            {caseDetail.result === 'success'
              ? (qualitative ? '✓ Оценка: сработало' : '✓ Успех')
              : (qualitative ? '✗ Оценка: не помогло' : '✗ Провал')}
          </span>
        )}
        {caseDetail.closed_at && (
          <p className="text-xs text-slate-500 mt-2">Закрыт {fmtDate(caseDetail.closed_at)}</p>
        )}
      </Section>
    )
  }

  if (qualitative && stage === 'awaiting_review') {
    const sentAt = getSentForReviewAt(caseDetail.history)
    const sentLabel = sentAt ? formatSentForReviewDisplay(sentAt) : 'недавно'
    return (
      <Section title="Статус">
        <StageStatusBlock stage={stage} result={caseDetail.result} align="start" />
        <div className="mt-3 rounded-lg border border-violet-500/25 bg-violet-500/10 px-4 py-3">
          <p className="text-sm text-violet-200">
            Ожидает оценки владельца. Отправлено {sentLabel}.
          </p>
        </div>
      </Section>
    )
  }

  return (
    <Section title="Действия">
      <StageStatusBlock stage={stage} result={caseDetail.result} align="start" />

      {error && (
        <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}

      {stage === 'detected' && (
        <div className="flex gap-2">
          <Button
            onClick={() => patchStage('in_progress')}
            disabled={loading}
            title={ACTION_TOOLTIPS.detected_to_in_progress}
            className="flex-1 bg-amber-600 hover:bg-amber-500 text-sm"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Начать работу →'}
          </Button>
          <Button
            onClick={() => patchStage('cancelled', 'Отменён администратором')}
            disabled={loading}
            title={ACTION_TOOLTIPS.detected_to_cancelled}
            variant="outline"
            className="text-slate-400 hover:text-red-400 text-sm"
          >
            Отменить
          </Button>
        </div>
      )}

      {stage === 'in_progress' && (
        <div className="flex gap-2">
          <Button
            onClick={() => patchStage('hold')}
            disabled={loading}
            title={ACTION_TOOLTIPS.in_progress_to_hold}
            className="flex-1 bg-amber-600 hover:bg-amber-500 text-sm"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Поставить на HOLD →'}
          </Button>
          <Button
            onClick={() => patchStage('cancelled', 'Отменён администратором')}
            disabled={loading}
            title={ACTION_TOOLTIPS.in_progress_to_cancelled}
            variant="outline"
            className="text-slate-400 hover:text-red-400 text-sm"
          >
            Отменить
          </Button>
        </div>
      )}

      {stage === 'hold' && (
        <div className="space-y-3">
          <p className="text-sm text-slate-400">
            {qualitative ? (
              <>
                HOLD-период до{' '}
                <span className="font-semibold text-violet-300">
                  {caseDetail.review_date ? fmtDate(caseDetail.review_date) : '—'}
                </span>
                . После этой даты можно отправить кейс на оценку владельцу.
              </>
            ) : (
              <>
                Кейс в холде до{' '}
                <span className="font-semibold text-orange-300">
                  {caseDetail.review_date ? fmtDate(caseDetail.review_date) : '—'}
                </span>.
                Система автоматически проверит метрику и переведёт в стадию оценки.
              </>
            )}
          </p>
          <div className="flex gap-2 flex-wrap">
            {qualitative ? (
              <Button
                onClick={() => postTransition('awaiting_review')}
                disabled={loading || !isHoldReviewReady(caseDetail.review_date)}
                title={
                  isHoldReviewReady(caseDetail.review_date)
                    ? ACTION_TOOLTIPS.hold_to_awaiting_review
                    : `Дождитесь окончания HOLD-периода (${caseDetail.review_date ? fmtDate(caseDetail.review_date) : '—'})`
                }
                className="flex-1 min-w-[200px] bg-violet-700 hover:bg-violet-600 text-sm"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Отправить на оценку →'}
              </Button>
            ) : (
              <div className="flex-1">
                <HoldTestButton caseId={id} onDone={onAction} />
              </div>
            )}
            <Button
              onClick={() => patchStage('cancelled', 'Отменён на HOLD-периоде')}
              disabled={loading}
              title={ACTION_TOOLTIPS.hold_to_cancelled}
              variant="outline"
              className="text-slate-400 hover:text-red-400 text-sm shrink-0"
            >
              Отменить
            </Button>
          </div>
        </div>
      )}

      {stage === 'review_due' && (
        <div className="space-y-3">
          {caseDetail.result_value != null && caseDetail.baseline_value != null && (
            <div className="flex items-center gap-4 text-sm">
              <div>
                <p className="text-xs text-slate-500">Baseline</p>
                <p className="font-semibold text-slate-200">{caseDetail.baseline_value}</p>
              </div>
              <ArrowRight className="h-4 w-4 text-slate-600" />
              <div>
                <p className="text-xs text-slate-500">Результат</p>
                <p className="font-semibold text-slate-200">{caseDetail.result_value}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Изменение</p>
                <p className={cn(
                  'font-semibold',
                  (caseDetail.result_value - caseDetail.baseline_value) / caseDetail.baseline_value > 0
                    ? 'text-green-400' : 'text-red-400',
                )}>
                  {caseDetail.baseline_value !== 0
                    ? `${(((caseDetail.result_value - caseDetail.baseline_value) / caseDetail.baseline_value) * 100).toFixed(1)}%`
                    : '—'}
                </p>
              </div>
            </div>
          )}

          <textarea
            value={resultNotes}
            onChange={e => setResultNotes(e.target.value)}
            rows={2}
            placeholder="Комментарий к результату (опционально)..."
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
          />

          <div className="flex gap-2">
            <Button
              onClick={() => closeCase('success')}
              disabled={loading}
              title={ACTION_TOOLTIPS.review_due_to_success}
              className="flex-1 bg-green-700 hover:bg-green-600 text-sm"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : '✓ Сработало'}
            </Button>
            <Button
              onClick={() => closeCase('failed')}
              disabled={loading}
              title={ACTION_TOOLTIPS.review_due_to_failed}
              className="flex-1 bg-red-800 hover:bg-red-700 text-sm"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : '✗ Не помогло'}
            </Button>
          </div>
        </div>
      )}
    </Section>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CaseDetailPage() {
  const params = useParams()
  const router = useRouter()
  const caseId = params.id as string

  const { data: c, isLoading, refetch } = useQuery<CaseDetail>({
    queryKey: ['admin-portal-case', caseId],
    queryFn: () =>
      api.get<CaseDetail>(`/api/v1/admin-portal/cases/${caseId}`).then(r => r.data),
    enabled: !!caseId,
  })

  if (isLoading) {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl" />
      </div>
    )
  }

  if (!c) {
    return (
      <div className="p-6 text-center text-slate-500">
        Кейс не найден
      </div>
    )
  }

  const baselineSnap = c.snapshots.find(
    s => s.snapshot_type === 'baseline' && (s.snapshot_type_v2 === 'baseline_v2' || !s.snapshot_type_v2),
  ) ?? c.snapshots.find(s => s.snapshot_type === 'baseline')
  const resultSnap = c.snapshots.find(
    s => s.snapshot_type === 'result' && s.snapshot_type_v2 === 'review_v2',
  ) ?? c.snapshots.find(s => s.snapshot_type === 'result')
  const isV2 = (c.baseline_version ?? 'v1') === 'v2'
  const isClosed = c.stage === 'closed'

  const diagnosisLines = (c.notes ?? '').split('\n')
  const chatterLine = diagnosisLines.find(l => l.startsWith('Чаттер:'))?.replace('Чаттер: ', '') ?? c.om_user_id
  const diagnosisLine = diagnosisLines.find(l => l.startsWith('Диагноз:'))?.replace('Диагноз: ', '') ?? ''
  const planLine      = diagnosisLines.find(l => l.startsWith('План:'))?.replace('План: ', '') ?? ''

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Назад
      </button>

      {/* Header */}
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-bold text-slate-100">{chatterLine}</h1>
            {isQualitative(c) ? (
              <div className="flex flex-wrap items-center gap-2 mt-1.5">
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30">
                  Качественный
                </span>
                {c.category && (
                  <span className="text-sm text-slate-300">
                    Категория: <span className="text-violet-200 font-medium">{c.category}</span>
                  </span>
                )}
              </div>
            ) : (
              <p className="text-sm text-amber-300 font-medium mt-0.5">
                {METRIC_LABELS[c.metric_type ?? ''] ?? c.metric_type}
              </p>
            )}
            <p className="text-xs text-slate-500 mt-0.5">ID: {c.om_user_id} · Открыт {fmtDate(c.opened_at)}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StageStatusBlock stage={c.stage} result={c.result} />
            {c.priority === 'high' && (
              <span className="text-xs bg-red-500/15 text-red-300 px-2 py-0.5 rounded-full">Высокий приоритет</span>
            )}
          </div>
        </div>
      </div>

      {/* Metric overview: quantitative only */}
      {!isQualitative(c) && baselineSnap && c.metric_type && (
        <Section title="Метрика">
          {isV2 && baselineSnap.snapshot_type_v2 === 'baseline_v2' ? (
            <MetricV2Block
              metric={c.metric_type}
              isClosed={isClosed}
              isEarlyMonth={c.is_early_month}
              isNewChatter={c.is_new_chatter}
              baseline={{
                daily_value: baselineSnap.daily_value,
                week_avg_value: baselineSnap.week_avg_value,
                month_current_value: baselineSnap.month_current_value,
                prev_month_value: baselineSnap.prev_month_value,
                snapshot_date: baselineSnap.snapshot_date,
                snapshot_as_of: baselineSnap.snapshot_as_of ?? baselineSnap.snapshot_date,
              }}
              now={
                !isClosed
                  ? (() => {
                      const y = new Date()
                      y.setDate(y.getDate() - 1)
                      return {
                        daily_value: c.today_metric?.value,
                        week_avg_value: c.week_avg_metric?.value,
                        month_current_value: c.month_metric?.value,
                        prev_month_value: baselineSnap.prev_month_value,
                        snapshot_date: y.toISOString().slice(0, 10),
                        snapshot_as_of: new Date().toISOString().slice(0, 10),
                      }
                    })()
                  : null
              }
              outcome={
                isClosed && resultSnap
                  ? {
                      daily_value: resultSnap.daily_value,
                      week_avg_value: resultSnap.week_avg_value,
                      month_current_value: resultSnap.month_current_value,
                      prev_month_value: resultSnap.prev_month_value,
                      snapshot_date: resultSnap.snapshot_date,
                      snapshot_as_of: resultSnap.snapshot_as_of ?? resultSnap.snapshot_date,
                    }
                  : null
              }
            />
          ) : (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* Baseline */}
            <div className="bg-slate-700/30 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Baseline</p>
              <p className="text-lg font-bold text-slate-100">{fmtVal(c.metric_type, baselineSnap.metric_value)}</p>
              <p className="text-xs text-slate-500 mt-1">{fmtDate(baselineSnap.snapshot_date)}</p>
            </div>
            {/* Today */}
            <div className="bg-slate-700/30 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Вчера</p>
              {c.today_metric?.value != null ? (
                <>
                  <p className={cn(
                    'text-lg font-bold',
                    c.today_metric.value >= baselineSnap.metric_value ? 'text-green-400' : 'text-red-400',
                  )}>
                    {fmtVal(c.metric_type, c.today_metric.value)}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">{c.today_metric.date_label ?? '—'}</p>
                </>
              ) : (
                <p className="text-lg font-bold text-slate-600">—</p>
              )}
            </div>
            {/* Week avg */}
            <div className="bg-slate-700/30 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Неделя (среднее)</p>
              {c.week_avg_metric?.value != null ? (
                <>
                  <p className={cn(
                    'text-lg font-bold',
                    c.week_avg_metric.value >= baselineSnap.metric_value ? 'text-green-400' : 'text-red-400',
                  )}>
                    {fmtVal(c.metric_type, c.week_avg_metric.value)}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">{c.week_avg_metric.date_label ?? '—'}</p>
                </>
              ) : (
                <p className="text-lg font-bold text-slate-600">—</p>
              )}
            </div>
            {/* Month */}
            <div className="bg-slate-700/30 rounded-xl p-3">
              <p className="text-xs text-slate-500 mb-1">Месяц (агрегат)</p>
              {c.month_metric?.value != null ? (
                <>
                  <p className={cn(
                    'text-lg font-bold',
                    c.month_metric.value >= baselineSnap.metric_value ? 'text-green-400' : 'text-red-400',
                  )}>
                    {fmtVal(c.metric_type, c.month_metric.value)}
                  </p>
                  <p className="text-xs text-slate-500 mt-1">{c.month_metric.date_label ?? '—'}</p>
                </>
              ) : (
                <p className="text-lg font-bold text-slate-600">—</p>
              )}
            </div>
          </div>
          )}
        </Section>
      )}

      {/* Result snapshot (v1 quantitative, review_due or closed) */}
      {!isQualitative(c) && !isV2 && resultSnap && (
        <Section title="Результат (текущее значение)">
          <div className="flex items-center gap-6 text-sm">
            <div>
              <p className="text-xs text-slate-500 mb-0.5">Значение</p>
              <p className="text-xl font-bold text-slate-100">{resultSnap.metric_value}</p>
            </div>
            {baselineSnap && (
              <div>
                <p className="text-xs text-slate-500 mb-0.5">Изменение</p>
                <p className={cn(
                  'text-xl font-bold',
                  resultSnap.metric_value >= baselineSnap.metric_value ? 'text-green-400' : 'text-red-400',
                )}>
                  {baselineSnap.metric_value !== 0
                    ? `${(((resultSnap.metric_value - baselineSnap.metric_value) / baselineSnap.metric_value) * 100).toFixed(1)}%`
                    : '—'}
                </p>
              </div>
            )}
            <div>
              <p className="text-xs text-slate-500 mb-0.5">На дату</p>
              <p className="font-medium text-slate-300">{fmtDate(resultSnap.snapshot_date)}</p>
            </div>
          </div>
        </Section>
      )}

      {/* Diagnosis & Plan */}
      {(diagnosisLine || planLine) && (
        <Section title="Диагноз и план">
          {diagnosisLine && (
            <div>
              <p className="text-xs text-slate-500 mb-1">Диагноз</p>
              <p className="text-sm text-slate-300 whitespace-pre-wrap">{diagnosisLine}</p>
            </div>
          )}
          {planLine && (
            <div className={diagnosisLine ? 'pt-3 border-t border-slate-700/50' : ''}>
              <p className="text-xs text-slate-500 mb-1">План действий</p>
              <p className="text-sm text-slate-300 whitespace-pre-wrap">{planLine}</p>
            </div>
          )}
        </Section>
      )}

      {/* Actions */}
      <CaseActions caseDetail={c} onAction={refetch} />

      {/* Activities */}
      <CaseActivities
        caseId={c.id}
        currentAdminId={getUserIdFromToken() ?? c.admin_id}
        caseOwnerAdminId={c.admin_id}
      />

      {/* Timeline */}
      {c.history.length > 0 && (
        <Section title="История переходов">
          <div className="space-y-2">
            {c.history.map((h, i) => (
              <div key={h.id} className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-slate-400">
                      {h.from_stage ? `${STAGE_LABELS[h.from_stage] ?? h.from_stage} →` : 'Создан →'}
                    </span>
                    <span className={cn('text-xs font-medium', STAGE_COLOR[h.to_stage]?.split(' ')[1] ?? 'text-slate-300')}>
                      {STAGE_LABELS[h.to_stage] ?? h.to_stage}
                    </span>
                    <span className="text-xs text-slate-600 ml-auto">
                      {CHANGED_BY_LABEL[h.changed_by] ?? h.changed_by} · {fmtDate(h.changed_at)}
                    </span>
                  </div>
                  {h.notes && (
                    <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{h.notes}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}
