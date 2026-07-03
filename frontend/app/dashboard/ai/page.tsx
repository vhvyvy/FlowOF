'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Header } from '@/components/layout/Header'
import { Button } from '@/components/ui/button'
import {
  Sparkles,
  Loader2,
  Send,
  X,
  Plus,
  Check,
  Brain,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import api from '@/lib/api'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatMonth } from '@/lib/utils'
import { useCreateAgentEvent } from '@/lib/hooks/useAgentEvents'
import type { ProposedEvent } from '@/lib/hooks/useAgentEvents'

// ── Shared label helpers (reused in proposed-event cards) ──────────────────

const METRIC_LABELS: Record<string, string> = {
  open_rate:      'Open Rate',
  ppv_open_rate:  'Open Rate',
  rpc:            'RPC',
  revenue:        'Выручка',
  revenue_mom_pct:'Падение выручки',
  chats_count:    'Чатов',
  top3_revenue_pct:'Концентрация топ-3',
}
export function fmtMetric(m?: string | null): string {
  if (!m) return ''
  return METRIC_LABELS[m] ?? m.replace(/_/g, ' ')
}

const ENTITY_REF_LABELS: Record<string, string> = {
  systemic_low_open_rate:  'Системная проблема (OR)',
  systemic_low_rpc:        'Системная проблема (RPC)',
  concentration_risk:      'Концентрация моделей',
  watcher_overflow_summary:'Прочие наблюдения',
}
export function fmtEntityRef(ref?: string | null): string {
  if (!ref) return ''
  return ENTITY_REF_LABELS[ref] ?? ref
}

// ── Markdown renderer — dark-theme, GFM tables ─────────────────────────────

const MD_COMPONENTS: Components = {
  // Wrap tables for horizontal scroll
  table: ({ children }) => (
    <div className="overflow-x-auto my-3 rounded-lg border border-slate-600/40">
      <table className="w-full border-collapse text-sm">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-slate-700/60">{children}</thead>
  ),
  tbody: ({ children }) => (
    <tbody>{children}</tbody>
  ),
  tr: ({ children }) => (
    <tr className="border-b border-slate-700/40 even:bg-slate-800/30 hover:bg-slate-700/20 transition-colors">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2 text-left text-xs font-semibold text-slate-200 border-r border-slate-600/30 last:border-r-0 whitespace-nowrap">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2 text-sm text-slate-300 border-r border-slate-700/30 last:border-r-0 tabular-nums">
      {children}
    </td>
  ),
  // Headings — moderate size, no giant H1
  h1: ({ children }) => (
    <h1 className="text-base font-bold text-slate-100 mt-4 mb-2 pb-1 border-b border-slate-700/50">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-sm font-bold text-slate-100 mt-4 mb-2">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-semibold text-slate-200 mt-3 mb-1">{children}</h3>
  ),
  // Lists
  ul: ({ children }) => (
    <ul className="list-disc list-outside space-y-0.5 text-slate-300 my-2 pl-5">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal list-outside space-y-0.5 text-slate-300 my-2 pl-5">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-sm leading-relaxed">{children}</li>
  ),
  // Inline
  strong: ({ children }) => (
    <strong className="font-semibold text-slate-100">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-slate-300">{children}</em>
  ),
  code: ({ children, className }) => {
    const isBlock = className?.startsWith('language-')
    return isBlock ? (
      <code className={`block bg-slate-900/60 text-emerald-300 px-3 py-2 rounded-md text-xs font-mono my-2 overflow-x-auto ${className ?? ''}`}>
        {children}
      </code>
    ) : (
      <code className="bg-slate-700/60 text-indigo-300 px-1.5 py-0.5 rounded text-xs font-mono">
        {children}
      </code>
    )
  },
  p: ({ children }) => (
    <p className="leading-relaxed text-slate-200 my-1.5 text-sm">{children}</p>
  ),
  hr: () => <hr className="my-3 border-slate-700/60" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-indigo-500/40 pl-3 text-slate-400 my-2 italic">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a href={href} className="text-indigo-400 hover:text-indigo-300 underline underline-offset-2" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
}

