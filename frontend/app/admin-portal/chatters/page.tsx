'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Plus, X, Loader2, AlertCircle, Link2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import {
  mappingErrorMessage,
  useCreateChatterMapping,
} from '@/lib/hooks/useCreateChatterMapping'
import {
  type BaselineMetricType,
  useBaselinePreview,
} from '@/lib/hooks/useBaselinePreview'
import {
  BaselinePreviewV2Cards,
  BaselineV2Flags,
} from '@/components/admin-portal/MetricV2Block'
import { fmtMetricValue } from '@/lib/metricFormat'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Chatter {
  is_mapped: boolean
  om_user_id: string | null
  display_name: string
  month_open_rate: number | null
  month_rpc: number | null
  month_apv: number | null
  month_chats: number | null
  month_revenue: number | null
  revenue_month: number | null
  has_open_case: boolean
  open_case_by_me: boolean
}

type MetricType = 'ppv_open_rate' | 'rpc' | 'apv' | 'total_chats' | 'revenue'
type Priority   = 'high' | 'normal' | 'low'
type CaseType   = 'quantitative' | 'qualitative'

const METRIC_OPTIONS: { value: MetricType; label: string }[] = [
  { value: 'ppv_open_rate', label: 'PPV Open Rate (%)' },
  { value: 'rpc',           label: 'RPC (Revenue/Chat)' },
  { value: 'apv',           label: 'APV (Avg Purchase Value)' },
  { value: 'total_chats',   label: 'Total Chats' },
  { value: 'revenue',       label: 'Revenue' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function chatterLabel(c: Chatter): string {
  const name = c.display_name?.trim()
  return name || c.om_user_id || '—'
}

function fmtRevenue(c: Chatter): string {
  const v = c.month_revenue ?? c.revenue_month
  return v != null ? `$${v.toFixed(0)}` : '—'
}

function rowKey(c: Chatter): string {
  return c.is_mapped ? `m-${c.om_user_id}` : `o-${c.display_name}`
}

function fmtMetric(c: Chatter, metric: MetricType): string {
  if (metric === 'ppv_open_rate') return c.month_open_rate != null ? `${c.month_open_rate.toFixed(1)}%` : '—'
  if (metric === 'rpc')           return c.month_rpc        != null ? `$${c.month_rpc.toFixed(2)}`      : '—'
  if (metric === 'apv')           return c.month_apv        != null ? `$${c.month_apv.toFixed(2)}`      : '—'
  if (metric === 'total_chats')   return c.month_chats      != null ? String(c.month_chats)             : '—'
  if (metric === 'revenue')       return c.month_revenue    != null ? `$${c.month_revenue.toFixed(0)}`  : '—'
  return '—'
}

function fmtBaselineValue(metric: MetricType, v: number): string {
  if (metric === 'ppv_open_rate') return `${v.toFixed(1)}%`
  if (metric === 'total_chats')   return String(Math.round(v))
  if (metric === 'revenue')       return `$${v.toFixed(0)}`
  return `$${v.toFixed(2)}`
}

/** Day + month in Russian, e.g. "1 июля" */
function fmtDayMonth(isoDate: string): string {
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
  })
}

// ── Create Case Modal ─────────────────────────────────────────────────────────

interface ModalProps {
  chatter: Chatter
  onClose: () => void
  onSuccess: (caseId: number) => void
}

