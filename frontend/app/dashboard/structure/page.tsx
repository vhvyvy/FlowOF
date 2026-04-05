'use client'

import { Header } from '@/components/layout/Header'
import { Skeleton } from '@/components/ui/skeleton'
import { useStructure } from '@/lib/hooks/useStructure'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import type { ModelShare, ChatterShare, EconomicBreakdown } from '@/types'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Treemap,
} from 'recharts'

// ── Colour palette ────────────────────────────────────────────────────────────

const MODEL_COLORS = [
  '#6366f1','#8b5cf6','#a855f7','#ec4899','#f43f5e',
  '#f97316','#eab308','#22c55e','#14b8a6','#06b6d4',
  '#3b82f6','#84cc16','#f59e0b','#10b981','#64748b',
]

const ECO_COLORS: Record<string, string> = {
  'Моделям':   '#f43f5e',
  'Чаттерам':  '#f97316',
  'Адмнам':    '#eab308',
  'Вывод':     '#64748b',
  'Ретеншн':   '#22c55e',
  'Агентство': '#6366f1',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function completionColor(pct: number) {
  if (pct >= 100) return 'text-emerald-400'
  if (pct >= 70)  return 'text-sky-400'
  if (pct >= 50)  return 'text-yellow-400'
  if (pct > 0)    return 'text-red-400'
  return 'text-slate-500'
}

function completionBg(pct: number) {
  if (pct >= 100) return 'bg-emerald-500'
  if (pct >= 70)  return 'bg-sky-500'
  if (pct >= 50)  return 'bg-yellow-500'
  if (pct > 0)    return 'bg-red-500'
  return 'bg-slate-600'
}

// ── Custom Treemap cell ───────────────────────────────────────────────────────

function TreemapCell(props: {
  x?: number; y?: number; width?: number; height?: number
  name?: string; value?: number; index?: number; share_pct?: number
}) {
  const { x = 0, y = 0, width = 0, height = 0, name = '', value = 0, index = 0, share_pct = 0 } = props
  const color = MODEL_COLORS[index % MODEL_COLORS.length]
  if (width < 20 || height < 20) return null
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={color} fillOpacity={0.85} rx={4} />
      {width > 60 && height > 36 && (
        <>
          <text x={x + 8} y={y + 20} fill="#fff" fontSize={Math.min(13, width / 8)} fontWeight={600} opacity={0.95}>
            {name && name.length > 16 ? name.slice(0, 14) + '…' : name}
          </text>
          {height > 52 && (
            <text x={x + 8} y={y + 36} fill="#fff" fontSize={11} opacity={0.7}>
              {formatCurrency(value)} · {share_pct}%
            </text>
          )}
        </>
      )}
    </g>
  )
}

// ── Economic Donut ────────────────────────────────────────────────────────────

