'use client'

import { useState, useMemo } from 'react'
import Link from 'next/link'
import { Header } from '@/components/layout/Header'
import {
  Brain,
  CheckCheck,
  AlertTriangle,
  XCircle,
  CheckCircle,
  Ban,
  ArrowRight,
  RefreshCw,
  CalendarClock,
  Archive,
  ListFilter,
  ScanSearch,
  Loader2,
  Bot,
  Trash2,
} from 'lucide-react'
import api from '@/lib/api'
import { useQueryClient } from '@tanstack/react-query'
import {
  useAgentEvents,
  usePatchAgentEvent,
  type AgentEvent,
} from '@/lib/hooks/useAgentEvents'

// ── Label helpers ──────────────────────────────────────────────────────────

const METRIC_LABELS: Record<string, string> = {
  open_rate:       'Open Rate',
  ppv_open_rate:   'Open Rate',
  rpc:             'RPC',
  revenue:         'Выручка',
  revenue_mom_pct: 'Падение выручки',
  chats_count:     'Чатов',
  top3_revenue_pct:'Концентрация топ-3',
}

const ENTITY_REF_LABELS: Record<string, string> = {
  systemic_low_open_rate:  'Системная проблема (OR)',
  systemic_low_rpc:        'Системная проблема (RPC)',
  concentration_risk:      'Концентрация моделей',
  watcher_overflow_summary:'Прочие наблюдения',
}

function fmtMetric(m?: string | null): string {
  if (!m) return ''
  return METRIC_LABELS[m] ?? m.replace(/_/g, ' ')
}

function fmtEntityRef(ref?: string | null): string {
  if (!ref) return ''
  return ENTITY_REF_LABELS[ref] ?? ref
}

// ── Status config ──────────────────────────────────────────────────────────

const STATUS_META: Record<
  string,
  { label: string; color: string; bg: string; border: string; icon: React.ElementType }
