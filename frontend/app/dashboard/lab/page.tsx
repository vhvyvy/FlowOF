'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { useMonth } from '@/lib/hooks/useMonth'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { FlaskConical, Target, SlidersHorizontal, Zap } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Settings {
  model_percent: string
  chatter_percent: string
  admin_percent: string
  withdraw_percent: string
  use_withdraw: string
  use_retention: string
}

interface OverviewData {
  revenue: number
  expenses: number
  profit: number
  transactions_count: number
}

interface SimMetrics {
  revenue: number
  net: number
  margin: number
}

const RETENTION_PCT = 2.5

// ─── Helpers ──────────────────────────────────────────────────────────────────

function simulate(
  revenue: number,
  expenses: number,
  modelPct: number,
  chatterPct: number,
  adminPct: number,
  withdrawPct: number,
  useWithdraw: boolean,
  useRetention: boolean,
): SimMetrics {
  const chatter = (revenue * chatterPct) / 100
  const admin = (revenue * adminPct) / 100
  const model = (revenue * modelPct) / 100
  const withdraw = useWithdraw ? (revenue * withdrawPct) / 100 : 0
  const agencyBase = revenue - chatter - admin - model - withdraw
  const retention = useRetention ? ((model + chatter) * RETENTION_PCT) / 100 : 0
  const agency = agencyBase + retention
  const net = agency - expenses
  const margin = revenue > 0 ? (net / revenue) * 100 : 0
  return { revenue, net, margin }
}

function fmt(n: number) {
  return `$${n.toLocaleString('en', { maximumFractionDigits: 0 })}`
}

function delta(a: number, b: number) {
  const d = a - b
  return (
    <span className={d >= 0 ? 'text-emerald-400' : 'text-red-400'}>
      {d >= 0 ? '+' : ''}{fmt(d)}
    </span>
  )
}

// ─── Tab: Симуляция ──────────────────────────────────────────────────────────

