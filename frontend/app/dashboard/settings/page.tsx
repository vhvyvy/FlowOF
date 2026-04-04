'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Header } from '@/components/layout/Header'
import { Skeleton } from '@/components/ui/skeleton'
import { Save, RefreshCw, AlertCircle, CheckCircle2 } from 'lucide-react'

interface Settings {
  model_percent: string
  chatter_percent: string
  admin_percent: string
  withdraw_percent: string
  use_withdraw: string
  use_retention: string
}

const DEFAULTS: Settings = {
  model_percent: '23',
  chatter_percent: '25',
  admin_percent: '9',
  withdraw_percent: '6',
  use_withdraw: '1',
  use_retention: '1',
}

function SliderRow({
  label, hint, value, onChange, max = 60,
}: {
  label: string; hint: string; value: number; onChange: (v: number) => void; max?: number
}) {
  return (
    <div className="py-4 border-b border-slate-700/40 last:border-0">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-medium text-slate-200">{label}</p>
          <p className="text-xs text-slate-500 mt-0.5">{hint}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            max={max}
            value={value}
            onChange={(e) => onChange(Math.min(max, Math.max(0, Number(e.target.value))))}
            className="w-14 text-right bg-slate-700 border border-slate-600 rounded-lg px-2 py-1 text-sm font-bold text-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <span className="text-sm text-slate-400 w-3">%</span>
        </div>
      </div>
      <div className="relative">
        <input
          type="range"
          min={0}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-2 rounded-full appearance-none cursor-pointer accent-indigo-500"
          style={{
            background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${(value / max) * 100}%, #334155 ${(value / max) * 100}%, #334155 100%)`
          }}
        />
      </div>
    </div>
  )
}

function ToggleRow({
  label, hint, checked, onChange,
}: {
  label: string; hint: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between py-4 border-b border-slate-700/40 last:border-0">
      <div>
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="text-xs text-slate-500 mt-0.5">{hint}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${checked ? 'bg-indigo-500' : 'bg-slate-600'}`}
      >
        <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform duration-200 mt-0.5 ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </button>
    </div>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const [local, setLocal] = useState<Settings>(DEFAULTS)
  const [saved, setSaved] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/v1/settings').then((r) => r.data.settings as Settings),
  })

  useEffect(() => { if (data) setLocal(data) }, [data])

  const mutation = useMutation({
    mutationFn: (s: Settings) => api.put('/api/v1/settings', s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const set = (key: keyof Settings, value: string) =>
    setLocal((prev) => ({ ...prev, [key]: value }))

  const model = Number(local.model_percent)
  const chatter = Number(local.chatter_percent)
  const admin = Number(local.admin_percent)
  const withdraw = Number(local.withdraw_percent)
  const useWithdraw = local.use_withdraw === '1'
  const useRetention = local.use_retention === '1'

  const totalDeductions = model + chatter + admin + (useWithdraw ? withdraw : 0)
  const retentionBonus = useRetention ? (model + chatter) * 0.025 : 0
  const agencyPct = 100 - totalDeductions + retentionBonus
  const overLimit = totalDeductions > 100

  if (isLoading) return (
    <div className="flex flex-col h-full">
      <Header title="Настройки" />
      <div className="flex-1 p-6 space-y-4 overflow-y-auto max-w-xl">
        {[1,2,3,4].map(i => <Skeleton key={i} className="h-20 bg-slate-800 rounded-xl" />)}
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <Header title="Настройки" />
      <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-xl space-y-6">

      {/* Sliders */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest pt-5 pb-2">Распределение выручки</p>
        <SliderRow label="Модель" hint="Доля модели от выручки" value={model} onChange={(v) => set('model_percent', String(v))} />
        <SliderRow label="Чаттеры" hint="Доля чаттеров от выручки" value={chatter} onChange={(v) => set('chatter_percent', String(v))} />
        <SliderRow label="Админы" hint="Доля администраторов" value={admin} onChange={(v) => set('admin_percent', String(v))} />
        <SliderRow label="Вывод" hint="Комиссия за вывод средств" value={withdraw} onChange={(v) => set('withdraw_percent', String(v))} />
      </div>

      {/* Toggles */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest pt-5 pb-2">Дополнительно</p>
        <ToggleRow
          label="Комиссия вывода"
          hint={`Учитывать ${withdraw}% от выручки как комиссию платформы`}
          checked={useWithdraw}
          onChange={(v) => set('use_withdraw', v ? '1' : '0')}
        />
        <ToggleRow
          label="Retention 2.5%"
          hint="Агентство получает 2.5% от доли модели и чаттера обратно"
          checked={useRetention}
          onChange={(v) => set('use_retention', v ? '1' : '0')}
        />
      </div>

      {/* Summary */}
      <div className={`rounded-xl border px-5 py-4 ${overLimit ? 'bg-red-900/20 border-red-700/50' : 'bg-slate-800/60 border-slate-700/50'}`}>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Структура</p>
        <div className="space-y-1.5 text-sm">
          {[
            { label: 'Модель', value: model },
            { label: 'Чаттеры', value: chatter },
            { label: 'Админы', value: admin },
            ...(useWithdraw ? [{ label: 'Вывод', value: withdraw }] : []),
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between">
              <span className="text-slate-400">{label}</span>
              <span className="text-slate-300">{value}%</span>
            </div>
          ))}
          <div className="flex justify-between pt-2 mt-2 border-t border-slate-700">
            <span className="text-slate-400">Итого удержаний</span>
            <span className={`font-semibold ${overLimit ? 'text-red-400' : 'text-slate-200'}`}>{totalDeductions}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Агентству остаётся</span>
            <span className={`font-bold text-base ${agencyPct < 0 ? 'text-red-400' : 'text-emerald-400'}`}>≈{agencyPct.toFixed(1)}%</span>
          </div>
        </div>
        {overLimit && (
          <div className="flex items-center gap-2 mt-3 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Сумма превышает 100% — проверьте значения
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => mutation.mutate(local)}
          disabled={mutation.isPending || overLimit}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
        >
          {mutation.isPending
            ? <RefreshCw className="h-4 w-4 animate-spin" />
            : <Save className="h-4 w-4" />}
          Сохранить
        </button>
        {saved && (
          <span className="flex items-center gap-1.5 text-emerald-400 text-sm">
            <CheckCircle2 className="h-4 w-4" /> Сохранено
          </span>
        )}
        {mutation.isError && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4" /> Ошибка
          </span>
        )}
      </div>
      </div>
      </div>
    </div>
  )
}
