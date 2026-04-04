'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
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

function SliderField({
  label, value, onChange, min = 0, max = 60, hint,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  hint?: string
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-slate-300">{label}</label>
        <span className="text-lg font-bold text-indigo-400">{value}%</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-indigo-500 cursor-pointer"
      />
      <div className="flex justify-between text-xs text-slate-500">
        <span>{min}%</span>
        <span>{max}%</span>
      </div>
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

function Toggle({
  label, checked, onChange, hint,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  hint?: string
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-slate-700/50 last:border-0">
      <div>
        <p className="text-sm font-medium text-slate-300">{label}</p>
        {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
          checked ? 'bg-indigo-500' : 'bg-slate-600'
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
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

  useEffect(() => {
    if (data) setLocal(data)
  }, [data])

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

  const totalPct = model + chatter + admin + (useWithdraw ? withdraw : 0)
  const agencyPct = 100 - totalPct + (useRetention ? (model + chatter) * 0.025 : 0)
  const overLimit = totalPct > 100

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48 bg-slate-800" />
        <Skeleton className="h-64 w-full bg-slate-800" />
        <Skeleton className="h-48 w-full bg-slate-800" />
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Настройки</h1>
        <p className="text-sm text-slate-400 mt-1">Экономическая модель агентства</p>
      </div>

      {/* Sliders */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardHeader className="pb-4">
          <CardTitle className="text-slate-100 text-base">Распределение выручки</CardTitle>
          <CardDescription className="text-slate-400">
            Укажите доли для каждого участника агентства
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <SliderField
            label="Модель %"
            value={model}
            onChange={(v) => set('model_percent', String(v))}
            hint="Доля модели от выручки"
          />
          <SliderField
            label="Чаттер %"
            value={chatter}
            onChange={(v) => set('chatter_percent', String(v))}
            hint="Доля чаттеров от выручки"
          />
          <SliderField
            label="Админы %"
            value={admin}
            onChange={(v) => set('admin_percent', String(v))}
            hint="Доля администраторов от выручки"
          />
          <SliderField
            label="Вывод %"
            value={withdraw}
            onChange={(v) => set('withdraw_percent', String(v))}
            hint="Комиссия за вывод средств"
          />
        </CardContent>
      </Card>

      {/* Toggles */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardHeader className="pb-4">
          <CardTitle className="text-slate-100 text-base">Дополнительные параметры</CardTitle>
        </CardHeader>
        <CardContent>
          <Toggle
            label="Учитывать комиссию вывода"
            checked={useWithdraw}
            onChange={(v) => set('use_withdraw', v ? '1' : '0')}
            hint={`${withdraw}% от выручки вычитается как комиссия платформы`}
          />
          <Toggle
            label="Удержание 2.5% (retention)"
            checked={useRetention}
            onChange={(v) => set('use_retention', v ? '1' : '0')}
            hint="2.5% возвращается агентству с долей модели и чаттера"
          />
        </CardContent>
      </Card>

      {/* Summary */}
      <Card className={`border ${overLimit ? 'bg-red-900/20 border-red-700/50' : 'bg-slate-800/50 border-slate-700/50'}`}>
        <CardContent className="pt-4">
          <p className="text-sm font-medium text-slate-300 mb-3">Текущая структура</p>
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <span className="text-slate-400">Модель</span>
            <span className="text-slate-200 text-right">{model}%</span>
            <span className="text-slate-400">Чаттеры</span>
            <span className="text-slate-200 text-right">{chatter}%</span>
            <span className="text-slate-400">Админы</span>
            <span className="text-slate-200 text-right">{admin}%</span>
            {useWithdraw && (
              <>
                <span className="text-slate-400">Вывод</span>
                <span className="text-slate-200 text-right">{withdraw}%</span>
              </>
            )}
            <span className="text-slate-400 border-t border-slate-700 pt-2 mt-1">Итого удержаний</span>
            <span className={`text-right border-t border-slate-700 pt-2 mt-1 font-semibold ${overLimit ? 'text-red-400' : 'text-slate-200'}`}>
              {totalPct}%
            </span>
            <span className="text-slate-400">Агентству остаётся</span>
            <span className={`text-right font-bold ${agencyPct < 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              ≈{agencyPct.toFixed(1)}%
            </span>
          </div>

          {overLimit && (
            <div className="flex items-center gap-2 mt-3 text-red-400 text-sm">
              <AlertCircle className="h-4 w-4 shrink-0" />
              Сумма процентов превышает 100% — проверьте значения
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => mutation.mutate(local)}
          disabled={mutation.isPending || overLimit}
          className="bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          {mutation.isPending ? (
            <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          Сохранить настройки
        </Button>

        {saved && (
          <div className="flex items-center gap-1.5 text-emerald-400 text-sm">
            <CheckCircle2 className="h-4 w-4" />
            Сохранено
          </div>
        )}

        {mutation.isError && (
          <div className="flex items-center gap-1.5 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4" />
            Ошибка сохранения
          </div>
        )}
      </div>
    </div>
  )
}
