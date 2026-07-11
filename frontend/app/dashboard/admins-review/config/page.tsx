'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useKpiConfig,
  useUpdateKpiConfig,
  type KpiConfigRow,
  type KpiConfigUpdatePayload,
} from '@/lib/hooks/useKpiConfig'
import {
  GUARDRAIL_METRIC_OPTIONS,
  METRIC_LABELS,
} from '@/lib/adminReviewLabels'
import { cn } from '@/lib/utils'

const METRIC_ORDER = [
  'ppv_open_rate',
  'rpc',
  'apv',
  'total_chats',
  'revenue',
] as const

function rowToPayload(row: KpiConfigRow): KpiConfigUpdatePayload {
  return {
    noise_threshold_pct: row.noise_threshold_pct,
    guardrail_metrics: [...row.guardrail_metrics],
    hold_days: row.hold_days,
    detect_to_result_ratio_min: row.detect_to_result_ratio_min,
    calibration_days: row.calibration_days,
  }
}

export default function KpiConfigPage() {
  const { data, isLoading } = useKpiConfig()
  const update = useUpdateKpiConfig()

  const [editRow, setEditRow] = useState<KpiConfigRow | null>(null)
  const [form, setForm] = useState<KpiConfigUpdatePayload | null>(null)
  const [toastMsg, setToastMsg] = useState<string | null>(null)

  const rows = [...(data ?? [])].sort(
    (a, b) =>
      METRIC_ORDER.indexOf(a.metric_type as (typeof METRIC_ORDER)[number]) -
      METRIC_ORDER.indexOf(b.metric_type as (typeof METRIC_ORDER)[number]),
  )

  function showToast(msg: string) {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  function openEdit(row: KpiConfigRow) {
    setEditRow(row)
    setForm(rowToPayload(row))
  }

  function closeEdit() {
    setEditRow(null)
    setForm(null)
  }

  function toggleGuardrail(metric: string) {
    if (!form || !editRow) return
    if (metric === editRow.metric_type) return
    const set = new Set(form.guardrail_metrics)
    if (set.has(metric)) set.delete(metric)
    else set.add(metric)
    setForm({ ...form, guardrail_metrics: [...set] })
  }

  const formValid =
    form != null &&
    form.noise_threshold_pct >= 0.01 &&
    form.noise_threshold_pct <= 100 &&
    form.hold_days >= 1 &&
    form.hold_days <= 60 &&
    form.detect_to_result_ratio_min >= 1 &&
    form.detect_to_result_ratio_min <= 50 &&
    form.calibration_days >= 1 &&
    form.calibration_days <= 90

  async function handleSave() {
    if (!editRow || !form || !formValid) return
    try {
      await update.mutateAsync({ metricType: editRow.metric_type, body: form })
      showToast(
        `Настройки ${METRIC_LABELS[editRow.metric_type] ?? editRow.metric_type} обновлены`,
      )
      closeEdit()
    } catch {
      showToast('Ошибка сохранения настроек')
    }
  }

  return (
    <div className="p-6 max-w-[1200px] mx-auto">
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-700 border border-slate-600 rounded-xl px-4 py-3 shadow-2xl text-sm text-slate-100 max-w-xs">
          {toastMsg}
        </div>
      )}

      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-100">Настройки KPI</h1>
        <p className="text-xs text-slate-500 mt-1">
          Пороги и параметры для расчёта KPI-балла админов
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-700/50">
          <table className="w-full min-w-[960px] text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-800/60">
                <th className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase">
                  Метрика
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase">
                  Шум, %
                </th>
                <th className="px-3 py-3 text-left text-xs font-semibold text-slate-500 uppercase">
                  Guardrail
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase">
                  HOLD
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase">
                  Мин. D:R
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase">
                  Калибр.
                </th>
                <th className="px-3 py-3 text-right text-xs font-semibold text-slate-500 uppercase">
                  Действие
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.metric_type} className="border-b border-slate-700/30">
                  <td className="px-4 py-3 font-medium text-slate-100">
                    {METRIC_LABELS[row.metric_type] ?? row.metric_type}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-300 tabular-nums">
                    {row.noise_threshold_pct}
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1">
                      {row.guardrail_metrics.length === 0 ? (
                        <span className="text-xs text-slate-600">—</span>
                      ) : (
                        row.guardrail_metrics.map((m) => (
                          <span
                            key={m}
                            className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20"
                          >
                            {METRIC_LABELS[m] ?? m}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right text-slate-300 tabular-nums">
                    {row.hold_days}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-300 tabular-nums">
                    {row.detect_to_result_ratio_min}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-300 tabular-nums">
                    {row.calibration_days}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-slate-400 hover:text-slate-200"
                      onClick={() => openEdit(row)}
                    >
                      Изменить
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editRow && form && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div
            className="bg-slate-900 border border-slate-700 rounded-xl p-5 max-w-lg w-full shadow-2xl space-y-4"
            data-testid="kpi-config-modal"
          >
            <h3 className="text-sm font-semibold text-slate-100">
              Изменить: {METRIC_LABELS[editRow.metric_type] ?? editRow.metric_type}
            </h3>

            <div>
              <label className="text-xs text-slate-500">Шум, %</label>
              <input
                type="number"
                min={0.01}
                max={100}
                step={0.1}
                value={form.noise_threshold_pct}
                onChange={(e) =>
                  setForm({ ...form, noise_threshold_pct: Number(e.target.value) })
                }
                className="mt-1 w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200"
              />
            </div>

            <div>
              <label className="text-xs text-slate-500">Guardrail-метрики</label>
              <div className="flex flex-wrap gap-2 mt-2">
                {GUARDRAIL_METRIC_OPTIONS.filter((m) => m !== editRow.metric_type).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => toggleGuardrail(m)}
                    className={cn(
                      'text-xs px-2.5 py-1 rounded-full border transition-colors',
                      form.guardrail_metrics.includes(m)
                        ? 'bg-amber-500/20 border-amber-500/40 text-amber-200'
                        : 'border-slate-700 text-slate-500 hover:text-slate-300',
                    )}
                  >
                    {METRIC_LABELS[m] ?? m}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-slate-500">HOLD, дней</label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={form.hold_days}
                  onChange={(e) => setForm({ ...form, hold_days: Number(e.target.value) })}
                  className="mt-1 w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500">Мин. D:R</label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={form.detect_to_result_ratio_min}
                  onChange={(e) =>
                    setForm({ ...form, detect_to_result_ratio_min: Number(e.target.value) })
                  }
                  className="mt-1 w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500">Калибровка, дней</label>
                <input
                  type="number"
                  min={1}
                  max={90}
                  value={form.calibration_days}
                  onChange={(e) =>
                    setForm({ ...form, calibration_days: Number(e.target.value) })
                  }
                  className="mt-1 w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200"
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end pt-2">
              <Button variant="outline" size="sm" disabled={update.isPending} onClick={closeEdit}>
                Отмена
              </Button>
              <Button
                size="sm"
                disabled={!formValid || update.isPending}
                className="bg-indigo-600 hover:bg-indigo-500"
                onClick={handleSave}
              >
                {update.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Сохранить'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
