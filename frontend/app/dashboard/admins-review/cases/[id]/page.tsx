'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
  RotateCcw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import CaseActivities from '@/components/admin-portal/CaseActivities'
import api, { formatApiError } from '@/lib/api'
import { useOwnerCaseDetail } from '@/lib/hooks/useOwnerCaseDetail'
import {
  CASE_TYPE_LABELS,
  METRIC_LABELS,
  ledgerEventLabel,
} from '@/lib/adminReviewLabels'
import {
  CHANGED_BY_LABEL,
  PRIORITY_LABELS,
  STAGE_LABELS_OWNER,
  fmtRuDate,
  formatSentForReviewDisplay,
} from '@/lib/qualitativeCase'
import { cn } from '@/lib/utils'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-3">
      <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</h2>
      {children}
    </div>
  )
}

function ledgerPointsClass(points: number): string {
  if (points > 0) return 'text-emerald-400'
  if (points < 0) return 'text-red-400'
  return 'text-slate-400'
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

function pctChange(baseline: number | null, result: number | null): string | null {
  if (baseline == null || result == null || baseline === 0) return null
  const pct = ((result - baseline) / Math.abs(baseline)) * 100
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}

const RESULT_LABELS: Record<string, string> = {
  success: 'Успех',
  failed: 'Провал',
  cancelled: 'Отменён',
  guardrail: 'Guardrail',
}

function resultBadgeVariant(result: string): 'success' | 'danger' | 'warning' | 'secondary' {
  if (result === 'success') return 'success'
  if (result === 'failed' || result === 'guardrail') return 'danger'
  if (result === 'cancelled') return 'warning'
  return 'secondary'
}

function stageBadgeClass(stage: string): string {
  if (stage === 'awaiting_review') return 'bg-violet-500/15 text-violet-300 ring-violet-500/30'
  if (stage === 'closed') return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30'
  if (stage === 'cancelled') return 'bg-slate-600/40 text-slate-400 ring-slate-600/40'
  if (stage === 'hold') return 'bg-amber-500/15 text-amber-300 ring-amber-500/30'
  return 'bg-slate-700/60 text-slate-300 ring-slate-600/40'
}

export default function OwnerCaseDetailPage() {
  const params = useParams()
  const router = useRouter()
  const qc = useQueryClient()
  const caseId = Number(params.id)

  const { data: c, isLoading, error } = useOwnerCaseDetail(caseId)

  const [confirmAction, setConfirmAction] = useState<'success' | 'failed' | null>(null)
  const [returnOpen, setReturnOpen] = useState(false)
  const [returnComment, setReturnComment] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const commentLen = returnComment.trim().length
  const returnValid = commentLen >= 10 && commentLen <= 500

  const ledgerTotal = useMemo(
    () => (c?.ledger ?? []).reduce((sum, e) => sum + e.points, 0),
    [c?.ledger],
  )

  const qualLedgerPoints = useMemo(() => {
    if (!c) return null
    const qual = c.ledger.filter(
      (e) => e.event_type === 'qualitative_success' || e.event_type === 'qualitative_failed',
    )
    if (qual.length === 0) return ledgerTotal
    return qual[qual.length - 1].points
  }, [c, ledgerTotal])

  async function afterAction() {
    await qc.invalidateQueries({ queryKey: ['pending-qualitative-list'] })
    await qc.invalidateQueries({ queryKey: ['pending-qualitative-count'] })
    await qc.invalidateQueries({ queryKey: ['owner-case-detail', caseId] })
    router.push('/dashboard/admins-review/pending')
  }

  async function closeQualitative(result: 'success' | 'failed') {
    setActionLoading(true)
    setActionError(null)
    try {
      await api.post(
        `/api/v1/dashboard/admins-review/cases/${caseId}/close-qualitative`,
        { result },
      )
      setConfirmAction(null)
      await afterAction()
    } catch (err: unknown) {
      setActionError(formatApiError(err))
    } finally {
      setActionLoading(false)
    }
  }

  async function returnForRevision() {
    if (!returnValid) return
    setActionLoading(true)
    setActionError(null)
    try {
      await api.post(
        `/api/v1/dashboard/admins-review/cases/${caseId}/return-for-revision`,
        { comment: returnComment.trim() },
      )
      setReturnOpen(false)
      await afterAction()
    } catch (err: unknown) {
      setActionError(formatApiError(err))
    } finally {
      setActionLoading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="p-6 max-w-3xl mx-auto space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    )
  }

  if (error || !c) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <Link
          href="/dashboard/admins-review"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-4"
        >
          <ArrowLeft className="h-4 w-4" /> К обзору
        </Link>
        <p className="text-sm text-red-400">Кейс не найден или недоступен</p>
      </div>
    )
  }

  const isQual = c.case_type === 'qualitative'
  const typeInline = isQual
    ? c.category ?? '—'
    : METRIC_LABELS[c.metric_type ?? ''] ?? c.metric_type ?? '—'
  const pct = !isQual ? pctChange(c.baseline_value, c.result_value) : null
  const sentLabel = c.sent_for_review_at
    ? formatSentForReviewDisplay(c.sent_for_review_at)
    : null

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5 pb-10">
      {/* Header */}
      <div>
        <Link
          href="/dashboard/admins-review"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-3"
        >
          <ArrowLeft className="h-4 w-4" /> К обзору
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-slate-100 truncate">
                {c.chatter_display_name || c.om_user_id}
              </h1>
              <span
                className={cn(
                  'text-[10px] font-semibold px-2 py-0.5 rounded-full ring-1',
                  isQual
                    ? 'bg-violet-500/15 text-violet-300 ring-violet-500/30'
                    : 'bg-slate-600/50 text-slate-300 ring-slate-500/40',
                )}
              >
                {CASE_TYPE_LABELS[c.case_type]}
              </span>
              <span className="text-sm text-slate-400">{typeInline}</span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{c.om_user_id}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            <span
              className={cn(
                'text-xs font-semibold px-2.5 py-1 rounded-full ring-1',
                stageBadgeClass(c.stage),
              )}
            >
              {STAGE_LABELS_OWNER[c.stage] ?? c.stage}
            </span>
            <Badge variant="secondary" className="text-[10px]">
              {PRIORITY_LABELS[c.priority] ?? c.priority}
            </Badge>
          </div>
        </div>
      </div>

      {/* Information */}
      <Section title="Информация">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div className="sm:col-span-2">
            <dt className="text-xs text-slate-500">Ведёт</dt>
            <dd className="mt-0.5 flex items-center gap-2 flex-wrap">
              <span className="text-slate-100">
                {c.admin.name || '—'} <span className="text-slate-500">#{c.admin.id}</span>
              </span>
              {c.admin.shift_name && (
                <Badge variant="secondary" className="text-[10px]">
                  {c.admin.shift_name}
                </Badge>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Открыт</dt>
            <dd className="text-slate-200 mt-0.5">{fmtRuDate(c.opened_at)}</dd>
          </div>
          {c.hold_days != null && (
            <div>
              <dt className="text-xs text-slate-500">HOLD</dt>
              <dd className="text-slate-200 mt-0.5">{c.hold_days} дней</dd>
            </div>
          )}
          {c.review_date && (
            <div>
              <dt className="text-xs text-slate-500">Ревью до</dt>
              <dd className="text-slate-200 mt-0.5">{fmtRuDate(c.review_date)}</dd>
            </div>
          )}
          {c.closed_at && (
            <div>
              <dt className="text-xs text-slate-500">Закрыт</dt>
              <dd className="text-slate-200 mt-0.5">{fmtRuDate(c.closed_at)}</dd>
            </div>
          )}
          {c.result && (
            <div>
              <dt className="text-xs text-slate-500">Результат</dt>
              <dd className="mt-0.5">
                <Badge variant={resultBadgeVariant(c.result)}>
                  {RESULT_LABELS[c.result] ?? c.result}
                </Badge>
              </dd>
            </div>
          )}
          {sentLabel && c.stage === 'awaiting_review' && (
            <div className="sm:col-span-2">
              <dt className="text-xs text-slate-500">На оценке</dt>
              <dd className="text-slate-400 mt-0.5 text-xs">Отправлено {sentLabel}</dd>
            </div>
          )}
        </dl>
      </Section>

      {/* Diagnosis */}
      <Section title="Диагноз и план">
        <div>
          <p className="text-xs text-slate-500 mb-1">Диагноз</p>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{c.diagnosis_text || '—'}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500 mb-1">План действий</p>
          <p className="text-sm text-slate-200 whitespace-pre-wrap">{c.action_plan || '—'}</p>
        </div>
      </Section>

      {/* Metrics (quantitative only) */}
      {!isQual && (
        <Section title="Метрики">
          <dl className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div>
              <dt className="text-xs text-slate-500">Baseline</dt>
              <dd className="text-slate-100 font-medium tabular-nums mt-0.5">
                {c.baseline_value != null ? c.baseline_value.toFixed(2) : '—'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Result</dt>
              <dd className="text-slate-100 font-medium tabular-nums mt-0.5">
                {c.result_value != null ? c.result_value.toFixed(2) : '—'}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Изменение</dt>
              <dd
                className={cn(
                  'font-medium tabular-nums mt-0.5',
                  pct == null
                    ? 'text-slate-500'
                    : pct.startsWith('+')
                      ? 'text-emerald-400'
                      : pct.startsWith('-')
                        ? 'text-red-400'
                        : 'text-slate-300',
                )}
              >
                {pct ?? '—'}
              </dd>
            </div>
          </dl>
        </Section>
      )}

      {/* Ledger */}
      <Section title="Ledger по этому кейсу">
        {c.ledger.length === 0 ? (
          <p className="text-sm text-slate-500">Нет событий</p>
        ) : (
          <>
            <div className="space-y-2">
              {c.ledger.map((e) => (
                <div
                  key={e.id}
                  className="flex items-start justify-between gap-3 py-2 border-b border-slate-700/30 last:border-0"
                >
                  <div className="min-w-0">
                    <p className="text-sm text-slate-200">{ledgerEventLabel(e.event_type)}</p>
                    {e.notes && (
                      <p className="text-xs text-slate-500 mt-0.5 truncate">{e.notes}</p>
                    )}
                    <p className="text-xs text-slate-600 mt-0.5">{formatLedgerDate(e.created_at)}</p>
                  </div>
                  <span
                    className={cn(
                      'text-sm font-medium tabular-nums shrink-0',
                      ledgerPointsClass(e.points),
                    )}
                  >
                    {e.points > 0 ? '+' : ''}
                    {e.points.toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-xs text-slate-500 pt-2 border-t border-slate-700/30">
              Итого по кейсу: {c.ledger.length}{' '}
              {c.ledger.length === 1 ? 'событие' : c.ledger.length < 5 ? 'события' : 'событий'},{' '}
              <span className={cn('font-medium', ledgerPointsClass(ledgerTotal))}>
                {ledgerTotal > 0 ? '+' : ''}
                {ledgerTotal.toFixed(1)} очков
              </span>
            </p>
          </>
        )}
      </Section>

      {/* Stage history */}
      <Section title="История стадий">
        {c.history.length === 0 ? (
          <p className="text-sm text-slate-500">Нет записей</p>
        ) : (
          <ol className="space-y-3">
            {c.history.map((h) => (
              <li key={h.id} className="flex gap-3 text-sm">
                <div className="w-2 h-2 rounded-full bg-amber-500/60 mt-1.5 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="text-slate-200">
                    {h.from_stage
                      ? `${STAGE_LABELS_OWNER[h.from_stage] ?? h.from_stage} → `
                      : 'Создан → '}
                    <span className="font-medium">
                      {STAGE_LABELS_OWNER[h.to_stage] ?? h.to_stage}
                    </span>
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {fmtRuDate(h.changed_at)} · {CHANGED_BY_LABEL[h.changed_by] ?? h.changed_by}
                  </p>
                  {h.notes && (
                    <p className="text-xs text-slate-400 mt-1 whitespace-pre-wrap">{h.notes}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Section>

      {/* Activities */}
      <CaseActivities
        caseId={caseId}
        currentAdminId={0}
        caseOwnerAdminId={c.admin.id}
        readOnly
        apiMode="owner"
      />

      {/* Evaluation (qualitative awaiting_review only) */}
      {isQual && c.stage === 'awaiting_review' && (
        <Section title="Оценка">
          {actionError && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <p className="text-xs text-red-400">{actionError}</p>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => setConfirmAction('success')}
              disabled={actionLoading}
              className="flex-1 min-w-[140px] bg-emerald-600 hover:bg-emerald-500"
            >
              <CheckCircle2 className="h-4 w-4 mr-1.5" />
              Сработало +5
            </Button>
            <Button
              onClick={() => setConfirmAction('failed')}
              disabled={actionLoading}
              variant="outline"
              className="flex-1 min-w-[140px] text-red-400 border-red-500/30 hover:bg-red-500/10"
            >
              <XCircle className="h-4 w-4 mr-1.5" />
              Не помогло -2
            </Button>
            <Button
              onClick={() => {
                setReturnOpen(true)
                setActionError(null)
              }}
              disabled={actionLoading}
              variant="outline"
              className="flex-1 min-w-[140px] text-slate-300"
            >
              <RotateCcw className="h-4 w-4 mr-1.5" />
              Вернуть на доработку
            </Button>
          </div>
        </Section>
      )}

      {/* Final status (closed qualitative) */}
      {isQual && c.stage === 'closed' && (
        <div
          className={cn(
            'rounded-xl border p-5 text-center',
            c.result === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/30'
              : 'bg-red-500/10 border-red-500/30',
          )}
        >
          <p
            className={cn(
              'text-lg font-bold',
              c.result === 'success' ? 'text-emerald-300' : 'text-red-300',
            )}
          >
            {c.result === 'success' ? '✓ Сработало (+5)' : '✗ Не помогло (-2)'}
          </p>
          {c.closed_at && (
            <p className="text-xs text-slate-500 mt-2">Закрыт {fmtRuDate(c.closed_at)}</p>
          )}
          {qualLedgerPoints != null && (
            <p className="text-xs text-slate-400 mt-1">
              Очки в ledger: {qualLedgerPoints > 0 ? '+' : ''}
              {qualLedgerPoints.toFixed(1)}
            </p>
          )}
        </div>
      )}

      {/* Confirm close */}
      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 max-w-sm w-full shadow-2xl">
            <p className="text-sm text-slate-200">Подтвердить?</p>
            <p className="text-xs text-slate-500 mt-1">
              {confirmAction === 'success'
                ? 'Кейс будет закрыт как успешный (+5 очков админу).'
                : 'Кейс будет закрыт без результата (-2 очка админу).'}
            </p>
            <div className="flex gap-2 mt-4 justify-end">
              <Button
                variant="outline"
                size="sm"
                disabled={actionLoading}
                onClick={() => setConfirmAction(null)}
              >
                Отмена
              </Button>
              <Button
                size="sm"
                disabled={actionLoading}
                className={
                  confirmAction === 'success'
                    ? 'bg-emerald-600 hover:bg-emerald-500'
                    : 'bg-red-700 hover:bg-red-600'
                }
                onClick={() => closeQualitative(confirmAction)}
              >
                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Подтвердить'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Return modal */}
      {returnOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          data-testid="return-modal"
        >
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 max-w-md w-full shadow-2xl">
            <h3 className="text-sm font-semibold text-slate-100">Вернуть на доработку</h3>
            <p className="text-xs text-slate-500 mt-1">
              Комментарий обязателен (10–500 символов). Админ увидит его в активностях.
            </p>
            <div className="relative mt-3">
              <textarea
                value={returnComment}
                onChange={(e) => setReturnComment(e.target.value)}
                rows={5}
                maxLength={500}
                placeholder="Что нужно доработать..."
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
              />
              <span className="absolute bottom-2 right-2 text-xs text-slate-500">
                {commentLen} / 500
              </span>
            </div>
            {actionError && <p className="text-xs text-red-400 mt-2">{actionError}</p>}
            <div className="flex gap-2 mt-4 justify-end">
              <Button
                variant="outline"
                size="sm"
                disabled={actionLoading}
                onClick={() => setReturnOpen(false)}
              >
                Отмена
              </Button>
              <Button
                size="sm"
                disabled={!returnValid || actionLoading}
                className="bg-amber-600 hover:bg-amber-500 disabled:opacity-50"
                onClick={returnForRevision}
              >
                {actionLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Отправить'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