> = {
  proposed:       { label: 'Предложено',    color: 'text-blue-400',   bg: 'bg-blue-500/10',   border: 'border-blue-500/25',   icon: Brain },
  accepted:       { label: 'Принято',       color: 'text-indigo-400', bg: 'bg-indigo-500/10', border: 'border-indigo-500/25', icon: CheckCheck },
  in_progress:    { label: 'В работе',      color: 'text-amber-400',  bg: 'bg-amber-500/10',  border: 'border-amber-500/25',  icon: RefreshCw },
  review_due:     { label: 'На проверке',   color: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/25', icon: AlertTriangle },
  closed_success: { label: 'Выполнено',     color: 'text-emerald-400',bg: 'bg-emerald-500/10',border: 'border-emerald-500/25',icon: CheckCircle },
  closed_failed:  { label: 'Не выполнено',  color: 'text-red-400',    bg: 'bg-red-500/10',    border: 'border-red-500/25',    icon: XCircle },
  dismissed:      { label: 'Отклонено',     color: 'text-slate-500',  bg: 'bg-slate-700/30',  border: 'border-slate-600/20',  icon: Ban },
}

const PRIORITY_META: Record<string, { label: string; dot: string }> = {
  high:   { label: 'Высокий', dot: 'bg-red-400' },
  normal: { label: 'Средний', dot: 'bg-amber-400' },
  low:    { label: 'Низкий',  dot: 'bg-slate-500' },
}

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.dismissed
  const Icon = m.icon
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-md border ${m.color} ${m.bg} ${m.border}`}
    >
      <Icon className="h-3 w-3" />
      {m.label}
    </span>
  )
}

function PriorityDot({ priority }: { priority: string }) {
  const m = PRIORITY_META[priority] ?? PRIORITY_META.normal
  return (
    <span title={m.label} className={`inline-block h-2 w-2 rounded-full ${m.dot} shrink-0`} />
  )
}

function fmtDate(d?: string | null) {
  if (!d) return null
  const [y, m, day] = d.split('T')[0].split('-')
  return `${day}.${m}.${y}`
}

function isReviewSoon(ev: AgentEvent) {
  if (!ev.review_date) return false
  const diff = (new Date(ev.review_date).getTime() - Date.now()) / 86_400_000
  return diff <= 3 && diff >= 0
}

// ── Event card ─────────────────────────────────────────────────────────────

function SourceBadge({ source }: { source: string }) {
  if (source !== 'watcher') return null
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-md bg-violet-500/10 text-violet-400 border border-violet-500/25">
      <Bot className="h-3 w-3" />
      Найдено мозгом
    </span>
  )
}

function BeforeAfterBlock({ ev }: { ev: AgentEvent }) {
  const before = ev.trigger_value_before
  const after  = ev.outcome_value_after
  if (before == null && after == null) return null

  const diff     = before != null && after != null ? after - before : null
  const improved = diff != null && diff > 0
  const worsened = diff != null && diff < 0

  return (
    <div className="mt-2 pl-11">
      <div className="inline-flex items-center gap-2 bg-slate-900/40 border border-slate-700/40 rounded-lg px-3 py-1.5 flex-wrap">
        {ev.trigger_metric && (
          <span className="text-xs text-slate-500 font-medium">{fmtMetric(ev.trigger_metric)}</span>
        )}
        {before != null && (
          <span className="text-xs font-mono text-slate-400 tabular-nums">{before.toFixed(2)}</span>
        )}
        {before != null && after != null && (
          <ArrowRight className="h-3 w-3 text-slate-600 shrink-0" />
        )}
        {after != null && (
          <span className={`text-xs font-mono font-semibold tabular-nums ${
            improved ? 'text-emerald-400' : worsened ? 'text-red-400' : 'text-slate-300'
          }`}>
            {after.toFixed(2)}
          </span>
        )}
        {diff != null && (
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            improved
              ? 'bg-emerald-500/10 text-emerald-400'
              : worsened
              ? 'bg-red-500/10 text-red-400'
              : 'bg-slate-700/40 text-slate-400'
          }`}>
            {improved ? '↑ улучшилось' : worsened ? '↓ ухудшилось' : '— без изменений'}
          </span>
        )}
      </div>
    </div>
  )
}

