'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Header } from '@/components/layout/Header'
import { Skeleton } from '@/components/ui/skeleton'
import { Save, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface PlanRow {
  model: string
  plan_amount: number
  actual: number
  completion_pct: number
}

interface PlansResponse {
  plans: PlanRow[]
  weighted_completion: number
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TIERS: [number, number][] = [
  [100, 25],
  [85, 22],
  [70, 20],
  [50, 18],
  [0, 15],
]

function chatterPct(completionPct: number): number {
  for (const [threshold, pct] of TIERS) {
    if (completionPct >= threshold) return pct
  }
  return 15
}

function tierLabel(pct: number): { label: string; color: string } {
  if (pct >= 100) return { label: '25% — топ', color: 'text-emerald-400' }
  if (pct >= 85) return { label: '22%', color: 'text-emerald-400' }
  if (pct >= 70) return { label: '20%', color: 'text-sky-400' }
  if (pct >= 50) return { label: '18%', color: 'text-yellow-400' }
  return { label: '15% — риск', color: 'text-red-400' }
}

function completionBar(pct: number) {
  const capped = Math.min(pct, 100)
  const color =
    pct >= 100 ? 'bg-emerald-500' :
    pct >= 70  ? 'bg-sky-500' :
    pct >= 50  ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="w-full bg-slate-700 rounded-full h-1.5 mt-1">
      <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${capped}%` }} />
    </div>
  )
}

function fmt(n: number) {
  return '$' + n.toLocaleString('en', { maximumFractionDigits: 0 })
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function PlansPage() {
  const { month, year } = useMonthStore()
  const qc = useQueryClient()

  const [edits, setEdits] = useState<Record<string, number>>({})
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(false)

  const { data, isLoading, error } = useQuery<PlansResponse>({
    queryKey: ['plans', month, year],
    queryFn: () => api.get(`/api/v1/plans?month=${month}&year=${year}`).then((r) => r.data),
  })

  // Reset edits when month/year changes
  useEffect(() => { setEdits({}) }, [month, year])

  const getPlanValue = (model: string, dbAmount: number) =>
    edits[model] !== undefined ? edits[model] : dbAmount

  const handleSave = async () => {
    setSaving(true)
    setSaveError(false)
    try {
      const promises = Object.entries(edits).map(([model, plan_amount]) =>
        api.put(`/api/v1/plans/${year}/${month}`, { model, plan_amount })
      )
      await Promise.all(promises)
      qc.invalidateQueries({ queryKey: ['plans', month, year] })
      qc.invalidateQueries({ queryKey: ['chatters', month, year] })
      setEdits({})
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setSaveError(true)
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = Object.keys(edits).length > 0

  // ── Render ────────────────────────────────────────────────────────────────

  if (isLoading) return (
    <div className="flex flex-col h-full">
      <Header title="Планы по моделям" />
      <div className="flex-1 p-6 space-y-3 overflow-y-auto">
        {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-16 bg-slate-800 rounded-xl" />)}
      </div>
    </div>
  )

  const plans = data?.plans ?? []
  const weighted = data?.weighted_completion ?? 0
  const modelsWithPlan = plans.filter(p => getPlanValue(p.model, p.plan_amount) > 0)

  return (
    <div className="flex flex-col h-full">
      <Header title="Планы по моделям" />
      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {error && (
          <div className="flex items-center gap-2 p-4 rounded-xl bg-red-900/20 border border-red-700/40 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Не удалось загрузить данные
          </div>
        )}

        {/* Summary bar */}
        {modelsWithPlan.length > 0 && (
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">Выполнение плана</p>
              <p className={`text-2xl font-bold mt-1 ${weighted >= 100 ? 'text-emerald-400' : weighted >= 70 ? 'text-sky-400' : 'text-yellow-400'}`}>
                {weighted.toFixed(1)}%
              </p>
              {completionBar(weighted)}
            </div>
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">Тир чаттеров</p>
              <p className={`text-2xl font-bold mt-1 ${tierLabel(weighted).color}`}>
                {chatterPct(weighted)}%
              </p>
              <p className="text-xs text-slate-500 mt-1">от выручки</p>
            </div>
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">Моделей с планом</p>
              <p className="text-2xl font-bold text-slate-100 mt-1">{modelsWithPlan.length}</p>
              <p className="text-xs text-slate-500 mt-1">из {plans.length} моделей</p>
            </div>
          </div>
        )}

        {/* Plans table */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="grid grid-cols-12 px-4 py-3 bg-slate-700/30 text-xs font-semibold text-slate-400 uppercase tracking-wide border-b border-slate-700/50">
            <span className="col-span-4">Модель</span>
            <span className="col-span-2 text-right">Выручка</span>
            <span className="col-span-3 text-right">План ($)</span>
            <span className="col-span-2 text-right">Выполнение</span>
            <span className="col-span-1 text-right">Тир</span>
          </div>

          {plans.length === 0 ? (
            <div className="px-4 py-10 text-center text-slate-500 text-sm">
              Нет данных за выбранный месяц
            </div>
          ) : (
            plans.map((row) => {
              const planVal = getPlanValue(row.model, row.plan_amount)
              const completion = planVal > 0 ? Math.round((row.actual / planVal) * 100) : 0
              const tier = tierLabel(completion)
              const isEdited = edits[row.model] !== undefined

              return (
                <div key={row.model} className={`grid grid-cols-12 px-4 py-3 border-b border-slate-700/30 last:border-0 items-center hover:bg-slate-700/20 transition-colors ${isEdited ? 'bg-indigo-900/10' : ''}`}>
                  <div className="col-span-4">
                    <p className="text-sm font-medium text-slate-200 truncate">{row.model || '—'}</p>
                  </div>
                  <div className="col-span-2 text-right">
                    <p className="text-sm text-slate-300">{fmt(row.actual)}</p>
                  </div>
                  <div className="col-span-3 text-right">
                    <input
                      type="number"
                      min={0}
                      step={500}
                      value={planVal || ''}
                      placeholder="0"
                      onChange={(e) => {
                        const v = Number(e.target.value)
                        setEdits((prev) => ({ ...prev, [row.model]: v }))
                      }}
                      className="w-28 text-right bg-slate-700/80 border border-slate-600/50 hover:border-slate-500 focus:border-indigo-500 rounded-lg px-2 py-1 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-colors"
                    />
                  </div>
                  <div className="col-span-2 text-right">
                    {planVal > 0 ? (
                      <div>
                        <p className={`text-sm font-semibold ${completion >= 100 ? 'text-emerald-400' : completion >= 70 ? 'text-sky-400' : completion >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                          {completion}%
                        </p>
                        {completionBar(completion)}
                      </div>
                    ) : (
                      <p className="text-sm text-slate-600">—</p>
                    )}
                  </div>
                  <div className="col-span-1 text-right">
                    {planVal > 0 ? (
                      <p className={`text-xs font-medium ${tier.color}`}>{tier.label}</p>
                    ) : (
                      <p className="text-xs text-slate-600">—</p>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Tiers legend */}
        <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Тиры чаттеров</p>
          <div className="flex flex-wrap gap-3">
            {TIERS.map(([threshold, pct]) => (
              <div key={threshold} className="flex items-center gap-1.5 text-xs">
                <span className={`w-2 h-2 rounded-full ${pct === 25 ? 'bg-emerald-500' : pct >= 20 ? 'bg-sky-500' : pct >= 18 ? 'bg-yellow-500' : 'bg-red-500'}`} />
                <span className="text-slate-400">≥{threshold}% выполнения</span>
                <span className="text-slate-200 font-semibold">→ {pct}% чаттеру</span>
              </div>
            ))}
          </div>
        </div>

        {/* Save */}
        <div className="flex items-center gap-4">
          <button
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Сохранить планы
          </button>
          {hasChanges && !saving && (
            <span className="text-xs text-indigo-400">{Object.keys(edits).length} изменений</span>
          )}
          {saved && (
            <span className="flex items-center gap-1.5 text-emerald-400 text-sm">
              <CheckCircle2 className="h-4 w-4" /> Сохранено
            </span>
          )}
          {saveError && (
            <span className="flex items-center gap-1.5 text-red-400 text-sm">
              <AlertCircle className="h-4 w-4" /> Ошибка сохранения
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
