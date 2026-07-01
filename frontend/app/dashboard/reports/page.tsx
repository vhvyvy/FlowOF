'use client'

import { useEffect, useState, useCallback } from 'react'
import { Header } from '@/components/layout/Header'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { resolveApiBaseURL } from '@/lib/api'
import { Download, RefreshCw, ImageOff, FileText, Loader2 } from 'lucide-react'

const FINANCE_CHARTS = [
  { id: 'revenue_trend',           label: 'Выручка по месяцам' },
  { id: 'revenue_expenses_profit', label: 'Выручка / Расходы / Прибыль' },
  { id: 'top_chatters',            label: 'Топ чаттеров (месяц)' },
  { id: 'chatter_mom_change',      label: 'Изменение выручки чаттеров MoM' },
  { id: 'tx_count',                label: 'Транзакции по месяцам' },
  { id: 'avg_check',               label: 'Средний чек по месяцам' },
  { id: 'expenses_by_category',    label: 'Расходы по категориям (месяц)' },
] as const

const KPI_CHARTS = [
  { id: 'kpi_top_revenue',         label: 'Топ-10 по выручке (KPI)' },
  { id: 'kpi_open_rate',           label: 'PPV Open Rate (%)' },
  { id: 'kpi_scatter_rpc_chats',   label: 'Объём диалогов × RPC' },
  { id: 'kpi_biggest_movers',      label: 'Крупнейшие изменения выручки MoM' },
] as const

type FinanceChartId = typeof FINANCE_CHARTS[number]['id']
type KpiChartId     = typeof KPI_CHARTS[number]['id']
type ChartId        = FinanceChartId | KpiChartId
type LoadState      = 'idle' | 'loading' | 'ok' | 'error'

async function fetchChartBlob(id: ChartId, year: number, month: number, token: string): Promise<string> {
  const base = resolveApiBaseURL()
  const url  = `${base}/api/v1/reports/chart/${id}?year=${year}&month=${month}`
  const res  = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

function ChartCard({ chartId, label, year, month }: {
  chartId: ChartId
  label: string
  year: number
  month: number
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [state, setState]         = useState<LoadState>('idle')

  const load = useCallback(async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') || '' : ''
    setState('loading')
    if (objectUrl) URL.revokeObjectURL(objectUrl)
    try {
      const url = await fetchChartBlob(chartId, year, month, token)
      setObjectUrl(url)
      setState('ok')
    } catch {
      setObjectUrl(null)
      setState('error')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartId, year, month])

  useEffect(() => {
    load()
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartId, year, month])

  const handleDownload = () => {
    if (!objectUrl) return
    const a = document.createElement('a')
    a.href     = objectUrl
    a.download = `${chartId}_${year}_${month.toString().padStart(2, '0')}.png`
    a.click()
  }

  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-2xl overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/40">
        <span className="text-sm font-medium text-slate-200">{label}</span>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={state === 'loading'}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors disabled:opacity-40"
            title="Обновить"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${state === 'loading' ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={handleDownload}
            disabled={!objectUrl}
            className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-300 hover:bg-slate-700/50 transition-colors disabled:opacity-40"
            title="Скачать PNG"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="relative min-h-[260px] flex items-center justify-center bg-white/[0.02]">
        {state === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
            <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-slate-500">Генерация графика…</span>
          </div>
        )}
        {state === 'error' && (
          <div className="flex flex-col items-center gap-2 text-slate-500">
            <ImageOff className="h-8 w-8" />
            <span className="text-xs">Не удалось загрузить</span>
            <button onClick={load} className="text-xs text-indigo-400 hover:text-indigo-300 underline">
              Повторить
            </button>
          </div>
        )}
        {state === 'ok' && objectUrl && (
          <img src={objectUrl} alt={label} className="w-full h-auto object-contain rounded-b-xl" />
        )}
        {state === 'idle' && <div className="text-xs text-slate-600">Ожидание…</div>}
      </div>
    </div>
  )
}

function SectionHeading({ label, note }: { label: string; note?: string }) {
  return (
    <div className="flex items-baseline gap-3 pt-2">
      <h2 className="text-base font-semibold text-slate-200">{label}</h2>
      {note && <span className="text-xs text-slate-500">{note}</span>}
    </div>
  )
}

function PdfDownloadButton({ year, month }: { year: number; month: number }) {
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  const handleDownload = async () => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') || '' : ''
    const base  = resolveApiBaseURL()
    const url   = `${base}/api/v1/reports/pdf?year=${year}&month=${month}`
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob     = await res.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href     = objectUrl
      a.download = `report_${year}_${month.toString().padStart(2, '0')}.pdf`
      a.click()
      URL.revokeObjectURL(objectUrl)
    } catch (e) {
      setError('Не удалось сгенерировать PDF')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleDownload}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
      >
        {loading
          ? <><Loader2 className="h-4 w-4 animate-spin" /> Генерируется отчёт…</>
          : <><FileText className="h-4 w-4" /> Скачать PDF-отчёт</>
        }
      </button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  )
}

export default function ReportsPage() {
  const { month, year } = useMonthStore()

  return (
    <div className="flex flex-col h-full">
      <Header title="Отчёты" />

      <div className="flex-1 overflow-y-auto p-6 space-y-8">
        {/* Top bar: hint + PDF button */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <p className="text-xs text-slate-500">
            Фокусный месяц: <span className="text-slate-300 font-medium">{month.toString().padStart(2, '0')}/{year}</span>.
            {' '}Графики тренда строятся по всей истории. Смените месяц в заголовке — детализация пересчитается.
          </p>
          <PdfDownloadButton year={year} month={month} />
        </div>

        {/* ── Финансы ── */}
        <section className="space-y-4">
          <SectionHeading label="Финансы" note="выручка, расходы, чаттеры, тренды" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            {FINANCE_CHARTS.map(({ id, label }) => (
              <ChartCard key={`${id}-${year}-${month}`} chartId={id} label={label} year={year} month={month} />
            ))}
          </div>
        </section>

        {/* ── KPI ── */}
        <section className="space-y-4">
          <SectionHeading label="KPI чаттеров" note="Onlymonster-метрики, RPC, Open Rate, MoM" />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            {KPI_CHARTS.map(({ id, label }) => (
              <ChartCard key={`${id}-${year}-${month}`} chartId={id} label={label} year={year} month={month} />
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