function EventCard({ ev }: { ev: AgentEvent }) {
  const patch = usePatchAgentEvent()
  const [optimisticStatus, setOptimisticStatus] = useState<string | null>(null)
  const status = optimisticStatus ?? ev.status

  async function doStatus(s: string, extra?: Record<string, unknown>) {
    setOptimisticStatus(s)
    try {
      await patch.mutateAsync({ id: ev.id, payload: { status: s, ...extra } })
    } catch {
      setOptimisticStatus(null)
    }
  }

  const m = STATUS_META[status] ?? STATUS_META.dismissed
  const Icon = m.icon
  const isOpen = !['closed_success', 'closed_failed', 'dismissed'].includes(status)

  return (
    <div
      className={`rounded-xl border bg-slate-800/50 p-4 transition-opacity ${isOpen ? '' : 'opacity-70'}`}
      style={{ borderColor: 'rgba(100,116,139,0.3)' }}
    >
      {/* Header row */}
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${m.bg} ${m.border} border`}>
          <Icon className={`h-4 w-4 ${m.color}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <PriorityDot priority={ev.priority} />
            <p className="text-sm font-semibold text-slate-100 leading-snug">{ev.title}</p>
          </div>
          {ev.description && (
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">{ev.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
          <SourceBadge source={ev.source} />
          <StatusBadge status={status} />
        </div>
      </div>

      {/* Meta tags */}
      <div className="flex flex-wrap gap-2 mt-3 pl-11">
        {ev.entity_ref && ev.entity_type !== 'agency' && (
          <span className="text-xs bg-slate-700/60 text-slate-300 border border-slate-600/30 rounded-md px-2 py-0.5">
            {fmtEntityRef(ev.entity_ref)}
          </span>
        )}
        {ev.entity_ref && ev.entity_type === 'agency' && ENTITY_REF_LABELS[ev.entity_ref] && (
          <span className="text-xs bg-slate-800/60 text-slate-400 border border-slate-600/20 rounded-md px-2 py-0.5 italic">
            {ENTITY_REF_LABELS[ev.entity_ref]}
          </span>
        )}
        {ev.trigger_metric && (
          <span className="text-xs bg-slate-700/40 text-slate-400 rounded-md px-2 py-0.5">
            {fmtMetric(ev.trigger_metric)}
            {ev.trigger_value_before != null ? `: ${Number(ev.trigger_value_before).toFixed(1)}` : ''}
          </span>
        )}
        {ev.review_date && (
          <span className={`text-xs rounded-md px-2 py-0.5 flex items-center gap-1 ${
            isReviewSoon(ev) ? 'bg-orange-500/15 text-orange-400' : 'bg-slate-700/40 text-slate-400'
          }`}>
            <CalendarClock className="h-3 w-3" />
            Проверить {fmtDate(ev.review_date)}
          </span>
        )}
        <span className="text-xs text-slate-600">{fmtDate(ev.created_at)}</span>
      </div>

      {/* Before → After comparison (review_due / archive) */}
      {(status === 'review_due' || status === 'closed_success' || status === 'closed_failed') && (
        <BeforeAfterBlock ev={ev} />
      )}

      {/* Outcome text */}
      {ev.outcome && (
        <div className="mt-2 pl-11">
          <p className="text-xs text-slate-400">
            <span className="text-slate-500">Итог: </span>{ev.outcome}
          </p>
        </div>
      )}

      {/* Action buttons */}
      {isOpen && (
        <div className="flex gap-2 mt-3 pl-11 flex-wrap">
          {status === 'proposed' && (
            <>
              <button onClick={() => doStatus('accepted')} disabled={patch.isPending}
                className="text-xs px-2.5 py-1 rounded-lg bg-indigo-500/15 text-indigo-300 border border-indigo-500/25 hover:bg-indigo-500/25 transition-colors disabled:opacity-50">
                Принять
              </button>
              <button onClick={() => doStatus('dismissed')} disabled={patch.isPending}
                className="text-xs px-2.5 py-1 rounded-lg bg-slate-700/40 text-slate-400 border border-slate-600/30 hover:bg-slate-700 transition-colors disabled:opacity-50">
                Отклонить
              </button>
            </>
          )}
          {status === 'accepted' && (
            <button onClick={() => doStatus('in_progress')} disabled={patch.isPending}
              className="text-xs px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/25 hover:bg-amber-500/25 transition-colors disabled:opacity-50">
              Взять в работу
            </button>
          )}
          {status === 'in_progress' && (
            <button onClick={() => doStatus('review_due')} disabled={patch.isPending}
              className="text-xs px-2.5 py-1 rounded-lg bg-orange-500/15 text-orange-400 border border-orange-500/25 hover:bg-orange-500/25 transition-colors disabled:opacity-50">
              На проверку
            </button>
          )}
          {(status === 'in_progress' || status === 'review_due') && (
            <>
              <button onClick={() => doStatus('closed_success', { outcome: 'Сработало — выполнено' })}
                disabled={patch.isPending}
                className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 hover:bg-emerald-500/25 transition-colors disabled:opacity-50">
                ✓ Сработало
              </button>
              <button onClick={() => doStatus('closed_failed', { outcome: 'Не помогло' })}
                disabled={patch.isPending}
                className="text-xs px-2.5 py-1 rounded-lg bg-red-500/15 text-red-400 border border-red-500/25 hover:bg-red-500/25 transition-colors disabled:opacity-50">
                ✕ Не помогло
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Scan-now button ────────────────────────────────────────────────────────

interface ScanResult {
  level_a: number
  level_b: number
  total: number
  errors?: string[]
}

function ActionButtons() {
  const qc = useQueryClient()
  const [scanning, setScanning]           = useState(false)
  const [reviewing, setReviewing]         = useState(false)
  const [dismissing, setDismissing]       = useState(false)
  const [scanResult, setScanResult]       = useState<ScanResult | null>(null)
  const [reviewResult, setReviewResult]   = useState<{ checked: number; updated: number } | null>(null)
  const [dismissResult, setDismissResult] = useState<{ dismissed: number } | null>(null)
  const [scanError, setScanError]         = useState<string | null>(null)
  const [reviewError, setReviewError]     = useState(false)
  const [confirmDismiss, setConfirmDismiss] = useState(false)

  async function handleScan() {
    setScanning(true)
    setScanResult(null)
    setScanError(null)
    try {
      const res = await api.post<ScanResult>('/api/v1/agent-events/scan-now')
      setScanResult(res.data)
      qc.invalidateQueries({ queryKey: ['agent-events'] })
      qc.invalidateQueries({ queryKey: ['agent-events-insights'] })
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setScanError(msg || 'Ошибка скана')
    } finally {
      setScanning(false)
    }
  }

  async function handleReview() {
    setReviewing(true)
    setReviewResult(null)
    setReviewError(false)
    try {
      const res = await api.post<{ checked: number; updated: number }>(
        '/api/v1/agent-events/review-now'
      )
      setReviewResult(res.data)
      qc.invalidateQueries({ queryKey: ['agent-events'] })
    } catch {
      setReviewError(true)
    } finally {
      setReviewing(false)
    }
  }

  async function handleDismissWatcher() {
    if (!confirmDismiss) {
      setConfirmDismiss(true)
      setTimeout(() => setConfirmDismiss(false), 4000) // auto-cancel after 4s
      return
    }
    setDismissing(true)
    setDismissResult(null)
    setConfirmDismiss(false)
    try {
      const res = await api.post<{ dismissed: number }>('/api/v1/agent-events/dismiss-watcher')
      setDismissResult(res.data)
      qc.invalidateQueries({ queryKey: ['agent-events'] })
      qc.invalidateQueries({ queryKey: ['agent-events-insights'] })
    } catch {
      // silently ignore
    } finally {
      setDismissing(false)
    }
  }

  const busy = scanning || reviewing || dismissing

  return (
    <div className="flex items-center gap-2 flex-wrap justify-end">
      {/* Inline results */}
      {!scanning && scanResult && (
        <span
          className={`text-xs max-w-xs truncate ${
            (scanResult.errors?.length ?? 0) > 0
              ? 'text-amber-400'
              : scanResult.total > 0
              ? 'text-violet-400'
              : 'text-slate-500'
          }`}
          title={scanResult.errors?.join('; ')}
        >
          {scanResult.total === 0 && !(scanResult.errors?.length)
            ? '✓ Новых проблем нет'
            : scanResult.total === 0 && (scanResult.errors?.length ?? 0) > 0
            ? `⚠ Создано: 0, ошибок: ${scanResult.errors!.length}`
            : `Создано: ${scanResult.total} (А:${scanResult.level_a} Б:${scanResult.level_b})${
                (scanResult.errors?.length ?? 0) > 0 ? ` ⚠ ${scanResult.errors!.length} ош.` : ''
              }`}
        </span>
      )}
      {!scanning && scanError && <span className="text-xs text-red-400">{scanError}</span>}
      {!reviewing && reviewResult && (
        <span className="text-xs text-slate-500">
          {reviewResult.updated === 0
            ? '✓ Проверено: изменений нет'
            : `Проверено ${reviewResult.checked}, обновлено ${reviewResult.updated}`}
        </span>
      )}
      {!reviewing && reviewError && <span className="text-xs text-red-400">Ошибка проверки</span>}
      {!dismissing && dismissResult && (
        <span className="text-xs text-slate-500">
          Отклонено {dismissResult.dismissed} watcher-событий
        </span>
      )}

      {/* Bulk-dismiss watcher events (two-tap confirm) */}
      <button
        onClick={handleDismissWatcher}
        disabled={busy}
        title={
          confirmDismiss
            ? 'Нажми ещё раз для подтверждения — отклонит ВСЕ открытые watcher-события'
            : 'Отклонить все открытые события от watcher'
        }
        className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors disabled:opacity-50 ${
          confirmDismiss
            ? 'border-red-500/60 bg-red-900/30 text-red-300 hover:bg-red-900/50'
            : 'border-slate-600/50 bg-slate-800/60 hover:bg-slate-700 text-slate-400'
        }`}
      >
        {dismissing
          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
          : <Trash2 className="h-3.5 w-3.5" />}
        {dismissing
          ? 'Удаляю…'
          : confirmDismiss
          ? 'Подтвердить очистку'
          : 'Очистить watcher'}
      </button>

      {/* Review-now */}
      <button
        onClick={handleReview}
        disabled={busy}
        title="Проверить события с истёкшей датой (watcher_review)"
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-slate-600/50 bg-slate-800/60 hover:bg-slate-700 text-slate-300 disabled:opacity-50 transition-colors"
      >
        {reviewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
        {reviewing ? 'Проверяю…' : 'Проверить события'}
      </button>

      {/* Scan-now (primary) */}
      <button
        onClick={handleScan}
        disabled={busy}
        className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-60 text-white shadow-sm transition-colors"
      >
        {scanning ? <Loader2 className="h-4 w-4 animate-spin shrink-0" /> : <ScanSearch className="h-4 w-4 shrink-0" />}
        {scanning ? 'Осматриваю…' : 'Осмотреть агентство'}
      </button>

      {(scanning || reviewing) && (
        <span className="text-xs text-slate-500 animate-pulse">~10–20 сек…</span>
      )}
    </div>
  )
}

// ── Feed view ──────────────────────────────────────────────────────────────

function FeedView() {
  const { data: events, isLoading } = useAgentEvents()

  const groups = useMemo(() => {
    if (!events) return { proposed: [], active: [], review: [] }
    return {
      proposed: events.filter((e) => e.status === 'proposed'),
      active:   events.filter((e) => ['accepted', 'in_progress'].includes(e.status)),
      review:   events.filter((e) => e.status === 'review_due' || isReviewSoon(e)),
    }
  }, [events])

  if (isLoading) return <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-slate-800/50 animate-pulse" />)}</div>

  const total = (events?.length ?? 0)
  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 flex items-center justify-center mb-3">
          <CheckCircle className="h-6 w-6 text-emerald-400" />
        </div>
        <p className="text-slate-300 font-medium">Всё под контролем</p>
        <p className="text-slate-500 text-sm mt-1">Открытых событий нет</p>
      </div>
    )
  }

  function Section({
    title,
    items,
    emptyText,
  }: { title: string; items: AgentEvent[]; emptyText?: string }) {
    return (
      <div>
        <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
          {title}
          {items.length > 0 && (
            <span className="ml-2 text-slate-500 normal-case font-normal">({items.length})</span>
          )}
        </h3>
        {items.length === 0 ? (
          emptyText ? <p className="text-sm text-slate-600 pl-1">{emptyText}</p> : null
        ) : (
          <div className="space-y-3">
            {items.map((ev) => <EventCard key={ev.id} ev={ev} />)}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {groups.proposed.length > 0 && (
        <Section title="Ждут тебя" items={groups.proposed} />
      )}
      {groups.review.length > 0 && (
        <Section title="На проверке" items={groups.review} />
      )}
      <Section title="В работе" items={groups.active} emptyText="Нет активных задач" />
    </div>
  )
}

// ── Calendar view ──────────────────────────────────────────────────────────

function CalendarView() {
  const { data: events, isLoading } = useAgentEvents()

  const grouped = useMemo(() => {
    if (!events) return []
    const byDate: Record<string, AgentEvent[]> = {}
    for (const ev of events) {
      const d = ev.review_date ?? ev.created_at?.split('T')[0] ?? 'unknown'
      const key = d.split('T')[0]
      if (!byDate[key]) byDate[key] = []
      byDate[key].push(ev)
    }
    return Object.entries(byDate).sort(([a], [b]) => a.localeCompare(b))
  }, [events])

  if (isLoading) return <div className="h-40 rounded-xl bg-slate-800/50 animate-pulse" />

  if (grouped.length === 0) {
    return (
      <p className="text-slate-500 text-sm text-center py-12">
        Нет событий с датой проверки
      </p>
    )
  }

  return (
    <div className="space-y-6">
      {grouped.map(([date, evs]) => {
        const d = new Date(date)
        const isPast = d < new Date()
        return (
          <div key={date}>
            <div className="flex items-center gap-3 mb-3">
              <div
                className={`w-10 h-10 rounded-xl flex flex-col items-center justify-center text-xs font-bold shrink-0 ${
                  isPast ? 'bg-red-500/15 text-red-400' : 'bg-indigo-500/15 text-indigo-300'
                }`}
              >
                <span className="text-[10px] font-normal opacity-70">
                  {d.toLocaleString('ru', { month: 'short' }).toUpperCase()}
                </span>
                <span className="text-base leading-none">{d.getDate()}</span>
              </div>
              <p className="text-sm font-medium text-slate-300">
                {d.toLocaleDateString('ru', { weekday: 'long', day: 'numeric', month: 'long' })}
                {isPast && (
                  <span className="ml-2 text-xs text-red-400">просрочено</span>
                )}
              </p>
            </div>
            <div className="ml-13 space-y-3 pl-0">
              {evs.map((ev) => <EventCard key={ev.id} ev={ev} />)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Archive view ───────────────────────────────────────────────────────────

function ArchiveView() {
  const { data: events, isLoading } = useAgentEvents({ include_closed: true })

  const archived = useMemo(
    () => events?.filter((e) => ['closed_success', 'closed_failed', 'dismissed'].includes(e.status)) ?? [],
    [events],
  )

  if (isLoading) return <div className="h-40 rounded-xl bg-slate-800/50 animate-pulse" />

  if (archived.length === 0) {
    return (
      <p className="text-slate-500 text-sm text-center py-12">
        Архив пуст — закрытые события появятся здесь
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {archived.map((ev) => <EventCard key={ev.id} ev={ev} />)}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

type TabId = 'feed' | 'calendar' | 'archive'

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: 'feed',     label: 'Лента',     icon: ListFilter },
  { id: 'calendar', label: 'Календарь', icon: CalendarClock },
  { id: 'archive',  label: 'Архив',     icon: Archive },
]

export default function AgentEventsPage() {
  const [tab, setTab] = useState<TabId>('feed')

  return (
    <div className="flex flex-col h-full">
      <Header title="События мозга" />

      {/* Sub-nav */}
      <div className="flex gap-1 px-6 pt-3 pb-0 border-b border-slate-700/50">
        <Link
          href="/dashboard/ai"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          Чат
        </Link>
        <span className="px-3 py-1.5 text-sm font-medium text-indigo-300 border-b-2 border-indigo-400 -mb-px">
          События
        </span>
        <Link
          href="/dashboard/ai/profile"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          Настройки
        </Link>
      </div>

      {/* Sticky toolbar: tabs (left) + action buttons (right) */}
      <div className="sticky top-0 z-20 flex items-center justify-between gap-2 px-6 py-3 bg-slate-900 border-b border-slate-700/50">
        <div className="flex gap-1">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                tab === id
                  ? 'bg-indigo-500/15 text-indigo-300 border border-indigo-500/25'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
        <ActionButtons />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {tab === 'feed'     && <FeedView />}
        {tab === 'calendar' && <CalendarView />}
        {tab === 'archive'  && <ArchiveView />}
      </div>
    </div>
  )
}