function TabSimulation({
  curTxn, curRevenue, curExpenses, curAvg,
  modelPct, chatterPct, adminPct, withdrawPct,
  useWithdraw, useRetention,
}: {
  curTxn: number; curRevenue: number; curExpenses: number; curAvg: number
  modelPct: number; chatterPct: number; adminPct: number; withdrawPct: number
  useWithdraw: boolean; useRetention: boolean
}) {
  const [simTxn, setSimTxn] = useState(curTxn)
  const [simAvg, setSimAvg] = useState(Math.round(curAvg * 100) / 100)

  const simRevenue = simTxn * simAvg
  const baseMetrics = simulate(curRevenue, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)
  const simMetrics = simulate(simRevenue, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Измените количество транзакций и средний чек — посмотрите как изменится прибыль.</p>

      <div className="grid grid-cols-2 gap-6">
        <div className="space-y-2">
          <div className="flex justify-between">
            <label className="text-sm font-medium text-slate-300">Транзакций</label>
            <span className="text-indigo-400 font-bold">{simTxn.toLocaleString()}</span>
          </div>
          <input
            type="range" min={0} max={Math.max(curTxn * 3, 2000)} step={10}
            value={simTxn} onChange={(e) => setSimTxn(Number(e.target.value))}
            className="w-full accent-indigo-500 cursor-pointer"
          />
          <div className="flex justify-between text-xs text-slate-500">
            <span>0</span><span>Факт: {curTxn.toLocaleString()}</span><span>{Math.max(curTxn * 3, 2000).toLocaleString()}</span>
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex justify-between">
            <label className="text-sm font-medium text-slate-300">Средний чек</label>
            <span className="text-indigo-400 font-bold">${simAvg.toFixed(2)}</span>
          </div>
          <input
            type="range" min={0} max={Math.max(curAvg * 5, 500)} step={0.5}
            value={simAvg} onChange={(e) => setSimAvg(Number(e.target.value))}
            className="w-full accent-indigo-500 cursor-pointer"
          />
          <div className="flex justify-between text-xs text-slate-500">
            <span>$0</span><span>Факт: ${curAvg.toFixed(2)}</span><span>${Math.max(curAvg * 5, 500).toFixed(0)}</span>
          </div>
        </div>
      </div>

      <button
        onClick={() => { setSimTxn(curTxn); setSimAvg(Math.round(curAvg * 100) / 100) }}
        className="text-xs text-slate-500 hover:text-slate-300 underline transition-colors"
      >
        Сбросить к фактическим значениям
      </button>

      <div className="grid grid-cols-2 gap-4">
        <Card className="bg-slate-800/60 border-slate-700/50">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-400 font-medium uppercase tracking-wide">Факт</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-2">
            <div className="flex justify-between text-sm"><span className="text-slate-400">Выручка</span><span className="text-slate-200">{fmt(curRevenue)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Прибыль</span><span className="text-slate-200">{fmt(baseMetrics.net)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Маржа</span><span className="text-slate-200">{baseMetrics.margin.toFixed(1)}%</span></div>
          </CardContent>
        </Card>
        <Card className="bg-indigo-900/20 border-indigo-700/40">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-indigo-400 font-medium uppercase tracking-wide">Симуляция</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-2">
            <div className="flex justify-between text-sm"><span className="text-slate-400">Выручка</span><span className="text-slate-200">{fmt(simRevenue)} {delta(simRevenue, curRevenue)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Прибыль</span><span className="text-slate-200">{fmt(simMetrics.net)} {delta(simMetrics.net, baseMetrics.net)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Маржа</span><span className="text-slate-200">{simMetrics.margin.toFixed(1)}%</span></div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ─── Tab: Цели ───────────────────────────────────────────────────────────────

function TabGoals({
  curRevenue, curExpenses, curTxn, curAvg,
  modelPct, chatterPct, adminPct, withdrawPct,
  useWithdraw, useRetention,
}: {
  curRevenue: number; curExpenses: number; curTxn: number; curAvg: number
  modelPct: number; chatterPct: number; adminPct: number; withdrawPct: number
  useWithdraw: boolean; useRetention: boolean
}) {
  const baseMetrics = simulate(curRevenue, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)
  const [targetNet, setTargetNet] = useState(Math.round(Math.max(baseMetrics.net, curRevenue * 0.25)))

  const agencyBasePct = 100 - modelPct - chatterPct - adminPct - (useWithdraw ? withdrawPct : 0)
  const retentionAdd = useRetention ? ((modelPct + chatterPct) * (RETENTION_PCT / 100)) : 0
  const agencyPct = agencyBasePct + retentionAdd

  const reqRevenue = agencyPct > 0 ? ((targetNet + curExpenses) / (agencyPct / 100)) : 0
  const reqTxn = curAvg > 0 ? Math.ceil(reqRevenue / curAvg) : 0

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Введите желаемую чистую прибыль — рассчитаем нужную выручку и количество транзакций.</p>

      <div className="space-y-2">
        <div className="flex justify-between">
          <label className="text-sm font-medium text-slate-300">Целевая прибыль</label>
          <span className="text-indigo-400 font-bold">{fmt(targetNet)}</span>
        </div>
        <input
          type="range" min={-50000} max={Math.max(curRevenue * 0.5, 100000)} step={500}
          value={targetNet} onChange={(e) => setTargetNet(Number(e.target.value))}
          className="w-full accent-indigo-500 cursor-pointer"
        />
        <div className="flex justify-between text-xs text-slate-500">
          <span>-$50k</span>
          <span>Текущая: {fmt(baseMetrics.net)}</span>
          <span>${Math.max(curRevenue * 0.5, 100000).toLocaleString('en', {maximumFractionDigits: 0})}</span>
        </div>
      </div>

      {agencyPct <= 0 ? (
        <div className="p-4 rounded-lg bg-red-900/30 border border-red-700/40 text-red-400 text-sm">
          Сумма удержаний ≥ 100% — агентству ничего не остаётся. Исправьте настройки.
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: 'Нужная выручка', value: fmt(reqRevenue), sub: `Доля агентства: ${agencyPct.toFixed(1)}%` },
            { label: 'Транзакций', value: reqTxn.toLocaleString(), sub: `При среднем чеке $${curAvg.toFixed(2)}` },
            { label: 'Рост к факту', value: reqRevenue > curRevenue ? `+${((reqRevenue / curRevenue - 1) * 100).toFixed(1)}%` : `${((reqRevenue / curRevenue - 1) * 100).toFixed(1)}%`, sub: `Факт: ${fmt(curRevenue)}` },
          ].map(({ label, value, sub }) => (
            <Card key={label} className="bg-slate-800/60 border-slate-700/50">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-slate-400 uppercase tracking-wide">{label}</p>
                <p className="text-2xl font-bold text-slate-100 mt-1">{value}</p>
                <p className="text-xs text-slate-500 mt-1">{sub}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Tab: Чувствительность ───────────────────────────────────────────────────

function TabSensitivity({
  curRevenue, curExpenses,
  modelPct, chatterPct, adminPct, withdrawPct,
  useWithdraw, useRetention,
}: {
  curRevenue: number; curExpenses: number
  modelPct: number; chatterPct: number; adminPct: number; withdrawPct: number
  useWithdraw: boolean; useRetention: boolean
}) {
  const [simModel, setSimModel] = useState(modelPct)
  const [simChatter, setSimChatter] = useState(chatterPct)
  const [simAdmin, setSimAdmin] = useState(adminPct)
  const [simWithdraw, setSimWithdraw] = useState(withdrawPct)

  const base = simulate(curRevenue, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)
  const sim = simulate(curRevenue, curExpenses, simModel, simChatter, simAdmin, simWithdraw, useWithdraw, useRetention)

  const sliders = [
    { label: 'Модель %', value: simModel, onChange: setSimModel },
    { label: 'Чаттер %', value: simChatter, onChange: setSimChatter },
    { label: 'Админы %', value: simAdmin, onChange: setSimAdmin },
    { label: 'Вывод %', value: simWithdraw, onChange: setSimWithdraw },
  ]

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Измените проценты и посмотрите как это влияет на прибыль при текущей выручке.</p>

      <div className="grid grid-cols-2 gap-6">
        {sliders.map(({ label, value, onChange }) => (
          <div key={label} className="space-y-2">
            <div className="flex justify-between">
              <label className="text-sm font-medium text-slate-300">{label}</label>
              <span className="text-indigo-400 font-bold">{value}%</span>
            </div>
            <input
              type="range" min={0} max={60} step={1}
              value={value} onChange={(e) => onChange(Number(e.target.value))}
              className="w-full accent-indigo-500 cursor-pointer"
            />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card className="bg-slate-800/60 border-slate-700/50">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-slate-400 font-medium uppercase tracking-wide">Текущие % (из настроек)</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-2">
            <div className="flex justify-between text-sm"><span className="text-slate-400">Прибыль</span><span className="text-slate-200">{fmt(base.net)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Маржа</span><span className="text-slate-200">{base.margin.toFixed(1)}%</span></div>
          </CardContent>
        </Card>
        <Card className="bg-indigo-900/20 border-indigo-700/40">
          <CardHeader className="pb-2 pt-4 px-4">
            <CardTitle className="text-xs text-indigo-400 font-medium uppercase tracking-wide">Новые %</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-2">
            <div className="flex justify-between text-sm"><span className="text-slate-400">Прибыль</span><span className="text-slate-200">{fmt(sim.net)} {delta(sim.net, base.net)}</span></div>
            <div className="flex justify-between text-sm"><span className="text-slate-400">Маржа</span><span className="text-slate-200">{sim.margin.toFixed(1)}%</span></div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ─── Tab: Сценарии ────────────────────────────────────────────────────────────

function TabScenarios({
  curTxn, curAvg, curRevenue, curExpenses,
  modelPct, chatterPct, adminPct, withdrawPct,
  useWithdraw, useRetention,
}: {
  curTxn: number; curAvg: number; curRevenue: number; curExpenses: number
  modelPct: number; chatterPct: number; adminPct: number; withdrawPct: number
  useWithdraw: boolean; useRetention: boolean
}) {
  const baseMetrics = simulate(curRevenue, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)

  const scenarios = [
    { name: '+10% транзакций', multTxn: 1.10, multAvg: 1.0 },
    { name: '+20% транзакций', multTxn: 1.20, multAvg: 1.0 },
    { name: '+10% средний чек', multTxn: 1.0, multAvg: 1.10 },
    { name: '+20% средний чек', multTxn: 1.0, multAvg: 1.20 },
    { name: '+10% оба', multTxn: 1.10, multAvg: 1.10 },
    { name: '+20% оба', multTxn: 1.20, multAvg: 1.20 },
    { name: '−10% транзакций', multTxn: 0.90, multAvg: 1.0 },
    { name: '−15% оба', multTxn: 0.85, multAvg: 0.85 },
  ]

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Быстрые сценарии — сразу видно как изменится прибыль.</p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {scenarios.map(({ name, multTxn, multAvg }) => {
          const simRev = Math.round(curTxn * multTxn) * (curAvg * multAvg)
          const m = simulate(simRev, curExpenses, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention)
          const d = m.net - baseMetrics.net
          const isPositive = d >= 0
          return (
            <Card key={name} className="bg-slate-800/60 border-slate-700/50">
              <CardContent className="pt-4 pb-4">
                <p className="text-xs text-slate-400 font-medium">{name}</p>
                <p className="text-xl font-bold text-slate-100 mt-1">{fmt(m.net)}</p>
                <p className={`text-sm mt-0.5 ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                  {isPositive ? '+' : ''}{fmt(d)}
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'sim', label: 'Симуляция', icon: FlaskConical },
  { id: 'goals', label: 'Цели', icon: Target },
  { id: 'sens', label: 'Чувствительность %', icon: SlidersHorizontal },
  { id: 'scenarios', label: 'Сценарии', icon: Zap },
]

export default function LabPage() {
  const { month, year } = useMonth()
  const [activeTab, setActiveTab] = useState('sim')

  const { data: overview, isLoading: loadingOverview } = useQuery<OverviewData>({
    queryKey: ['overview', month, year],
    queryFn: () => api.get(`/api/v1/overview?month=${month}&year=${year}`).then((r) => r.data),
  })

  const { data: settingsData, isLoading: loadingSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/v1/settings').then((r) => r.data.settings as Settings),
  })

  if (loadingOverview || loadingSettings) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40 bg-slate-800" />
        <Skeleton className="h-10 w-full bg-slate-800" />
        <Skeleton className="h-64 w-full bg-slate-800" />
      </div>
    )
  }

  const curRevenue = overview?.revenue ?? 0
  const curExpenses = overview?.expenses ?? 0
  const curTxn = overview?.transactions_count ?? 0
  const curAvg = curTxn > 0 ? curRevenue / curTxn : 0

  const s = settingsData
  const modelPct = Number(s?.model_percent ?? 23)
  const chatterPct = Number(s?.chatter_percent ?? 25)
  const adminPct = Number(s?.admin_percent ?? 9)
  const withdrawPct = Number(s?.withdraw_percent ?? 6)
  const useWithdraw = (s?.use_withdraw ?? '1') === '1'
  const useRetention = (s?.use_retention ?? '1') === '1'

  const props = { curTxn, curRevenue, curExpenses, curAvg, modelPct, chatterPct, adminPct, withdrawPct, useWithdraw, useRetention }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Лаборатория</h1>
        <p className="text-sm text-slate-400 mt-1">Эксперименты с цифрами — симуляции, цели, сценарии</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1 border border-slate-700/50">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={cn(
              'flex items-center gap-2 flex-1 justify-center px-3 py-2 rounded-lg text-sm font-medium transition-all',
              activeTab === id
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <Card className="bg-slate-800/50 border-slate-700/50">
        <CardContent className="pt-6">
          {activeTab === 'sim' && <TabSimulation {...props} />}
          {activeTab === 'goals' && <TabGoals {...props} />}
          {activeTab === 'sens' && <TabSensitivity {...props} />}
          {activeTab === 'scenarios' && <TabScenarios {...props} />}
        </CardContent>
      </Card>
    </div>
  )
}