function CreateCaseModal({ chatter, onClose, onSuccess }: ModalProps) {
  const [caseType, setCaseType]   = useState<CaseType>('quantitative')
  const [metric, setMetric]       = useState<MetricType>('ppv_open_rate')
  const [category, setCategory]   = useState('')
  const [diagnosis, setDiagnosis] = useState('')
  const [plan, setPlan]           = useState('')
  const [priority, setPriority]   = useState<Priority>('normal')
  const [holdDays, setHoldDays]   = useState(21)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const isQuant = caseType === 'quantitative'
  const {
    data: baselinePreview,
    isLoading: baselineLoading,
    isFetching: baselineFetching,
  } = useBaselinePreview(
    chatter.om_user_id,
    metric as BaselineMetricType,
    isQuant,
  )

  const baselinePending = isQuant && (baselineLoading || baselineFetching)
  const baselineBlocked = isQuant && baselinePreview?.available === false

  const categoryOk = caseType === 'quantitative' || category.trim().length >= 1
  const canSubmit =
    diagnosis.trim().length > 0 &&
    holdDays >= 0 &&
    holdDays <= 60 &&
    categoryOk &&
    !loading &&
    !baselinePending &&
    !baselineBlocked

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!diagnosis.trim()) { setError('Укажите диагноз'); return }
    if (caseType === 'qualitative' && !category.trim()) {
      setError('Укажите категорию для качественного кейса')
      return
    }
    if (holdDays < 0 || holdDays > 60) { setError('HOLD-период: от 0 до 60 дней'); return }
    setError(null)
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        om_user_id:           chatter.om_user_id!,
        chatter_display_name: chatterLabel(chatter),
        case_type:            caseType,
        diagnosis_text:       diagnosis,
        action_plan:          plan,
        priority,
        hold_days:            holdDays,
      }
      if (caseType === 'quantitative') {
        body.metric_type = metric
      } else {
        body.category = category.trim()
      }
      const res = await api.post<{ id: number }>('/api/v1/admin-portal/cases', body)
      onSuccess(res.data.id)
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      const detail = resp?.data?.detail ?? 'Ошибка создания кейса'
      if (resp?.status === 409) setError('Уже открытый кейс по этому чаттеру')
      else if (resp?.status === 422) setError(typeof detail === 'string' ? detail : 'Ошибка валидации')
      else setError(typeof detail === 'string' ? detail : 'Ошибка создания кейса')
    } finally {
      setLoading(false)
    }
  }

  const currentVal = fmtMetric(chatter, metric)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Открыть кейс</h2>
            <p className="text-xs text-slate-400 mt-0.5">{chatterLabel(chatter)} · {chatter.om_user_id}</p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          {/* Case type toggle */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Тип кейса</label>
            <div className="flex gap-2">
              {([
                { value: 'quantitative' as CaseType, label: 'Количественный' },
                { value: 'qualitative' as CaseType, label: 'Качественный' },
              ]).map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setCaseType(opt.value)}
                  className={cn(
                    'flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    caseType === opt.value
                      ? opt.value === 'qualitative'
                        ? 'bg-violet-500/20 text-violet-300 ring-1 ring-violet-500/50'
                        : 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/50'
                      : 'bg-slate-800 text-slate-500 hover:text-slate-300',
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Metric (quantitative only) */}
          {caseType === 'quantitative' && (
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Метрика</label>
            <div className="flex gap-2 items-center">
              <select
                value={metric}
                onChange={e => setMetric(e.target.value as MetricType)}
                className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500"
              >
                {METRIC_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              {currentVal !== '—' && (
                <span
                  className="text-sm font-semibold text-amber-300 shrink-0 cursor-help"
                  title={
                    baselinePreview?.baseline_version === 'v2'
                      ? 'Месячная агрегация — основная цифра точки отсчёта'
                      : 'Месячная агрегация. Baseline берётся из дневных данных.'
                  }
                  data-testid="month-metric-badge"
                >
                  {baselinePreview?.baseline_version === 'v2' ? 'Точка отсчёта' : 'Мес'}:{' '}
                  {baselinePreview?.baseline_version === 'v2' && baselinePreview.month_current_value != null
                    ? fmtMetricValue(metric, baselinePreview.month_current_value)
                    : currentVal}
                </span>
              )}
            </div>
            <div className="mt-2 min-h-[1.25rem]" data-testid="baseline-preview">
              {baselinePending ? (
                <p className="text-xs text-slate-500">Проверяем данные…</p>
              ) : baselinePreview?.available && baselinePreview.baseline_version === 'v2' ? (
                <>
                  <BaselinePreviewV2Cards metric={metric} preview={baselinePreview} />
                  <BaselineV2Flags
                    isEarlyMonth={baselinePreview.is_early_month}
                    isNewChatter={baselinePreview.is_new_chatter}
                  />
                </>
              ) : baselinePreview?.available && baselinePreview.value != null && baselinePreview.snapshot_date ? (
                <p className="text-xs text-emerald-400">
                  Baseline: {fmtBaselineValue(metric, baselinePreview.value)} на{' '}
                  {fmtDayMonth(baselinePreview.snapshot_date)}
                  {baselinePreview.days_ago != null && ` (${baselinePreview.days_ago} дн. назад)`}
                </p>
              ) : baselinePreview && !baselinePreview.available ? (
                <p className="text-xs text-red-400">
                  Недостаточно данных за 30 дней. Кейс создать нельзя.
                </p>
              ) : null}
            </div>
          </div>
          )}

          {/* Category (qualitative only) */}
          {caseType === 'qualitative' && (
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Категория <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={category}
              onChange={e => setCategory(e.target.value)}
              maxLength={100}
              placeholder="мотивация / дисциплина / скрипты / ..."
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
            <p className="text-xs text-slate-500 mt-1.5">
              Опиши, что нельзя измерить метрикой
            </p>
          </div>
          )}

          {/* Diagnosis */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Диагноз <span className="text-red-400">*</span>
            </label>
            <textarea
              value={diagnosis}
              onChange={e => setDiagnosis(e.target.value)}
              rows={3}
              placeholder="Что видишь, почему это проблема..."
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
            />
          </div>

          {/* Action plan */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              План действий
            </label>
            <textarea
              value={plan}
              onChange={e => setPlan(e.target.value)}
              rows={3}
              placeholder="Что собираешься делать для исправления..."
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Приоритет</label>
            <div className="flex gap-2">
              {(['high', 'normal', 'low'] as Priority[]).map(p => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={cn(
                    'flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    priority === p
                      ? p === 'high'   ? 'bg-red-500/20 text-red-300 ring-1 ring-red-500/50'
                      : p === 'normal' ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/50'
                      :                  'bg-slate-600/40 text-slate-300 ring-1 ring-slate-500/50'
                      : 'bg-slate-800 text-slate-500 hover:text-slate-300',
                  )}
                >
                  {p === 'high' ? 'Высокий' : p === 'normal' ? 'Обычный' : 'Низкий'}
                </button>
              ))}
            </div>
          </div>

          {/* HOLD period */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              HOLD-период (дней) <span className="text-red-400">*</span>
            </label>
            <input
              type="number"
              min={0}
              max={60}
              value={holdDays}
              onChange={e => setHoldDays(Number(e.target.value))}
              required
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500"
            />
            <p className="text-xs text-slate-500 mt-1.5">
              0–60 дней. 0 — сразу на оценку (для теста).
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
              <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Submit */}
          <div className="flex gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose} className="flex-1" disabled={loading}>
              Отмена
            </Button>
            <Button type="submit" className="flex-1 bg-amber-600 hover:bg-amber-500" disabled={!canSubmit}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Создать кейс'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Mapping Modal ─────────────────────────────────────────────────────────────

interface MappingModalProps {
  initialDisplayName?: string
  onClose: () => void
  onSuccess: (displayName: string) => void
}

function MappingModal({ initialDisplayName = '', onClose, onSuccess }: MappingModalProps) {
  const createMapping = useCreateChatterMapping()
  const [omId, setOmId] = useState('')
  const [displayName, setDisplayName] = useState(initialDisplayName)
  const [inlineError, setInlineError] = useState<string | null>(null)

  const canSubmit =
    omId.trim().length >= 1 &&
    omId.trim().length <= 64 &&
    displayName.trim().length >= 2 &&
    !createMapping.isPending

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setInlineError(null)
    try {
      const result = await createMapping.mutateAsync({
        om_user_id: omId.trim(),
        display_name: displayName.trim(),
      })
      onSuccess(result.display_name)
    } catch (err: unknown) {
      const msg = mappingErrorMessage(err)
      if (msg) {
        setInlineError(msg)
      } else {
        setInlineError('Ошибка при сохранении маппинга')
      }
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div
        className="bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl w-full max-w-lg"
        data-testid="mapping-modal"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div>
            <h2 className="text-base font-semibold text-slate-100">
              Маппинг чаттера ↔ Onlymonster ID
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Введите Onlymonster user_id и имя чаттера как в транзакциях.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          {inlineError && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
              <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <p className="text-sm text-red-400">{inlineError}</p>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Onlymonster user_id (напр. 21036)
            </label>
            <input
              value={omId}
              onChange={e => setOmId(e.target.value)}
              maxLength={64}
              placeholder="21036"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Имя чаттера (напр. @nick)
            </label>
            <input
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              maxLength={100}
              placeholder="@nick"
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="flex gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose} className="flex-1" disabled={createMapping.isPending}>
              Отмена
            </Button>
            <Button
              type="submit"
              className="flex-1 bg-indigo-600 hover:bg-indigo-500"
              disabled={!canSubmit}
            >
              {createMapping.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Добавить'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Chatter table section ─────────────────────────────────────────────────────

function ChatterTableSection({
  title,
  rows,
  onOpenCase,
  onOpenMapping,
  emptyHint,
}: {
  title: string
  rows: Chatter[]
  onOpenCase: (c: Chatter) => void
  onOpenMapping: (c: Chatter) => void
  emptyHint?: string
}) {
  return (
    <div className="mb-8">
      <h2 className="text-sm font-semibold text-slate-300 mb-3">{title}</h2>
      {rows.length === 0 ? (
        emptyHint ? (
          <p className="text-sm text-slate-500 px-1">{emptyHint}</p>
        ) : null
      ) : (
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Чаттер</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Open Rate (мес)</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">RPC (мес)</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">APV (мес)</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Чатов (мес)</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Выручка (мес)</th>
              <th className="text-center px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Статус</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/30">
            {rows.map(c => (
              <tr key={rowKey(c)} className="hover:bg-slate-800/50 transition-colors">
                <td className="px-4 py-3">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="font-medium text-slate-200">{chatterLabel(c)}</p>
                      {!c.is_mapped && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-700/60 text-slate-400 border border-slate-600/50">
                          Требует маппинга
                        </span>
                      )}
                    </div>
                    {c.is_mapped && c.om_user_id && (
                      <p className="text-xs text-slate-500 mt-0.5">{c.om_user_id}</p>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-right text-slate-300">
                  {c.month_open_rate != null
                    ? `${c.month_open_rate.toFixed(1)}%`
                    : <span className="text-slate-600">—</span>}
                </td>
                <td className="px-4 py-3 text-right text-slate-300">
                  {c.month_rpc != null
                    ? `$${c.month_rpc.toFixed(2)}`
                    : <span className="text-slate-600">—</span>}
                </td>
                <td className="px-4 py-3 text-right text-slate-300">
                  {c.month_apv != null
                    ? `$${c.month_apv.toFixed(2)}`
                    : <span className="text-slate-600">—</span>}
                </td>
                <td className="px-4 py-3 text-right text-slate-300">
                  {c.month_chats != null && c.month_chats > 0
                    ? c.month_chats
                    : <span className="text-slate-600">—</span>}
                </td>
                <td className="px-4 py-3 text-right text-slate-300 tabular-nums">
                  {fmtRevenue(c) === '—'
                    ? <span className="text-slate-600">—</span>
                    : fmtRevenue(c)}
                </td>
                <td className="px-4 py-3 text-center">
                  {c.is_mapped && c.open_case_by_me ? (
                    <span className="text-xs bg-amber-500/15 text-amber-300 px-2 py-0.5 rounded-full">У меня</span>
                  ) : c.is_mapped && c.has_open_case ? (
                    <span className="text-xs bg-blue-500/15 text-blue-300 px-2 py-0.5 rounded-full">У другого</span>
                  ) : null}
                </td>
                <td className="px-4 py-3 text-right">
                  {c.is_mapped ? (
                    <button
                      onClick={() => !c.has_open_case && onOpenCase(c)}
                      disabled={c.has_open_case}
                      title={c.has_open_case ? 'Уже открыт кейс' : 'Открыть кейс'}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto',
                        c.has_open_case
                          ? 'bg-slate-700/40 text-slate-600 cursor-not-allowed'
                          : 'bg-amber-600/20 text-amber-300 hover:bg-amber-600/40',
                      )}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Кейс
                    </button>
                  ) : (
                    <button
                      onClick={() => onOpenMapping(c)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto bg-slate-700/50 text-slate-300 hover:bg-slate-600/60"
                    >
                      <Link2 className="h-3.5 w-3.5" />
                      Смаппить
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ChattersPage() {
  const router = useRouter()
  const qc = useQueryClient()
  const [modalChatter, setModalChatter] = useState<Chatter | null>(null)
  const [mappingChatter, setMappingChatter] = useState<Chatter | null>(null)
  const [mappingOpen, setMappingOpen] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const { data: chatters, isLoading } = useQuery<Chatter[]>({
    queryKey: ['admin-portal-chatters', showAll],
    queryFn: () =>
      api.get<Chatter[]>(`/api/v1/admin-portal/chatters?show_all=${showAll}`).then(r => r.data),
  })

  const mapped = chatters?.filter(c => c.is_mapped ?? !!c.om_user_id) ?? []
  const orphans = chatters?.filter(c => !(c.is_mapped ?? !!c.om_user_id)) ?? []

  function showToast(msg: string) {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  function handleSuccess(caseId: number) {
    setModalChatter(null)
    qc.invalidateQueries({ queryKey: ['admin-portal-chatters'] })
    qc.invalidateQueries({ queryKey: ['admin-portal-cases-active'] })
    router.push(`/admin-portal/cases/${caseId}`)
  }

  function openMapping(c?: Chatter) {
    setMappingChatter(c ?? null)
    setMappingOpen(true)
  }

  function handleMappingSuccess(displayName: string) {
    setMappingOpen(false)
    setMappingChatter(null)
    if (displayName) {
      showToast(`Маппинг сохранён. Чаттер ${displayName} добавлен в активные.`)
    } else {
      showToast('Ошибка при сохранении маппинга')
    }
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 shadow-2xl text-sm text-slate-100 max-w-xs">
          {toastMsg}
        </div>
      )}

      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Чаттеры</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Активные смаппированные чаттеры и сироты из транзакций (текущий месяц)
          </p>
        </div>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <span className="text-xs text-slate-400">Показать всех</span>
          <div
            onClick={() => setShowAll(v => !v)}
            className={cn(
              'relative w-9 h-5 rounded-full transition-colors',
              showAll ? 'bg-amber-500' : 'bg-slate-600',
            )}
          >
            <div className={cn(
              'absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform',
              showAll ? 'translate-x-4' : 'translate-x-0.5',
            )} />
          </div>
        </label>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map(i => <Skeleton key={i} className="h-14 w-full rounded-lg" />)}
        </div>
      ) : !chatters?.length ? (
        <div className="text-center py-12 text-slate-500">
          <p>
            {showAll
              ? 'Нет смаппированных чаттеров. Настройте маппинг Onlymonster.'
              : 'Нет активных чаттеров за текущий месяц.'}
          </p>
        </div>
      ) : (
        <>
          <ChatterTableSection
            title={`Активные чаттеры (${mapped.length})`}
            rows={mapped}
            onOpenCase={setModalChatter}
            onOpenMapping={openMapping}
          />
          {!showAll && (
            <ChatterTableSection
              title={`Требуют маппинга (${orphans.length})`}
              rows={orphans}
              onOpenCase={setModalChatter}
              onOpenMapping={openMapping}
            />
          )}
        </>
      )}

      {modalChatter && (
        <CreateCaseModal
          chatter={modalChatter}
          onClose={() => setModalChatter(null)}
          onSuccess={handleSuccess}
        />
      )}

      {mappingOpen && (
        <MappingModal
          initialDisplayName={mappingChatter?.display_name ?? ''}
          onClose={() => {
            setMappingOpen(false)
            setMappingChatter(null)
          }}
          onSuccess={handleMappingSuccess}
        />
      )}
    </div>
  )
}
