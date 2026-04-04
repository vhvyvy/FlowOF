'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { FlaskConical, Target, SlidersHorizontal, Zap } from 'lucide-react'

// ─── Types & helpers ──────────────────────────────────────────────────────────

interface Settings { model_percent: string; chatter_percent: string; admin_percent: string; withdraw_percent: string; use_withdraw: string; use_retention: string }
interface OverviewData { revenue: number; expenses: number; profit: number; transactions_count: number }

const RETENTION = 2.5

function calcNet(rev: number, exp: number, m: number, c: number, a: number, w: number, uw: boolean, ur: boolean) {
  const withdraw = uw ? rev * w / 100 : 0
  const agencyBase = rev - rev * m / 100 - rev * c / 100 - rev * a / 100 - withdraw
  const retention = ur ? (rev * m / 100 + rev * c / 100) * RETENTION / 100 : 0
  return agencyBase + retention - exp
}

function fmt(n: number) {
  return '$' + Math.round(Math.abs(n)).toLocaleString('en')
}

function DeltaBadge({ base, sim }: { base: number; sim: number }) {
  const d = sim - base
  if (Math.abs(d) < 0.5) return <span className="text-slate-500 text-xs">≈0</span>
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${d > 0 ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}>
      {d > 0 ? '+' : '−'}{fmt(d)}
    </span>
  )
}

function MetricRow({ label, base, sim }: { label: string; base: number; sim: number }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-700/40 last:border-0">
      <span className="text-sm text-slate-400">{label}</span>
      <div className="flex items-center gap-3">
        <span className="text-sm text-slate-500 w-20 text-right">{fmt(base)}</span>
        <span className="text-sm font-semibold text-slate-100 w-20 text-right">{fmt(sim)}</span>
        <div className="w-20 text-right"><DeltaBadge base={base} sim={sim} /></div>
      </div>
    </div>
  )
}

