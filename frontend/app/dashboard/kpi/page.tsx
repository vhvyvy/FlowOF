'use client'

import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Header } from '@/components/layout/Header'
import { MetricCard, MetricCardSkeleton } from '@/components/metrics/MetricCard'
import { Skeleton } from '@/components/ui/skeleton'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatCurrency } from '@/lib/utils'
import api from '@/lib/api'
import type { KpiRow, KpiResponse, KpiMappingOut, KpiSyncResult } from '@/types'
import {
  MessageSquare, DollarSign, Zap, RefreshCw, Upload,
  ChevronDown, ChevronUp, Info, Plus, Trash2, Link2, Users
} from 'lucide-react'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, prefix = '', suffix = '', digits = 2): string {
  if (v == null) return '—'
  return `${prefix}${v.toFixed(digits)}${suffix}`
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v.toFixed(1)}%`
}

function scoreColor(v: number | null, low: number, high: number): string {
  if (v == null) return 'text-slate-500'
  if (v >= high) return 'text-emerald-400'
  if (v >= low) return 'text-yellow-400'
  return 'text-rose-400'
}

// ── Delta badge ───────────────────────────────────────────────────────────────

function Delta({ value, suffix = '%', pp = false }: { value?: number | null; suffix?: string; pp?: boolean }) {
  if (value == null) return null
  const positive = value > 0
  const zero = Math.abs(value) < 0.05
  if (zero) return <div className="text-slate-600 text-xs leading-none mt-0.5">→ 0{pp ? ' pp' : suffix}</div>
  return (
    <div className={`text-xs leading-none mt-0.5 ${positive ? 'text-emerald-500' : 'text-rose-500'}`}>
      {positive ? '↑' : '↓'} {positive ? '+' : ''}{value.toFixed(1)}{pp ? ' pp' : suffix}
    </div>
  )
}

// ── Pamyatka ─────────────────────────────────────────────────────────────────

function Pamyatka() {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
          <Info className="h-4 w-4 text-indigo-400" />
          Памятка: как читать KPI
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-slate-500" /> : <ChevronDown className="h-4 w-4 text-slate-500" />}
      </button>
      {open && (
        <div className="px-5 pb-5 text-xs text-slate-400 space-y-4 border-t border-slate-700/50 pt-4">
          <div>
            <p className="text-slate-300 font-semibold mb-2">Базовые метрики</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
              {[
                ['PPV Open Rate %', '% купленных PPV от отправленных. 20–30% норм, 35%+ сильный, <15% пересмотреть'],
                ['APV', 'Средняя сумма за купленный PPV. Растёт — лучше упаковка/цены'],
                ['Total Chats', 'Кол-во чатов с сообщениями. Объём работы'],
                ['RPC', 'Revenue Per Chat = Выручка / Total Chats. Ключевая эффективность'],
                ['PPV Sold', 'Оценочное кол-во проданных PPV (Выручка / APV)'],
                ['APC per chat', 'PPV Sold / Total Chats — PPV в среднем на чат'],
                ['Volume Rating', 'Total Chats × PPV Open Rate — взвешенный объём'],
              ].map(([name, desc]) => (
                <div key={name} className="flex gap-2">
                  <span className="text-indigo-300 font-medium w-32 shrink-0">{name}</span>
                  <span>{desc}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="text-slate-300 font-semibold mb-2">Составные оценки</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
              {[
                ['Conversion Score', 'PPV Open Rate × APC. 1–3 норм, 5+ сильный'],
                ['Monetization Depth', '(RPC/APV)×100. Глубина монетизации на чат'],
                ['Productivity Index', '(PPV Sold/Total Chats)×PPV Open Rate'],
                ['Efficiency Ratio', '(RPC/APV)×PPV Open Rate. Общая эффективность'],
              ].map(([name, desc]) => (
                <div key={name} className="flex gap-2">
                  <span className="text-indigo-300 font-medium w-40 shrink-0">{name}</span>
                  <span>{desc}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="bg-slate-700/30 rounded-lg p-3 space-y-1">
            <p className="text-slate-300 font-medium">Выводы</p>
            <p>• Высокий RPC + высокий Volume → топ-чаттер, масштабируй</p>
            <p>• Низкий PPV Open Rate, высокий объём → много шлёт, мало покупают → пересмотри контент/цены</p>
            <p>• Высокий APV, низкий Volume → продаёт дорого, но мало охват → увеличь активность</p>
            <p>• Рост Conversion Score → чаттер прокачивается</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Mini progress bar ─────────────────────────────────────────────────────────

function MiniBar({ value, max, color = 'bg-indigo-500' }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="w-16 bg-slate-700/50 rounded-full h-1.5 ml-2 inline-block align-middle">
      <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
    </div>
  )
}

// ── Top-5 panel ───────────────────────────────────────────────────────────────

function TopPanel({ rows }: { rows: KpiRow[] }) {
  const topRpc = [...rows].filter(r => r.rpc != null).sort((a, b) => (b.rpc ?? 0) - (a.rpc ?? 0)).slice(0, 5)
  const topOr = [...rows].filter(r => r.ppv_open_rate != null).sort((a, b) => (b.ppv_open_rate ?? 0) - (a.ppv_open_rate ?? 0)).slice(0, 5)
  const topCs = [...rows].filter(r => r.conversion_score != null).sort((a, b) => (b.conversion_score ?? 0) - (a.conversion_score ?? 0)).slice(0, 5)
  const maxRpc = topRpc[0]?.rpc ?? 1
  const maxOr = topOr[0]?.ppv_open_rate ?? 1
  const maxCs = topCs[0]?.conversion_score ?? 1

  const TopList = ({ items, getValue, format, color }: { items: KpiRow[]; getValue: (r: KpiRow) => number | null; format: (v: number | null) => string; color: string }) => (
    <div className="space-y-2">
      {items.length === 0 && <p className="text-xs text-slate-600 italic">Нет данных</p>}
      {items.map((r, i) => {
        const v = getValue(r)
        const max = getValue(items[0]) ?? 1
        return (
          <div key={r.chatter} className="flex items-center gap-2">
            <span className="text-xs text-slate-600 w-4">{i + 1}</span>
            <span className="text-xs text-slate-300 flex-1 truncate">{r.chatter}</span>
            <span className={`text-xs font-mono font-medium ${color}`}>{format(v)}</span>
            <MiniBar value={v ?? 0} max={max} color={color.replace('text-', 'bg-').replace('-400', '-500')} />
          </div>
        )
      })}
    </div>
  )

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {[
        { title: 'Топ-5 по RPC', items: topRpc, getValue: (r: KpiRow) => r.rpc, format: (v: number | null) => fmt(v, '$'), color: 'text-indigo-400' },
        { title: 'Топ-5 по PPV Open Rate', items: topOr, getValue: (r: KpiRow) => r.ppv_open_rate, format: fmtPct, color: 'text-emerald-400' },
        { title: 'Топ-5 по Conversion Score', items: topCs, getValue: (r: KpiRow) => r.conversion_score, format: (v: number | null) => fmt(v, '', '', 2), color: 'text-orange-400' },
      ].map(({ title, items, getValue, format, color }) => (
        <div key={title} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">{title}</p>
          <TopList items={items} getValue={getValue} format={format} color={color} />
        </div>
      ))}
    </div>
  )
}

// ── Mapping Panel ─────────────────────────────────────────────────────────────

function MappingPanel({ mappings, onAdd, onDelete, isAdding }: {
  mappings: KpiMappingOut[]
  onAdd: (oid: string, name: string) => void
  onDelete: (id: number) => void
  isAdding: boolean
}) {
  const [open, setOpen] = useState(false)
  const [oid, setOid] = useState('')
  const [name, setName] = useState('')

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-slate-700/30 transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
          <Link2 className="h-4 w-4 text-indigo-400" />
          Маппинг чаттер ↔ Onlymonster ID
          {mappings.length > 0 && (
            <span className="bg-indigo-500/20 text-indigo-300 text-xs px-2 py-0.5 rounded-full">{mappings.length}</span>
          )}
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-slate-500" /> : <ChevronDown className="h-4 w-4 text-slate-500" />}
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-slate-700/50 pt-4 space-y-4">
          <p className="text-xs text-slate-500">Связь user_id из Onlymonster API с именем чаттера в транзакциях</p>
          <div className="flex gap-3 flex-wrap">
            <input
              value={oid}
              onChange={e => setOid(e.target.value)}
              placeholder="Onlymonster user_id (напр. 21036)"
              className="flex-1 min-w-48 bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Имя чаттера (напр. @nick)"
              className="flex-1 min-w-48 bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            <button
              onClick={() => { if (oid && name) { onAdd(oid.trim(), name.trim()); setOid(''); setName('') } }}
              disabled={isAdding || !oid || !name}
              className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
            >
              <Plus className="h-4 w-4" /> Добавить
            </button>
          </div>
          {mappings.length > 0 && (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {mappings.map(m => {
                let names = ''
                try { names = JSON.parse(m.display_names || '[]').join(', ') } catch { names = m.display_names || '' }
                return (
                  <div key={m.id} className="flex items-center justify-between bg-slate-700/30 rounded-lg px-3 py-2">
                    <span className="text-xs text-slate-400">
                      <span className="text-indigo-300 font-mono">{m.onlymonster_id}</span>
                      {' → '}
                      <span className="text-slate-300">{names}</span>
                    </span>
                    <button onClick={() => onDelete(m.id)} className="text-slate-600 hover:text-rose-400 transition-colors ml-4">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Main KPI Table ────────────────────────────────────────────────────────────

type SortKey = keyof KpiRow
type SortDir = 'asc' | 'desc'

function KpiTable({ rows }: { rows: KpiRow[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'revenue', dir: 'desc' })
  const [tab, setTab] = useState<'main' | 'scores'>('main')

  const sorted = [...rows].sort((a, b) => {
    const av = a[sort.key] as number | null ?? -Infinity
    const bv = b[sort.key] as number | null ?? -Infinity
    return sort.dir === 'desc' ? (bv as number) - (av as number) : (av as number) - (bv as number)
  })

  const toggleSort = (key: SortKey) => {
    setSort(s => s.key === key ? { key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { key, dir: 'desc' })
  }

  const Th = ({ label, field, right = true }: { label: string; field: SortKey; right?: boolean }) => (
    <th
      onClick={() => toggleSort(field)}
      className={`${right ? 'text-right' : 'text-left'} px-3 py-3 text-xs font-medium text-slate-500 cursor-pointer select-none hover:text-slate-300 transition-colors whitespace-nowrap`}
    >
      {label}
      {sort.key === field && (
        <span className="ml-1">{sort.dir === 'desc' ? '↓' : '↑'}</span>
      )}
    </th>
  )

  const mainCols: { label: string; field: SortKey }[] = [
    { label: 'Выручка', field: 'revenue' },
    { label: 'Выходы', field: 'transactions' },
    { label: 'Средний чек', field: 'avg_check' },
    { label: 'Доля %', field: 'share_pct' },
    { label: 'PPV Open Rate', field: 'ppv_open_rate' },
    { label: 'APV', field: 'apv' },
    { label: 'Total Chats', field: 'total_chats' },
    { label: 'RPC', field: 'rpc' },
    { label: 'PPV Sold', field: 'ppv_sold' },
    { label: 'APC/Chat', field: 'apc_per_chat' },
    { label: 'Volume', field: 'volume_rating' },
    { label: 'Выплата', field: 'payout' },
  ]

  const scoreCols: { label: string; field: SortKey; low: number; high: number }[] = [
    { label: 'Conversion Score', field: 'conversion_score', low: 1, high: 3 },
    { label: 'Monetization Depth', field: 'monetization_depth', low: 1, high: 3 },
    { label: 'Productivity Index', field: 'productivity_index', low: 0.5, high: 2 },
    { label: 'Efficiency Ratio', field: 'efficiency_ratio', low: 0.5, high: 2 },
    { label: 'Выручка', field: 'revenue', low: 0, high: Infinity },
    { label: 'RPC', field: 'rpc', low: 1, high: 3 },
  ]

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="flex items-center gap-4 px-5 py-4 border-b border-slate-700/50">
        <p className="text-sm font-semibold text-slate-200 flex-1">Таблица KPI</p>
        <div className="flex bg-slate-700/40 rounded-lg p-0.5 text-xs">
          <button onClick={() => setTab('main')} className={`px-3 py-1 rounded-md transition-colors ${tab === 'main' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-300'}`}>
            Основные
          </button>
          <button onClick={() => setTab('scores')} className={`px-3 py-1 rounded-md transition-colors ${tab === 'scores' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-300'}`}>
            Составные
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        {tab === 'main' ? (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left px-3 py-3 text-xs font-medium text-slate-500">Чаттер</th>
                {mainCols.map(c => <Th key={c.field} label={c.label} field={c.field} />)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/25">
              {sorted.map((row) => (
                <tr key={row.chatter} className="hover:bg-slate-700/15 transition-colors">
                  <td className="px-3 py-2.5 font-medium text-slate-200 whitespace-nowrap">{row.chatter}</td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="text-emerald-400 font-mono">{formatCurrency(row.revenue)}</div>
                    <Delta value={row.revenue_delta} />
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-300">{row.transactions}</td>
                  <td className="px-3 py-2.5 text-right text-slate-300">{formatCurrency(row.avg_check)}</td>
                  <td className="px-3 py-2.5 text-right text-slate-400">{fmtPct(row.share_pct)}</td>
                  <td className="px-3 py-2.5 text-right">
                    <div className={`font-medium ${scoreColor(row.ppv_open_rate, 15, 30)}`}>{fmtPct(row.ppv_open_rate)}</div>
                    <Delta value={row.ppv_open_rate_delta} pp />
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-300">{fmt(row.apv, '$')}</td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="text-slate-300">{row.total_chats?.toLocaleString() ?? '—'}</div>
                    <Delta value={row.total_chats_delta} />
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className={`font-mono font-medium ${scoreColor(row.rpc, 1, 3)}`}>{fmt(row.rpc, '$')}</div>
                    <Delta value={row.rpc_delta} />
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-400">{fmt(row.ppv_sold, '', '', 1)}</td>
                  <td className="px-3 py-2.5 text-right text-slate-400">{fmt(row.apc_per_chat)}</td>
                  <td className="px-3 py-2.5 text-right text-slate-400">{fmt(row.volume_rating, '', '', 1)}</td>
                  <td className="px-3 py-2.5 text-right text-orange-400 font-medium">{formatCurrency(row.payout)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left px-3 py-3 text-xs font-medium text-slate-500">Чаттер</th>
                {scoreCols.map(c => <Th key={c.field} label={c.label} field={c.field} />)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/25">
              {sorted.map((row) => (
                <tr key={row.chatter} className="hover:bg-slate-700/15 transition-colors">
                  <td className="px-3 py-2.5 font-medium text-slate-200 whitespace-nowrap">{row.chatter}</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${scoreColor(row.conversion_score, 1, 3)}`}>{fmt(row.conversion_score)}</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${scoreColor(row.monetization_depth, 1, 3)}`}>{fmt(row.monetization_depth)}</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${scoreColor(row.productivity_index, 0.5, 2)}`}>{fmt(row.productivity_index)}</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${scoreColor(row.efficiency_ratio, 0.5, 2)}`}>{fmt(row.efficiency_ratio)}</td>
                  <td className="px-3 py-2.5 text-right text-emerald-400 font-mono">{formatCurrency(row.revenue)}</td>
                  <td className={`px-3 py-2.5 text-right font-mono ${scoreColor(row.rpc, 1, 3)}`}>{fmt(row.rpc, '$')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function KpiPage() {
  const { month, year } = useMonthStore()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const { data, isLoading, error } = useQuery<KpiResponse>({
    queryKey: ['kpi', month, year],
    queryFn: () => api.get<KpiResponse>(`/api/v1/kpi?month=${month}&year=${year}`).then(r => r.data),
    enabled: month > 0 && year > 0,
  })

  const { data: mappings = [], refetch: refetchMappings } = useQuery<KpiMappingOut[]>({
    queryKey: ['kpi-mapping'],
    queryFn: () => api.get<KpiMappingOut[]>('/api/v1/kpi/mapping').then(r => r.data),
  })

  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  const syncMutation = useMutation({
    mutationFn: () =>
      api.post<KpiSyncResult>(`/api/v1/kpi/sync?month=${month}&year=${year}`).then(r => r.data),
    onSuccess: (res) => {
      setSyncMsg(res.message)
      setSyncError(null)
      qc.invalidateQueries({ queryKey: ['kpi'] })
    },
    onError: (e: any) => {
      setSyncError(e?.response?.data?.detail ?? 'Ошибка синхронизации')
      setSyncMsg(null)
    },
  })

  const syncAllMutation = useMutation({
    mutationFn: () => api.post<KpiSyncResult>('/api/v1/kpi/sync-all').then(r => r.data),
    onSuccess: (res) => {
      setSyncMsg(res.message)
      setSyncError(null)
      qc.invalidateQueries({ queryKey: ['kpi'] })
    },
    onError: (e: any) => {
      setSyncError(e?.response?.data?.detail ?? 'Ошибка синхронизации всех месяцев')
      setSyncMsg(null)
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post<KpiSyncResult>(`/api/v1/kpi/upload?month=${month}&year=${year}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }).then(r => r.data)
    },
    onSuccess: (res) => {
      setSyncMsg(res.message)
      setSyncError(null)
      qc.invalidateQueries({ queryKey: ['kpi', month, year] })
    },
    onError: (e: any) => {
      setSyncError(e?.response?.data?.detail ?? 'Ошибка загрузки файла')
      setSyncMsg(null)
    },
  })

  const addMappingMutation = useMutation({
    mutationFn: ({ oid, name }: { oid: string; name: string }) =>
      api.post('/api/v1/kpi/mapping', { onlymonster_id: oid, display_name: name }),
    onSuccess: () => refetchMappings(),
  })

  const deleteMappingMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/kpi/mapping/${id}`),
    onSuccess: () => refetchMappings(),
  })

  const rows = data?.rows ?? []
  const hasOm = data?.has_onlymonster_key ?? false
  const hasOmData = rows.some(r => r.ppv_open_rate != null)

  return (
    <div className="flex flex-col h-full">
      <Header title="KPI Чаттеров" />

      <div className="flex-1 p-6 space-y-5 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4">
            <p className="text-sm text-rose-400">Не удалось загрузить данные</p>
          </div>
        )}

        {/* Summary cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)
          ) : data ? (
            <>
              <MetricCard label="Выручка" value={formatCurrency(data.total_revenue)} icon={<DollarSign className="h-4 w-4" />} />
              <MetricCard label="Транзакций" value={data.total_transactions.toLocaleString()} icon={<MessageSquare className="h-4 w-4" />} />
              <MetricCard label="Avg RPC" value={data.avg_rpc != null ? `$${data.avg_rpc}` : '—'} icon={<Zap className="h-4 w-4" />} />
              <MetricCard label="Чаттеров" value={String(rows.length)} icon={<Users className="h-4 w-4" />} />
            </>
          ) : null}
        </div>

        {/* Sync / Upload bar */}
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <p className="text-sm font-medium text-slate-300 mr-2">Данные Onlymonster</p>
            {hasOm ? (
              <>
                <button
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending || syncAllMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
                >
                  <RefreshCw className={`h-4 w-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
                  {syncMutation.isPending ? 'Синхронизация...' : 'Этот месяц'}
                </button>
                <button
                  onClick={() => syncAllMutation.mutate()}
                  disabled={syncMutation.isPending || syncAllMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-indigo-900/60 hover:bg-indigo-800/70 border border-indigo-700/50 disabled:opacity-50 text-indigo-300 text-sm rounded-lg transition-colors"
                  title="Синхронизировать все месяцы с транзакциями"
                >
                  <RefreshCw className={`h-4 w-4 ${syncAllMutation.isPending ? 'animate-spin' : ''}`} />
                  {syncAllMutation.isPending ? 'Синхронизация...' : 'Все месяцы'}
                </button>
              </>
            ) : (
              <a
                href="/dashboard/settings"
                className="flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 px-3 py-2 rounded-lg transition-colors"
              >
                Добавьте API-ключ в Настройках →
              </a>
            )}
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploadMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 text-sm rounded-lg transition-colors"
            >
              <Upload className={`h-4 w-4 ${uploadMutation.isPending ? 'animate-pulse' : ''}`} />
              {uploadMutation.isPending ? 'Загрузка...' : 'Загрузить CSV из Onlymonster'}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0]
                if (f) uploadMutation.mutate(f)
                e.target.value = ''
              }}
            />
          </div>
          {syncMsg && <p className="text-xs text-emerald-400">{syncMsg}</p>}
          {syncError && <p className="text-xs text-rose-400">{syncError}</p>}
          {!hasOmData && !isLoading && rows.length > 0 && (
            <div className="text-xs text-slate-500 bg-slate-700/30 rounded-lg p-3 space-y-1">
              <p className="text-slate-400 font-medium">Как заполнить PPV Open Rate, APV, RPC и другие метрики:</p>
              <p>1. Маппинг ✓ — вы уже связали чаттеров с Onlymonster ID</p>
              <p>2. Загрузите данные: нажмите <span className="text-slate-300">"Загрузить CSV"</span> (экспорт из Onlymonster → Chatter Metrics) или <span className="text-slate-300">"Синхронизировать через API"</span> (нужен API-ключ в Настройках)</p>
              <p>3. После загрузки метрики появятся автоматически</p>
            </div>
          )}
        </div>

        {/* Памятка */}
        <Pamyatka />

        {/* Mapping */}
        <MappingPanel
          mappings={mappings}
          onAdd={(oid, name) => addMappingMutation.mutate({ oid, name })}
          onDelete={id => deleteMappingMutation.mutate(id)}
          isAdding={addMappingMutation.isPending}
        />

        {/* Top-5 panels */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40 w-full rounded-xl" />)}
          </div>
        ) : rows.length > 0 ? (
          <TopPanel rows={rows} />
        ) : null}

        {/* Main table */}
        {isLoading ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-9 w-full mb-2" />)}
          </div>
        ) : rows.length > 0 ? (
          <KpiTable rows={rows} />
        ) : data ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-10 text-center">
            <p className="text-slate-500">Нет данных за выбранный период</p>
          </div>
        ) : null}
      </div>
    </div>
  )
}
