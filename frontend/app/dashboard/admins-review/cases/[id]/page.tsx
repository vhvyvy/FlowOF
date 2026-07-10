'use client'

import { useState } from 'react'
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
import { Skeleton } from '@/components/ui/skeleton'
import CaseActivities from '@/components/admin-portal/CaseActivities'
import api, { formatApiError } from '@/lib/api'
import { useOwnerQualitativeCase } from '@/lib/hooks/useOwnerQualitativeCase'
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

export default function OwnerQualitativeCasePage() {
  const params = useParams()
  const router = useRouter()
  const qc = useQueryClient()
  const caseId = Number(params.id)

  const { data: c, isLoading, error } = useOwnerQualitativeCase(caseId)

  const [confirmAction, setConfirmAction] = useState<'success' | 'failed' | null>(null)
  const [returnOpen, setReturnOpen] = useState(false)
  const [returnComment, setReturnComment] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const commentLen = returnComment.trim().length
  const returnValid = commentLen >= 10 && commentLen <= 500

  async function afterAction() {
    await qc.invalidateQueries({ queryKey: ['pending-qualitative-list'] })
    await qc.invalidateQueries({ queryKey: ['pending-qualitative-count'] })
    await qc.invalidateQueries({ queryKey: ['owner-qualitative-case', caseId] })
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
          href="/dashboard/admins-review/pending"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-4"
        >
          <ArrowLeft className="h-4 w-4" /> К списку
        </Link>
        <p className="text-sm text-red-400">Кейс не найден или недоступен</p>
      </div>
    )
  }

  const sentLabel = c.sent_for_review_at
    ? formatSentForReviewDisplay(c.sent_for_review_at)
    : null

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5 pb-10">
      {/* Header */}
      <div>
        <Link
          href="/dashboard/admins-review/pending"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200 mb-3"
        >
          <ArrowLeft className="h-4 w-4" /> К списку
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-slate-100">
              {STAGE_LABELS_OWNER[c.stage] ?? c.stage}
            </h1>
            {sentLabel && c.stage === 'awaiting_review' && (
              <p className="text-sm text-slate-400 mt-0.5">Отправлено {sentLabel}</p>
            )}
            {c.closed_at && c.stage === 'closed' && (
              <p className="text-sm text-slate-400 mt-0.5">Закрыт {fmtRuDate(c.closed_at)}</p>
            )}
          </div>
          <span
            className={cn(
              'text-xs font-semibold px-2.5 py-1 rounded-full shrink-0',
              c.stage === 'awaiting_review'
                ? 'bg-violet-500/15 text-violet-300'
                : c.stage === 'closed'
                  ? 'bg-green-500/15 text-green-300'
                  : 'bg-slate-700 text-slate-300',
            )}
          >
            {STAGE_LABELS_OWNER[c.stage] ?? c.stage}
          </span>
        </div>
      </div>

      {/* Case info */}
      <Section title="Кейс">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-slate-500">Чаттер</dt>
            <dd className="text-slate-100 font-medium mt-0.5">{c.chatter_display_name}</dd>
            <dd className="text-xs text-slate-500">{c.om_user_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Категория</dt>
            <dd className="mt-0.5">
              <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-300">
                {c.category}
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Приоритет</dt>
            <dd className="text-slate-200 mt-0.5">{PRIORITY_LABELS[c.priority] ?? c.priority}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">HOLD-период</dt>
            <dd className="text-slate-200 mt-0.5">
              {fmtRuDate(c.hold_start_date)} → {fmtRuDate(c.hold_end_date)}
            </dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-xs text-slate-500">Отправил</dt>
            <dd className="text-slate-200 mt-0.5">
              {c.admin.name || 'Администратор'}
              {sentLabel && (
                <span className="text-slate-500"> · {sentLabel}</span>
              )}
            </dd>
          </div>
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

      {/* History timeline */}
      <Section title="История переходов">
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

      {/* Activities read-only */}
      <CaseActivities
        caseId={caseId}
        currentAdminId={0}
        caseOwnerAdminId={c.admin.id}
        readOnly
        apiMode="owner"
      />

      {/* Evaluation */}
      {c.stage === 'awaiting_review' && (
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

      {/* Result (closed) */}
      {c.stage === 'closed' && (
        <Section title="Результат">
          <p
            className={cn(
              'text-sm font-semibold',
              c.result === 'success' ? 'text-emerald-300' : 'text-red-300',
            )}
          >
            {c.result === 'success' ? 'Сработало (+5)' : 'Не помогло (-2)'}
          </p>
          {c.ledger_points != null && (
            <p className="text-xs text-slate-500">
              Очки в ledger: {c.ledger_points > 0 ? '+' : ''}
              {c.ledger_points}
            </p>
          )}
          {c.closed_at && (
            <p className="text-xs text-slate-500">Закрыт {fmtRuDate(c.closed_at)}</p>
          )}
        </Section>
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
            {actionError && (
              <p className="text-xs text-red-400 mt-2">{actionError}</p>
            )}
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
