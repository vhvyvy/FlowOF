'use client'

import { useEffect, useRef, useState } from 'react'
import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useChatters } from '@/lib/hooks/useChatters'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { useTeamStore } from '@/lib/hooks/useTeam'
import { formatCurrency } from '@/lib/utils'
import type { ChatterStatus, ChatterModelBreakdown } from '@/types'
import { DollarSign, Users, Target, TrendingUp, X } from 'lucide-react'

const STATUS_BADGE: Record<ChatterStatus, { label: string; variant: 'success' | 'default' | 'warning' | 'danger' }> = {
  top:  { label: 'Топ',    variant: 'success' },
  ok:   { label: 'Норм',   variant: 'default' },
  risk: { label: 'Риск',   variant: 'warning' },
  miss: { label: 'Провал', variant: 'danger'  },
}

function tierStyle(pct: number): { color: string; bg: string } {
  if (pct >= 25)  return { color: 'text-emerald-400', bg: 'bg-emerald-500/15 border-emerald-500/30' }
  if (pct >= 24)  return { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' }
  if (pct >= 23)  return { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' }
  if (pct >= 22)  return { color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/20'         }
  if (pct >= 21)  return { color: 'text-sky-400',     bg: 'bg-sky-500/10 border-sky-500/20'         }
  return            { color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/20'   }
}

function planCompletionColor(completion: number) {
  if (completion >= 100) return 'text-emerald-400'
  if (completion >= 70)  return 'text-sky-400'
  if (completion >= 50)  return 'text-yellow-400'
  return 'text-red-400'
}

// ── Popover with model breakdown ──────────────────────────────────────────────

interface ModelPopoverProps {
  chatterName: string
  models: ChatterModelBreakdown[]
  onClose: () => void
  anchorRef: React.RefObject<HTMLElement>
}

function ModelPopover({ chatterName, models, onClose, anchorRef }: ModelPopoverProps) {
  const popRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    if (anchorRef.current && popRef.current) {
      const rect = anchorRef.current.getBoundingClientRect()
      const pop  = popRef.current.getBoundingClientRect()
      let left = rect.left + rect.width / 2 - pop.width / 2
      let top  = rect.bottom + 8 + window.scrollY
      // keep within viewport
      if (left + pop.width > window.innerWidth - 16) left = window.innerWidth - pop.width - 16
      if (left < 16) left = 16
      setPos({ top, left })
    }
  }, [anchorRef])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node) &&
          anchorRef.current && !anchorRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose, anchorRef])

  return (
    <div
      ref={popRef}
      style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 9999 }}
      className="w-80 bg-slate-800 border border-slate-600/60 rounded-xl shadow-2xl shadow-black/50"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/60">
        <div>
          <p className="text-xs text-slate-400 uppercase tracking-wide font-semibold">Анкеты</p>
          <p className="text-sm font-semibold text-slate-100 mt-0.5">{chatterName}</p>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Model rows */}
      <div className="divide-y divide-slate-700/40 max-h-80 overflow-y-auto">
        {models.map((m) => {
          const ts = tierStyle(m.tier_pct)
          const hasPlan = m.plan_amount > 0
          const hasRetention = m.retention > 0
          return (
            <div key={m.model} className="px-4 py-3">
              {/* Model name + plan info */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-slate-200 truncate">{m.model}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {hasPlan
                      ? `${m.plan_completion}% плана · $${m.plan_amount.toLocaleString()} план`
                      : 'Нет плана → дефолт 25%'
                    }
                  </p>
                </div>
                <span className={`shrink-0 inline-block text-xs font-bold px-2 py-0.5 rounded-lg border ${ts.bg} ${ts.color}`}>
                  {m.tier_pct}%
                </span>
              </div>
              {/* Financials */}
              <div className="bg-slate-700/30 rounded-lg px-3 py-2 space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Выручка</span>
                  <span className="text-slate-300">{formatCurrency(m.revenue)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400">Начислено ({m.tier_pct}%)</span>
                  <span className="text-slate-300">{formatCurrency(m.cut)}</span>
                </div>
                {hasRetention && (
                  <div className="flex justify-between text-xs">
                    <span className="text-orange-400/80">Ретеншн −2.5%</span>
                    <span className="text-orange-400/80">−{formatCurrency(m.retention)}</span>
                  </div>
                )}
                <div className="flex justify-between text-xs font-semibold border-t border-slate-600/40 pt-1 mt-1">
                  <span className="text-slate-300">К выплате</span>
                  <span className="text-emerald-400">{formatCurrency(m.net_cut)}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer total */}
      <div className="px-4 py-2.5 border-t border-slate-700/60 flex items-center justify-between bg-slate-700/20 rounded-b-xl">
        <span className="text-xs text-slate-400">Итого к выплате</span>
        <span className="text-sm font-semibold text-emerald-400">
          {formatCurrency(models.reduce((s, m) => s + m.net_cut, 0))}
        </span>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ChattersPage() {
  const { month, year } = useMonthStore()
  const { teamId } = useTeamStore()
  const { data, isLoading, error } = useChatters(month, year, teamId)

  const [openPopover, setOpenPopover] = useState<string | null>(null)
  const btnRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const anchorRef = useRef<HTMLElement | null>(null)

  const completion  = data?.plan_completion ?? 0
  const totalPayout = data?.chatters.reduce((s, c) => s + c.chatter_cut, 0) ?? 0
  const tier        = tierStyle(completion >= 100 ? 25 : completion >= 90 ? 24 : completion >= 80 ? 23 : completion >= 70 ? 22 : completion >= 60 ? 21 : 20)

  const activeChatter = openPopover
    ? data?.chatters.find((c) => `${c.name}::${c.team_id ?? 0}` === openPopover) ?? null
    : null

  return (
    <div className="flex flex-col h-full">
      <Header title="Чаттеры" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard label="Общая выручка"    value={formatCurrency(data.total_revenue)} icon={<DollarSign className="h-4 w-4" />} />
              <MetricCard label="Чаттеров"          value={data.chatters.length.toString()}    icon={<Users className="h-4 w-4" />} />
              <MetricCard label="Выполнение плана"  value={`${completion}%`}                   icon={<Target className="h-4 w-4" />} />
              <MetricCard label="Итого выплаты"     value={formatCurrency(totalPayout)}         icon={<TrendingUp className="h-4 w-4" />} />
            </>
          ) : null}
        </div>

        {/* Active tier banner */}
        {!isLoading && data && (
          <div className={`flex items-center px-5 py-3.5 rounded-xl border ${tier.bg}`}>
            <div className="flex items-center gap-3">
              <span className={`text-2xl font-bold ${tier.color}`}>{completion}%</span>
              <div>
                <p className={`text-sm font-semibold ${tier.color}`}>
                  Тир по анкетам: каждая анкета считается отдельно
                </p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Выполнение плана: <span className={`font-semibold ${planCompletionColor(completion)}`}>{completion}%</span>
                  <span className="ml-2 text-slate-500">· Тиры: ≥100%→25%, ≥90%→24%, ≥80%→23%, ≥70%→22%, ≥60%→21%, {'<60%'}→20% (мин.) · Нет плана→25%</span>
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Table */}
        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
          </div>
        ) : data && data.chatters.length > 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700/50 bg-slate-700/20">
                    <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Чаттер</th>
                    {teamId === 'all' && (
                      <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Команда</th>
                    )}
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Выручка</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Транзакции</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">RPC</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">% выплаты</th>
                    <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Выплата</th>
                    <th className="text-center px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {data.chatters.map((chatter) => {
                    const rowKey = `${chatter.name}::${chatter.team_id ?? 0}`
                    const status = STATUS_BADGE[chatter.status]
                    const ts = tierStyle(chatter.chatter_pct)
                    const isOpen = openPopover === rowKey
                    return (
                      <tr key={rowKey} className="hover:bg-slate-700/20 transition-colors">
                        <td className="px-5 py-3 text-sm font-medium text-slate-200">{chatter.name}</td>
                        {teamId === 'all' && (
                          <td className="px-5 py-3 text-sm text-slate-400">{chatter.team_name ?? '—'}</td>
                        )}
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">{formatCurrency(chatter.revenue)}</td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">{chatter.transactions}</td>
                        <td className="px-5 py-3 text-sm text-slate-300 text-right">${chatter.rpc}</td>
                        <td className="px-5 py-3 text-right">
                          <button
                            ref={(el) => { btnRefs.current[rowKey] = el }}
                            onClick={(e) => {
                              anchorRef.current = e.currentTarget
                              setOpenPopover(isOpen ? null : rowKey)
                            }}
                            className={`inline-flex items-center gap-1 text-sm font-bold px-2 py-0.5 rounded-lg border transition-all cursor-pointer hover:brightness-125 active:scale-95 ${ts.bg} ${ts.color} ${isOpen ? 'ring-1 ring-offset-1 ring-offset-slate-800 ring-current' : ''}`}
                          >
                            {chatter.chatter_pct}%
                          </button>
                        </td>
                        <td className="px-5 py-3 text-sm font-semibold text-right">
                          {chatter.chatter_cut > 0 ? (
                            <span className={ts.color}>{formatCurrency(chatter.chatter_cut)}</span>
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
                        </td>
                        <td className="px-5 py-3 text-center">
                          <Badge variant={status.variant}>{status.label}</Badge>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : data ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-10 text-center">
            <p className="text-slate-500">Нет данных за выбранный период</p>
          </div>
        ) : null}
      </div>

      {/* Popover rendered outside table flow */}
      {activeChatter && openPopover && (
        <ModelPopover
          chatterName={activeChatter.name}
          models={activeChatter.models ?? []}
          onClose={() => setOpenPopover(null)}
          anchorRef={{ current: btnRefs.current[openPopover] } as React.RefObject<HTMLElement>}
        />
      )}
    </div>
  )
}