function EconomicDonut({ eco, revenue }: { eco: EconomicBreakdown; revenue: number }) {
  const agencyNet = revenue > 0
    ? revenue - eco.model_cut - eco.chatter_cut - eco.admin_cut - eco.withdraw + eco.retention
    : 0

  const slices = [
    { name: 'Моделям',   value: eco.model_cut,   pct: eco.model_pct },
    { name: 'Чаттерам',  value: eco.chatter_cut,  pct: eco.chatter_pct },
    { name: 'Адмнам',    value: eco.admin_cut,    pct: eco.admin_pct },
    ...(eco.use_withdraw && eco.withdraw > 0 ? [{ name: 'Вывод', value: eco.withdraw, pct: eco.withdraw_pct }] : []),
    ...(eco.use_retention && eco.retention > 0 ? [{ name: 'Ретеншн', value: eco.retention, pct: +(eco.retention / revenue * 100).toFixed(1) }] : []),
    { name: 'Агентство', value: agencyNet > 0 ? agencyNet : 0, pct: revenue > 0 ? +(agencyNet / revenue * 100).toFixed(1) : 0 },
  ].filter((s) => s.value > 0)

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">Распределение выручки</p>
      <div className="flex items-center gap-6">
        <div className="shrink-0">
          <ResponsiveContainer width={180} height={180}>
            <PieChart>
              <Pie
                data={slices}
                cx="50%" cy="50%"
                innerRadius={52} outerRadius={82}
                paddingAngle={2}
                dataKey="value"
              >
                {slices.map((s) => (
                  <Cell key={s.name} fill={ECO_COLORS[s.name] ?? '#6366f1'} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                formatter={(v) => [typeof v === 'number' ? formatCurrency(v) : String(v), '']}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="flex-1 space-y-2">
          {slices.map((s) => (
            <div key={s.name} className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: ECO_COLORS[s.name] ?? '#6366f1' }} />
              <span className="text-xs text-slate-400 flex-1">{s.name}</span>
              <span className="text-xs font-semibold text-slate-200">{formatCurrency(s.value)}</span>
              <span className="text-xs text-slate-500 w-10 text-right">{s.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Model Treemap ─────────────────────────────────────────────────────────────

function ModelTreemap({ models }: { models: ModelShare[] }) {
  const data = models.map((m, i) => ({
    name: m.model,
    value: m.revenue,
    share_pct: m.share_pct,
    index: i,
  }))

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">Карта анкет по выручке</p>
      <ResponsiveContainer width="100%" height={280}>
        <Treemap
          data={data}
          dataKey="value"
          aspectRatio={4 / 3}
          content={<TreemapCell />}
        />
      </ResponsiveContainer>
    </div>
  )
}

// ── Chatter Bar ───────────────────────────────────────────────────────────────

function ChatterBar({ chatters }: { chatters: ChatterShare[] }) {
  const top = chatters.slice(0, 15)
  const data = top.map((c) => ({ name: c.chatter, revenue: c.revenue, share: c.share_pct }))

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">Выручка по чаттерам (топ {top.length})</p>
      <ResponsiveContainer width="100%" height={Math.max(220, top.length * 28)}>
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 64, left: 8, bottom: 0 }}>
          <CartesianGrid horizontal={false} stroke="#334155" strokeOpacity={0.4} />
          <XAxis
            type="number"
            tick={{ fontSize: 11, fill: '#64748b' }}
            tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
            axisLine={false} tickLine={false}
          />
          <YAxis
            type="category" dataKey="name"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            axisLine={false} tickLine={false} width={110}
          />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
            formatter={(v: number, _: string, entry: { payload: { share: number } }) => [
              `${formatCurrency(v)} (${entry.payload.share}%)`, 'Выручка'
            ]}
          />
          <Bar dataKey="revenue" radius={[0, 4, 4, 0]} fill="#6366f1" fillOpacity={0.85}>
            {data.map((_, i) => (
              <Cell key={i} fill={MODEL_COLORS[i % MODEL_COLORS.length]} fillOpacity={0.8} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Model Table ───────────────────────────────────────────────────────────────

function ModelTable({ models }: { models: ModelShare[] }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-700/50">
        <p className="text-sm font-semibold text-slate-300">Рейтинг анкет</p>
      </div>
      <div className="divide-y divide-slate-700/30">
        {models.map((m, i) => {
          const hasPlan = m.plan_amount > 0
          return (
            <div key={m.model} className="flex items-center gap-4 px-5 py-3 hover:bg-slate-700/20 transition-colors">
              <span className="text-xs font-bold text-slate-600 w-5 shrink-0">{i + 1}</span>
              <div
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ background: MODEL_COLORS[i % MODEL_COLORS.length] }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-200 truncate">{m.model}</p>
                {hasPlan && (
                  <div className="flex items-center gap-2 mt-1">
                    <div className="flex-1 h-1 bg-slate-700 rounded-full max-w-32">
                      <div
                        className={`h-1 rounded-full ${completionBg(m.plan_completion)}`}
                        style={{ width: `${Math.min(m.plan_completion, 100)}%` }}
                      />
                    </div>
                    <span className={`text-xs font-medium ${completionColor(m.plan_completion)}`}>
                      {m.plan_completion}%
                    </span>
                  </div>
                )}
              </div>
              <div className="text-right shrink-0">
                <p className="text-sm font-semibold text-slate-100">{formatCurrency(m.revenue)}</p>
                <p className="text-xs text-slate-500">{m.share_pct}% выручки</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function StructurePage() {
  const { month, year } = useMonthStore()
  const { data, isLoading, error } = useStructure(month, year)

  return (
    <div className="flex flex-col h-full">
      <Header title="Структура" />

      <div className="flex-1 p-6 space-y-6 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-red-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Top row: Treemap + Donut */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            {isLoading ? (
              <Skeleton className="h-[332px] w-full rounded-xl" />
            ) : data && data.models.length > 0 ? (
              <ModelTreemap models={data.models} />
            ) : null}
          </div>
          <div>
            {isLoading ? (
              <Skeleton className="h-[332px] w-full rounded-xl" />
            ) : data?.economic ? (
              <EconomicDonut eco={data.economic} revenue={data.total_revenue} />
            ) : null}
          </div>
        </div>

        {/* Chatter bar chart */}
        {isLoading ? (
          <Skeleton className="h-64 w-full rounded-xl" />
        ) : data && data.chatters.length > 0 ? (
          <ChatterBar chatters={data.chatters} />
        ) : null}

        {/* Model detail table */}
        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
          </div>
        ) : data && data.models.length > 0 ? (
          <ModelTable models={data.models} />
        ) : data ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-10 text-center">
            <p className="text-slate-500">Нет данных за выбранный период</p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
