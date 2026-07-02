'use client'

import Link from 'next/link'
import {
  Brain,
  ArrowRight,
  CheckCircle,
  RefreshCw,
  AlertTriangle,
  CheckCheck,
  XCircle,
  Ban,
} from 'lucide-react'
import { useAgentInsights } from '@/lib/hooks/useAgentEvents'
import type { AgentEvent } from '@/lib/hooks/useAgentEvents'

const STATUS_META: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  proposed:       { label: 'Предложено',  color: 'text-blue-400',    icon: Brain },
  accepted:       { label: 'Принято',     color: 'text-indigo-400',  icon: CheckCheck },
  in_progress:    { label: 'В работе',    color: 'text-amber-400',   icon: RefreshCw },
  review_due:     { label: 'На проверке', color: 'text-orange-400',  icon: AlertTriangle },
  closed_success: { label: 'Выполнено',   color: 'text-emerald-400', icon: CheckCircle },
  closed_failed:  { label: 'Провал',      color: 'text-red-400',     icon: XCircle },
  dismissed:      { label: 'Отклонено',   color: 'text-slate-500',   icon: Ban },
}

const PRIORITY_BORDER: Record<string, string> = {
  high:   'border-l-red-400',
  normal: 'border-l-amber-400',
  low:    'border-l-slate-600',
}

function InsightCard({ ev }: { ev: AgentEvent }) {
  const m = STATUS_META[ev.status] ?? STATUS_META.dismissed
  const Icon = m.icon
  const borderColor = PRIORITY_BORDER[ev.priority] ?? 'border-l-slate-600'

  return (
    <div
      className={`flex items-start gap-3 rounded-xl border border-slate-700/50 bg-slate-800/40 px-4 py-3 border-l-2 ${borderColor}`}
    >
      <div className="mt-0.5 shrink-0">
        <Icon className={`h-4 w-4 ${m.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-200 leading-snug line-clamp-1">
          {ev.title}
        </p>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {ev.entity_ref && (
            <span className="text-xs text-slate-500">{ev.entity_ref}</span>
          )}
          <span className={`text-xs ${m.color}`}>{m.label}</span>
        </div>
      </div>
      <Link
        href="/dashboard/ai/events"
        className="shrink-0 p-1 rounded-lg text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10 transition-colors"
        title="Подробнее"
      >
        <ArrowRight className="h-4 w-4" />
      </Link>
    </div>
  )
}

export function AgentInsights() {
  const { data, isLoading } = useAgentInsights(3)

  if (isLoading) return null

  if (!data || data.length === 0) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-slate-700/50 bg-slate-800/30 px-4 py-3">
        <div className="w-7 h-7 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0">
          <CheckCircle className="h-4 w-4 text-emerald-400" />
        </div>
        <p className="text-sm text-slate-400">
          <span className="font-medium text-slate-300">Мозг агентства: </span>
          всё под контролем, открытых событий нет
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
          <Brain className="h-3.5 w-3.5 text-indigo-400" />
          Мозг агентства
        </p>
        <Link
          href="/dashboard/ai/events"
          className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1"
        >
          Все события <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
      <div className="space-y-2">
        {data.map((ev) => (
          <InsightCard key={ev.id} ev={ev} />
        ))}
      </div>
    </div>
  )
}
