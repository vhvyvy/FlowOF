'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, Loader2, AlertCircle, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Snapshot {
  id: number
  snapshot_type: string
  metric_type: string
  metric_value: number
  snapshot_date: string
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
  metric_type: string
  stage: string
  priority: string
  result: string | null
  opened_at: string
  closed_at: string | null
  review_date: string | null
  baseline_value: number | null
  result_value: number | null
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
  review_due: 'На проверке', closed: 'Закрыт', cancelled: 'Отменён',
}

const STAGE_COLOR: Record<string, string> = {
  detected: 'bg-blue-500/15 text-blue-300',
  in_progress: 'bg-yellow-500/15 text-yellow-300',
  hold: 'bg-orange-500/15 text-orange-300',
  review_due: 'bg-red-500/15 text-red-300',
  closed: 'bg-green-500/15 text-green-300',
  cancelled: 'bg-slate-600/20 text-slate-400',
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

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return new Date(s).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' })
}

function fmtVal(metric: string, v: number | null): string {
  if (v == null) return '—'
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
      setError(detail ?? 'Ошибка')
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
        <div className="flex items-center gap-3">
          <StageBadge stage={stage} />
          {caseDetail.result && (
            <span className={cn(
              'text-xs font-medium px-2 py-0.5 rounded-full',
              caseDetail.result === 'success' ? 'bg-green-500/15 text-green-300'
              : 'bg-red-500/15 text-red-300',
            )}>
              {caseDetail.result === 'success' ? '✓ Успех' : caseDetail.result === 'failed' ? '✗ Провал' : 'Отменён'}
            </span>
          )}
        </div>
        {caseDetail.closed_at && (
          <p className="text-xs text-slate-500">Закрыт {fmtDate(caseDetail.closed_at)}</p>
        )}
      </Section>
    )
  }

  return (
    <Section title="Действия">
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
            className="flex-1 bg-amber-600 hover:bg-amber-500 text-sm"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Начать работу →'}
          </Button>
          <Button
            onClick={() => patchStage('cancelled', 'Отменён администратором')}
            disabled={loading}
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
            className="flex-1 bg-amber-600 hover:bg-amber-500 text-sm"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Поставить на HOLD →'}
          </Button>
          <Button
            onClick={() => patchStage('cancelled', 'Отменён администратором')}
            disabled={loading}
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
            Кейс в холде до{' '}
            <span className="font-semibold text-orange-300">
              {caseDetail.review_date ? fmtDate(caseDetail.review_date) : '—'}
            </span>.
            Система автоматически проверит метрику и переведёт в стадию оценки.
          </p>
          <HoldTestButton caseId={id} onDone={onAction} />
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
              className="flex-1 bg-green-700 hover:bg-green-600 text-sm"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : '✓ Сработало'}
            </Button>
            <Button
              onClick={() => closeCase('failed')}
              disabled={loading}
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

  const baselineSnap = c.snapshots.find(s => s.snapshot_type === 'baseline')
  const resultSnap   = c.snapshots.find(s => s.snapshot_type === 'result')

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
            <p className="text-sm text-amber-300 font-medium mt-0.5">
              {METRIC_LABELS[c.metric_type] ?? c.metric_type}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">ID: {c.om_user_id} · Открыт {fmtDate(c.opened_at)}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StageBadge stage={c.stage} />
            {c.priority === 'high' && (
              <span className="text-xs bg-red-500/15 text-red-300 px-2 py-0.5 rounded-full">Высокий приоритет</span>
            )}
          </div>
        </div>
      </div>

      {/* Metric overview: 4-column row */}
      {baselineSnap && (
        <Section title="Метрика">
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
        </Section>
      )}

      {/* Result snapshot (if review_due or closed) */}
      {resultSnap && (
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