function SliderControl({ label, min, max, value, onChange, fmt: fmtFn }: {
  label: string; min: number; max: number; value: number; onChange: (v: number) => void; fmt?: (v: number) => string
}) {
  const display = fmtFn ? fmtFn(value) : value.toLocaleString('en')
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0
  return (
    <div className="space-y-2">
      <div className="flex justify-between items-baseline">
        <span className="text-sm font-medium text-slate-300">{label}</span>
        <span className="text-base font-bold text-indigo-300">{display}</span>
      </div>
      <input
        type="range" min={min} max={max} step={max > 1000 ? 10 : 0.5} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-2 rounded-full appearance-none cursor-pointer accent-indigo-500"
        style={{ background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${pct}%, #334155 ${pct}%, #334155 100%)` }}
      />
      <div className="flex justify-between text-xs text-slate-600">
        <span>{fmtFn ? fmtFn(min) : min.toLocaleString('en')}</span>
        <span>{fmtFn ? fmtFn(max) : max.toLocaleString('en')}</span>
      </div>
    </div>
  )
}

function StatCard({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: boolean }) {
  return (
    <div className={`rounded-xl border p-4 ${highlight ? 'bg-indigo-900/20 border-indigo-700/40' : 'bg-slate-800/60 border-slate-700/50'}`}>
      <p className="text-xs text-slate-400 uppercase tracking-wide font-medium">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${highlight ? 'text-indigo-300' : 'text-slate-100'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

// ─── Tab components ───────────────────────────────────────────────────────────

function TabSimulation({ rev, exp, txn, avg, m, c, a, w, uw, ur }: {
  rev: number; exp: number; txn: number; avg: number
  m: number; c: number; a: number; w: number; uw: boolean; ur: boolean
}) {
  const [simTxn, setSimTxn] = useState(txn)
  const [simAvg, setSimAvg] = useState(Math.round(avg * 100) / 100)
  const simRev = simTxn * simAvg
  const baseNet = calcNet(rev, exp, m, c, a, w, uw, ur)
  const simNet = calcNet(simRev, exp, m, c, a, w, uw, ur)
  const baseMargin = rev > 0 ? baseNet / rev * 100 : 0
  const simMargin = simRev > 0 ? simNet / simRev * 100 : 0

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Измените количество транзакций и средний чек — увидите как изменится прибыль.</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <SliderControl label="Транзакций" min={0} max={Math.max(txn * 3, 3000)} value={simTxn} onChange={setSimTxn} />
        <SliderControl label="Средний чек" min={0} max={Math.max(avg * 5, 300)} value={simAvg} onChange={setSimAvg} fmt={(v) => `$${v.toFixed(2)}`} />
      </div>
      <button onClick={() => { setSimTxn(txn); setSimAvg(Math.round(avg * 100) / 100) }}
        className="text-xs text-slate-500 hover:text-indigo-400 underline transition-colors">
        Сбросить к факту
      </button>

      {/* Table */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="grid grid-cols-4 px-4 py-2.5 bg-slate-700/30 text-xs font-semibold text-slate-400 uppercase tracking-wide">
          <span>Метрика</span>
          <span className="text-right">Факт</span>
          <span className="text-right">Симуляция</span>
          <span className="text-right">Изменение</span>
        </div>
        <div className="px-4">
          <MetricRow label="Выручка" base={rev} sim={simRev} />
          <MetricRow label="Прибыль" base={baseNet} sim={simNet} />
          <div className="flex items-center justify-between py-2.5">
            <span className="text-sm text-slate-400">Маржа</span>
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-500 w-20 text-right">{baseMargin.toFixed(1)}%</span>
              <span className="text-sm font-semibold text-slate-100 w-20 text-right">{simMargin.toFixed(1)}%</span>
              <div className="w-20 text-right"><DeltaBadge base={baseMargin} sim={simMargin} /></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function TabGoals({ rev, exp, txn, avg, m, c, a, w, uw, ur }: {
  rev: number; exp: number; txn: number; avg: number
  m: number; c: number; a: number; w: number; uw: boolean; ur: boolean
}) {
  const baseNet = calcNet(rev, exp, m, c, a, w, uw, ur)
  const [target, setTarget] = useState(Math.max(Math.round(baseNet / 1000) * 1000, 5000))

  const agencyBasePct = 100 - m - c - a - (uw ? w : 0)
  const retentionAdd = ur ? (m + c) * RETENTION / 100 : 0
  const agencyPct = agencyBasePct + retentionAdd
  const reqRev = agencyPct > 0 ? (target + exp) / (agencyPct / 100) : 0
  const reqTxn = avg > 0 ? Math.ceil(reqRev / avg) : 0
  const growth = rev > 0 ? (reqRev / rev - 1) * 100 : 0

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Введите желаемую прибыль — рассчитаем нужную выручку и количество транзакций.</p>
      <SliderControl
        label="Целевая прибыль"
        min={0}
        max={Math.max(rev * 0.6, 50000)}
        value={target}
        onChange={setTarget}
        fmt={(v) => '$' + Math.round(v).toLocaleString('en')}
      />
      {agencyPct <= 0 ? (
        <div className="p-4 rounded-xl bg-red-900/20 border border-red-700/40 text-red-400 text-sm">
          Сумма удержаний ≥ 100% — исправьте в Настройках.
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          <StatCard label="Нужная выручка" value={'$' + Math.round(reqRev).toLocaleString('en')} sub={`Доля агентства: ${agencyPct.toFixed(1)}%`} />
          <StatCard label="Транзакций" value={reqTxn.toLocaleString('en')} sub={`При среднем чеке $${avg.toFixed(2)}`} />
          <StatCard label="Рост к факту" value={(growth >= 0 ? '+' : '') + growth.toFixed(1) + '%'} sub={`Факт: $${Math.round(rev).toLocaleString('en')}`} highlight />
        </div>
      )}
    </div>
  )
}

function TabSensitivity({ rev, exp, m: baseM, c: baseC, a: baseA, w: baseW, uw, ur }: {
  rev: number; exp: number; m: number; c: number; a: number; w: number; uw: boolean; ur: boolean
}) {
  const [m, setM] = useState(baseM)
  const [c, setC] = useState(baseC)
  const [a, setA] = useState(baseA)
  const [w, setW] = useState(baseW)
  const baseNet = calcNet(rev, exp, baseM, baseC, baseA, baseW, uw, ur)
  const simNet = calcNet(rev, exp, m, c, a, w, uw, ur)
  const baseMargin = rev > 0 ? baseNet / rev * 100 : 0
  const simMargin = rev > 0 ? simNet / rev * 100 : 0

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-400">Измените проценты и посмотрите влияние на прибыль при текущей выручке {fmt(rev)}.</p>
      <div className="grid grid-cols-2 gap-x-8 gap-y-5">
        {[
          { label: 'Модель %', val: m, set: setM },
          { label: 'Чаттеры %', val: c, set: setC },
          { label: 'Админы %', val: a, set: setA },
          { label: 'Вывод %', val: w, set: setW },
        ].map(({ label, val, set }) => (
          <SliderControl key={label} label={label} min={0} max={60} value={val} onChange={set} fmt={(v) => v + '%'} />
        ))}
      </div>
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="grid grid-cols-4 px-4 py-2.5 bg-slate-700/30 text-xs font-semibold text-slate-400 uppercase tracking-wide">
          <span>Метрика</span>
          <span className="text-right">Текущие %</span>
          <span className="text-right">Новые %</span>
          <span className="text-right">Изменение</span>
        </div>
        <div className="px-4">
          <MetricRow label="Прибыль" base={baseNet} sim={simNet} />
          <div className="flex items-center justify-between py-2.5">
            <span className="text-sm text-slate-400">Маржа</span>
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-500 w-20 text-right">{baseMargin.toFixed(1)}%</span>
              <span className="text-sm font-semibold text-slate-100 w-20 text-right">{simMargin.toFixed(1)}%</span>
              <div className="w-20 text-right"><DeltaBadge base={baseMargin} sim={simMargin} /></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function TabScenarios({ rev, exp, txn, avg, m, c, a, w, uw, ur }: {
  rev: number; exp: number; txn: number; avg: number
  m: number; c: number; a: number; w: number; uw: boolean; ur: boolean
}) {
  const baseNet = calcNet(rev, exp, m, c, a, w, uw, ur)
  const scenarios = [
    { name: '+10% транзакций', tM: 1.10, aM: 1.00 },
    { name: '+20% транзакций', tM: 1.20, aM: 1.00 },
    { name: '+10% средний чек', tM: 1.00, aM: 1.10 },
    { name: '+20% средний чек', tM: 1.00, aM: 1.20 },
    { name: '+10% оба', tM: 1.10, aM: 1.10 },
    { name: '+20% оба', tM: 1.20, aM: 1.20 },
    { name: '−10% транзакций', tM: 0.90, aM: 1.00 },
    { name: '−15% оба', tM: 0.85, aM: 0.85 },
  ]

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">Быстрые сценарии относительно текущего месяца.</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {scenarios.map(({ name, tM, aM }) => {
          const simRev = Math.round(txn * tM) * (avg * aM)
          const simNet = calcNet(simRev, exp, m, c, a, w, uw, ur)
          const d = simNet - baseNet
          const positive = d >= 0
          return (
            <div key={name} className={`rounded-xl border p-4 ${positive ? 'bg-emerald-900/10 border-emerald-700/30' : 'bg-red-900/10 border-red-700/30'}`}>
              <p className="text-xs text-slate-400 font-medium leading-tight">{name}</p>
              <p className="text-lg font-bold text-slate-100 mt-2">{fmt(simNet)}</p>
              <p className={`text-sm mt-0.5 font-medium ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
                {positive ? '+' : '−'}{fmt(d)}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'sim', label: 'Симуляция', icon: FlaskConical },
  { id: 'goals', label: 'Цели', icon: Target },
  { id: 'sens', label: 'Чувствительность', icon: SlidersHorizontal },
  { id: 'scenarios', label: 'Сценарии', icon: Zap },
]

export default function LabPage() {
  const { month, year } = useMonthStore()
  const [activeTab, setActiveTab] = useState('sim')

  const { data: overview, isLoading: lo } = useQuery<OverviewData>({
    queryKey: ['overview', month, year],
    queryFn: () => api.get(`/api/v1/overview?month=${month}&year=${year}`).then((r) => r.data),
  })

  const { data: settingsData, isLoading: ls } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/v1/settings').then((r) => r.data.settings as Settings),
  })

  if (lo || ls) return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-40 bg-slate-800" />
      <Skeleton className="h-12 w-full bg-slate-800" />
      <Skeleton className="h-72 w-full bg-slate-800" />
    </div>
  )

  const rev = overview?.revenue ?? 0
  const exp = overview?.expenses ?? 0
  const txn = overview?.transactions_count ?? 0
  const avg = txn > 0 ? rev / txn : 0
  const s = settingsData
  const m = Number(s?.model_percent ?? 23)
  const c = Number(s?.chatter_percent ?? 25)
  const a = Number(s?.admin_percent ?? 9)
  const w = Number(s?.withdraw_percent ?? 6)
  const uw = (s?.use_withdraw ?? '1') === '1'
  const ur = (s?.use_retention ?? '1') === '1'
  const props = { rev, exp, txn, avg, m, c, a, w, uw, ur }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Лаборатория</h1>
        <p className="text-sm text-slate-400 mt-1">Симуляции, цели, сценарии — эксперименты с цифрами</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-slate-800/60 rounded-xl border border-slate-700/50">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setActiveTab(id)}
            className={cn(
              'flex items-center justify-center gap-2 flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all',
              activeTab === id ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/60'
            )}>
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-6">
        {activeTab === 'sim' && <TabSimulation {...props} />}
        {activeTab === 'goals' && <TabGoals {...props} />}
        {activeTab === 'sens' && <TabSensitivity {...props} />}
        {activeTab === 'scenarios' && <TabScenarios {...props} />}
      </div>
    </div>
  )
}