function MarkdownContent({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
      {text}
    </ReactMarkdown>
  )
}

const QUICK_PROMPTS = [
  'Сделай анализ выручки за этот месяц',
  'Кто из чаттеров показал лучший результат?',
  'Где главные точки роста?',
  'Сравни расходы с прошлым месяцем',
]

interface Message {
  role: 'user' | 'assistant'
  content: string
  proposedEvents?: ProposedEvent[]
}

// ── Status helpers ─────────────────────────────────────────────────────────

function priorityBadge(p?: string) {
  if (p === 'high') return 'bg-red-500/15 text-red-400 border-red-500/30'
  if (p === 'low')  return 'bg-slate-700/60 text-slate-400 border-slate-600/30'
  return 'bg-amber-500/15 text-amber-400 border-amber-500/30'
}

function priorityLabel(p?: string) {
  if (p === 'high') return 'Высокий'
  if (p === 'low')  return 'Низкий'
  return 'Средний'
}

// ── Proposed event card ────────────────────────────────────────────────────

function ProposedEventCard({
  ev,
  onAccept,
  onDismiss,
}: {
  ev: ProposedEvent
  onAccept: () => void
  onDismiss: () => void
}) {
  const create = useCreateAgentEvent()
  const [done, setDone] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  async function handleAccept() {
    try {
      await create.mutateAsync({
        title: ev.title,
        description: ev.description ?? undefined,
        entity_type: ev.entity_type ?? undefined,
        entity_ref: ev.entity_ref ?? undefined,
        trigger_metric: ev.trigger_metric ?? undefined,
        trigger_value_before: ev.trigger_value_before ?? undefined,
        review_in_days: ev.suggested_review_days ?? undefined,
        source: 'chat',
        priority: ev.priority ?? 'normal',
      })
      setDone(true)
      onAccept()
    } catch {
      // keep button available on error
    }
  }

  return (
    <div className="relative flex items-start gap-3 rounded-xl border border-slate-600/40 bg-slate-800/40 px-4 py-3">
      <div className="mt-0.5 w-7 h-7 rounded-lg bg-indigo-500/15 flex items-center justify-center shrink-0">
        <Brain className="h-3.5 w-3.5 text-indigo-400" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-200 leading-snug">{ev.title}</p>
        {ev.description && (
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{ev.description}</p>
        )}
        <div className="flex items-center flex-wrap gap-2 mt-2">
          {ev.entity_ref && (
            <span className="text-xs bg-slate-700/60 text-slate-300 border border-slate-600/30 rounded-md px-2 py-0.5">
              {fmtEntityRef(ev.entity_ref)}
            </span>
          )}
          {ev.trigger_metric && (
            <span className="text-xs bg-slate-700/40 text-slate-400 rounded-md px-2 py-0.5">
              {fmtMetric(ev.trigger_metric)}
              {ev.trigger_value_before != null ? ` = ${ev.trigger_value_before}` : ''}
            </span>
          )}
          <span
            className={`text-xs border rounded-md px-2 py-0.5 ${priorityBadge(ev.priority)}`}
          >
            {priorityLabel(ev.priority)}
          </span>
          {ev.suggested_review_days && (
            <span className="text-xs text-slate-500">
              Проверить через {ev.suggested_review_days} дн.
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {done ? (
          <span className="flex items-center gap-1 text-xs text-emerald-400 font-medium px-2 py-1 bg-emerald-500/10 rounded-lg border border-emerald-500/20">
            <Check className="h-3 w-3" /> В отслеживании
          </span>
        ) : (
          <button
            onClick={handleAccept}
            disabled={create.isPending}
            className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-lg bg-indigo-500/15 text-indigo-300 border border-indigo-500/25 hover:bg-indigo-500/25 disabled:opacity-50 transition-colors"
          >
            {create.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            Завести
          </button>
        )}
        <button
          onClick={() => { setDismissed(true); onDismiss() }}
          className="p-1 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-colors"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function AiPage() {
  const { month, year } = useMonthStore()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  async function sendMessage(text: string) {
    if (!text.trim()) return
    const userMsg: Message = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await api.post<{ answer: string; proposed_events?: ProposedEvent[] }>(
        '/api/v1/ai/analyze',
        { question: text, month, year },
      )
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.data.answer,
          proposedEvents: res.data.proposed_events ?? [],
        },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Ошибка при обращении к AI. Проверьте настройки.' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <Header
        title="AI Аналитик"
        actions={
          <Link
            href="/dashboard/ai/events"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/50 text-slate-300 text-sm rounded-lg transition-colors"
          >
            <Brain className="h-4 w-4" />
            События мозга
          </Link>
        }
      />

      {/* Sub-nav */}
      <div className="flex gap-1 px-6 pt-3 pb-0 border-b border-slate-700/50">
        <span className="px-3 py-1.5 text-sm font-medium text-indigo-300 border-b-2 border-indigo-400 -mb-px">
          Чат
        </span>
        <Link
          href="/dashboard/ai/events"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          События
        </Link>
        <Link
          href="/dashboard/ai/profile"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          Настройки
        </Link>
      </div>

      <div className="flex-1 flex flex-col p-6 overflow-hidden">
        {/* Messages area */}
        <div className="flex-1 overflow-y-auto space-y-4 mb-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div className="w-14 h-14 rounded-2xl bg-indigo-500/15 flex items-center justify-center mb-4">
                <Sparkles className="h-7 w-7 text-indigo-400" />
              </div>
              <h3 className="text-lg font-semibold text-slate-200 mb-2">AI Аналитик</h3>
              <p className="text-slate-500 text-sm max-w-xs">
                Задайте вопрос о данных агентства за {formatMonth(month, year)}
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 max-w-lg w-full">
                {QUICK_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => sendMessage(prompt)}
                    className="text-left px-4 py-3 rounded-xl bg-slate-800/50 border border-slate-700/50 text-sm text-slate-300 hover:bg-slate-700/50 hover:border-indigo-500/30 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="w-full max-w-2xl space-y-3">
                {msg.role === 'user' ? (
                  <div className="ml-auto w-fit max-w-xl rounded-2xl px-5 py-3 bg-indigo-600 text-white">
                    <p className="text-sm leading-relaxed">{msg.content}</p>
                  </div>
                ) : (
                  <div className="rounded-2xl px-5 py-4 bg-slate-800/80 border border-slate-700/50">
                    <MarkdownContent text={msg.content} />
                  </div>
                )}

                {/* Proposed events block */}
                {msg.role === 'assistant' &&
                  msg.proposedEvents &&
                  msg.proposedEvents.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-1 flex items-center gap-1.5">
                        <Brain className="h-3.5 w-3.5 text-indigo-400" />
                        Предложенные действия
                      </p>
                      {msg.proposedEvents.map((ev, j) => (
                        <ProposedEventCard
                          key={j}
                          ev={ev}
                          onAccept={() => {}}
                          onDismiss={() => {}}
                        />
                      ))}
                    </div>
                  )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-center py-3">
              <div className="bg-slate-800/80 border border-slate-700/50 rounded-2xl px-6 py-3 flex items-center gap-3">
                <div className="relative h-5 w-5 shrink-0">
                  <Loader2 className="absolute inset-0 h-5 w-5 animate-spin text-indigo-500" />
                </div>
                <span className="text-sm text-slate-400 animate-pulse">Анализирую данные агентства…</span>
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="flex gap-3">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendMessage(input)
              }
            }}
            placeholder="Задайте вопрос..."
            disabled={loading}
            className="flex-1 h-11 rounded-xl border border-slate-600 bg-slate-800 px-4 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
          />
          <Button
            onClick={() => sendMessage(input)}
            disabled={loading || !input.trim()}
            size="icon"
            className="h-11 w-11"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}
