'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trophy, CheckCircle2, Clock, RefreshCw } from 'lucide-react'
import { Header } from '@/components/layout/Header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { LeagueBadge } from '@/components/mmr/LeagueBadge'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ──────────────────────────────────────────────────────────────────

interface LeaderboardRow {
  chatter_id: number
  name: string
  current_mmr: number
  peak_mmr: number
  current_league: string | null
  days_active: number
  calibration_complete: boolean
  rank: number
}

interface Season {
  id: number
  name: string
  start_date: string
  end_date: string
  is_active: boolean
  closed_at: string | null
}

interface SeasonResult {
  rank: number
  chatter_id: number
  chatter_name: string
  final_mmr: number
  final_league: string | null
  prize_amount: number
  prize_paid: boolean
  prize_paid_at: string | null
}

interface MmrSettings {
  fin_overperform_threshold: number
  fin_underperform_threshold: number
  fin_overperform_points: number
  fin_perform_points: number
  fin_underperform_points: number
  fin_empty_shift_points: number
  kpi_threshold_high: number
  kpi_threshold_low: number
  kpi_high_points: number
  kpi_low_points: number
  kpi_enabled: boolean
  season_carry_over: number
  prize_1st: number
  prize_2nd: number
  prize_3rd: number
  calibration_days: number
}

// ── Helpers ────────────────────────────────────────────────────────────────

function RankBadge({ rank }: { rank: number }) {
  const colors: Record<number, string> = {
    1: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
    2: 'bg-slate-400/20 text-slate-300 border border-slate-400/30',
    3: 'bg-amber-700/20 text-amber-600 border border-amber-700/30',
  }
  return (
    <span className={cn('inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold',
      colors[rank] ?? 'bg-slate-700/50 text-slate-400')}>
      {rank}
    </span>
  )
}

function FieldGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
      <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">{label}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">{children}</div>
    </div>
  )
}

function NumInput({
  label, value, fieldKey, onChange,
}: { label: string; value: number; fieldKey: string; onChange: (k: string, v: number) => void }) {
  return (
    <div>
      <label className="text-xs text-slate-500 block mb-1">{label}</label>
      <input
        type="number"
        className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
        value={value}
        onChange={e => onChange(fieldKey, Number(e.target.value))}
      />
    </div>
  )
}

// ── Tab: Лидерборд ─────────────────────────────────────────────────────────

function LeaderboardTab() {
  const { data, isLoading } = useQuery<{ season: Season | null; rows: LeaderboardRow[] }>({
    queryKey: ['mmr-leaderboard'],
    queryFn: () => api.get('/api/v1/mmr/leaderboard').then(r => r.data),
  })

  const season = data?.season
  const rows = data?.rows ?? []

  return (
    <div className="space-y-4">
      {season && (
        <div className="flex items-center gap-3 text-sm">
          <span className="bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 px-3 py-1 rounded-full text-xs font-medium">
            {season.is_active ? '▶ Активный' : 'Завершён'}
          </span>
          <span className="text-slate-400">{season.name}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500 text-xs">{season.start_date} — {season.end_date}</span>
        </div>
      )}

      {isLoading ? (
        <div className="bg-slate-800/50 rounded-xl p-8 text-center">
          <p className="text-slate-500 text-sm">Загрузка…</p>
        </div>
      ) : rows.length === 0 ? (
        <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-10 text-center">
          <Trophy className="h-8 w-8 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-400 text-sm">Нет данных. Запустите пересчёт в разделе Настройки.</p>
        </div>
      ) : (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-700/20">
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide w-12">#</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Чаттер</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Лига</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">MMR</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Пик</th>
                <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Дней</th>
                <th className="text-center px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Статус</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {rows.map(r => (
                <tr key={r.chatter_id} className="hover:bg-slate-700/20 transition-colors">
                  <td className="px-4 py-3"><RankBadge rank={r.rank} /></td>
                  <td className="px-4 py-3 text-sm font-medium text-slate-200">{r.name}</td>
                  <td className="px-4 py-3"><LeagueBadge league={r.current_league} /></td>
                  <td className="px-4 py-3 text-right text-sm font-bold text-indigo-300">{r.current_mmr}</td>
                  <td className="px-4 py-3 text-right text-sm text-slate-400">{r.peak_mmr}</td>
                  <td className="px-4 py-3 text-right text-sm text-slate-400">{r.days_active}</td>
                  <td className="px-4 py-3 text-center">
                    {r.calibration_complete ? (
                      <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">Активен</span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-700/50 text-slate-400">
                        Калибровка {r.days_active}/14
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Tab: Сезоны ───────────────────────────────────────────────────────────

function SeasonsTab() {
  const [selectedSeason, setSelectedSeason] = useState<number | null>(null)
  const { data: seasonsData } = useQuery<{ seasons: Season[] }>({
    queryKey: ['mmr-seasons'],
    queryFn: () => api.get('/api/v1/mmr/seasons').then(r => r.data),
  })
  const { data: resultsData } = useQuery<{ season: Season; results: SeasonResult[] }>({
    queryKey: ['mmr-season-results', selectedSeason],
    queryFn: () => api.get(`/api/v1/mmr/seasons/${selectedSeason}/results`).then(r => r.data),
    enabled: !!selectedSeason,
  })
  const seasons = seasonsData?.seasons ?? []

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="space-y-2">
        {seasons.length === 0 && (
          <p className="text-sm text-slate-500 py-4">Сезонов ещё нет. Запустите пересчёт.</p>
        )}
        {seasons.map(s => (
          <button
            key={s.id}
            onClick={() => !s.is_active && setSelectedSeason(s.id)}
            className={cn(
              'w-full text-left px-4 py-3 rounded-xl border transition-colors',
              s.is_active
                ? 'bg-indigo-500/10 border-indigo-500/30 cursor-default'
                : selectedSeason === s.id
                ? 'bg-slate-700 border-slate-500'
                : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-700/50',
            )}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-200">{s.name}</span>
              {s.is_active
                ? <span className="text-xs text-indigo-400">Активный</span>
                : <span className="text-xs text-slate-500">Завершён</span>}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{s.start_date} — {s.end_date}</p>
          </button>
        ))}
      </div>

      <div className="lg:col-span-2">
        {!selectedSeason ? (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-8 text-center h-full flex items-center justify-center">
            <p className="text-slate-500 text-sm">Выберите завершённый сезон для просмотра результатов</p>
          </div>
        ) : resultsData ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-700/40">
              <p className="text-sm font-semibold text-slate-300">{resultsData.season.name} — Результаты</p>
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/40 bg-slate-700/20">
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">#</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Чаттер</th>
                  <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Лига</th>
                  <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase">MMR</th>
                  <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase">Приз</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {resultsData.results.map(r => (
                  <tr key={r.chatter_id} className="hover:bg-slate-700/20">
                    <td className="px-4 py-3"><RankBadge rank={r.rank} /></td>
                    <td className="px-4 py-3 text-sm font-medium text-slate-200">{r.chatter_name}</td>
                    <td className="px-4 py-3"><LeagueBadge league={r.final_league} /></td>
                    <td className="px-4 py-3 text-right text-sm font-bold text-indigo-300">{r.final_mmr}</td>
                    <td className="px-4 py-3 text-right text-sm">
                      {r.prize_amount > 0 ? (
                        <span className="text-emerald-400 font-medium">${r.prize_amount.toFixed(0)}</span>
                      ) : (
                        <span className="text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ── Tab: Настройки ────────────────────────────────────────────────────────

function SettingsTab() {
  const qc = useQueryClient()
  const [recalcDate, setRecalcDate] = useState(new Date().toISOString().slice(0, 10))
  const [recalcResult, setRecalcResult] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // Range recalculation state
  const today = new Date().toISOString().slice(0, 10)
  const firstOfMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10)
  const [rangeFrom, setRangeFrom] = useState(firstOfMonth)
  const [rangeTo, setRangeTo] = useState(today)
  const [rangeRunning, setRangeRunning] = useState(false)
  const [rangeResult, setRangeResult] = useState<{ success: boolean; days: number; events: number; errors: string[] } | null>(null)

  const { data: settings } = useQuery<MmrSettings>({
    queryKey: ['mmr-settings'],
    queryFn: () => api.get('/api/v1/mmr/settings').then(r => r.data),
  })
  const [form, setForm] = useState<Partial<MmrSettings>>({})

  const merged = { ...settings, ...form } as MmrSettings

  const handleChange = (k: string, v: number) => setForm(prev => ({ ...prev, [k]: v }))

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.put('/api/v1/mmr/settings', form)
      qc.invalidateQueries({ queryKey: ['mmr-settings'] })
      setForm({})
    } finally {
      setSaving(false)
    }
  }

  const handleRecalc = async () => {
    setRecalcResult(null)
    try {
      const res = await api.post('/api/v1/mmr/recalculate', { date: recalcDate })
      const d = res.data
      setRecalcResult(`Успешно: ${d.events_created} событий, сезон «${d.season_name}»`)
      qc.invalidateQueries({ queryKey: ['mmr-leaderboard'] })
    } catch {
      setRecalcResult('Ошибка пересчёта')
    }
  }

  const handleRangeRecalc = async () => {
    setRangeResult(null)
    setRangeRunning(true)
    try {
      const res = await api.post('/api/v1/mmr/recalculate-range', {
        date_from: rangeFrom,
        date_to: rangeTo,
      })
      const d = res.data
      setRangeResult({ success: d.success, days: d.days_processed, events: d.total_events, errors: d.errors ?? [] })
      qc.invalidateQueries({ queryKey: ['mmr-leaderboard'] })
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка пересчёта диапазона'
      setRangeResult({ success: false, days: 0, events: 0, errors: [msg] })
    } finally {
      setRangeRunning(false)
    }
  }

  if (!settings) return <p className="text-slate-500 text-sm">Загрузка…</p>

  return (
    <div className="space-y-5">
      {/* Ручной пересчёт */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Пересчитать день</p>
        <div className="flex items-center gap-3">
          <input
            type="date"
            value={recalcDate}
            onChange={e => setRecalcDate(e.target.value)}
            className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
          />
          <button
            onClick={handleRecalc}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Пересчитать
          </button>
        </div>
        {recalcResult && (
          <p className={cn('mt-3 text-sm', recalcResult.startsWith('Успешно') ? 'text-emerald-400' : 'text-red-400')}>
            {recalcResult}
          </p>
        )}
      </div>

      {/* Range recalculation */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Пересчитать диапазон</p>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">с</span>
            <input
              type="date"
              value={rangeFrom}
              onChange={e => setRangeFrom(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">по</span>
            <input
              type="date"
              value={rangeTo}
              onChange={e => setRangeTo(e.target.value)}
              className="bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            onClick={handleRangeRecalc}
            disabled={rangeRunning}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', rangeRunning && 'animate-spin')} />
            {rangeRunning ? 'Обрабатываем…' : 'Пересчитать диапазон'}
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2">Максимум 90 дней. Дефолт: первое число месяца → сегодня.</p>

        {rangeRunning && (
          <div className="mt-3 flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-indigo-400" />
            Идёт пересчёт, это может занять несколько секунд…
          </div>
        )}

        {rangeResult && (
          <div className={cn('mt-3 rounded-lg p-3 text-sm', rangeResult.success ? 'bg-emerald-500/10 border border-emerald-500/20' : 'bg-red-500/10 border border-red-500/20')}>
            {rangeResult.success ? (
              <div className="space-y-1">
                <p className="text-emerald-400 font-medium">
                  ✓ Обработано {rangeResult.days} дней, создано {rangeResult.events} событий
                </p>
                <button
                  onClick={() => qc.invalidateQueries({ queryKey: ['mmr-leaderboard'] })}
                  className="text-xs text-indigo-400 hover:text-indigo-300 underline"
                >
                  Обновить лидерборд
                </button>
              </div>
            ) : (
              <div>
                <p className="text-red-400 font-medium mb-1">Ошибка пересчёта</p>
                {rangeResult.errors.map((e, i) => (
                  <p key={i} className="text-xs text-red-300/70">{e}</p>
                ))}
                {rangeResult.days > 0 && (
                  <p className="text-xs text-slate-400 mt-1">Обработано до ошибки: {rangeResult.days} дн., {rangeResult.events} событий</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <FieldGroup label="Финансовая часть">
        <NumInput label="Порог перевыполнения" value={merged.fin_overperform_threshold ?? 1.10} fieldKey="fin_overperform_threshold" onChange={handleChange} />
        <NumInput label="Порог недовыполнения" value={merged.fin_underperform_threshold ?? 0.90} fieldKey="fin_underperform_threshold" onChange={handleChange} />
        <NumInput label="+MMR перевыполнение" value={merged.fin_overperform_points ?? 25} fieldKey="fin_overperform_points" onChange={handleChange} />
        <NumInput label="+MMR выполнение" value={merged.fin_perform_points ?? 15} fieldKey="fin_perform_points" onChange={handleChange} />
        <NumInput label="MMR недовыполнение" value={merged.fin_underperform_points ?? -15} fieldKey="fin_underperform_points" onChange={handleChange} />
        <NumInput label="MMR пустая смена" value={merged.fin_empty_shift_points ?? -15} fieldKey="fin_empty_shift_points" onChange={handleChange} />
      </FieldGroup>

      <FieldGroup label="KPI (Onlymonster)">
        <NumInput label="Порог KPI высокий" value={merged.kpi_threshold_high ?? 1.15} fieldKey="kpi_threshold_high" onChange={handleChange} />
        <NumInput label="Порог KPI низкий" value={merged.kpi_threshold_low ?? 0.85} fieldKey="kpi_threshold_low" onChange={handleChange} />
        <NumInput label="+MMR KPI высокий" value={merged.kpi_high_points ?? 5} fieldKey="kpi_high_points" onChange={handleChange} />
        <NumInput label="MMR KPI низкий" value={merged.kpi_low_points ?? -5} fieldKey="kpi_low_points" onChange={handleChange} />
        <div className="flex items-center gap-2 col-span-2">
          <input
            type="checkbox"
            id="kpi_enabled"
            checked={merged.kpi_enabled ?? true}
            onChange={e => setForm(p => ({ ...p, kpi_enabled: e.target.checked }))}
            className="accent-indigo-500"
          />
          <label htmlFor="kpi_enabled" className="text-sm text-slate-300">KPI включён</label>
        </div>
      </FieldGroup>

      <FieldGroup label="Сезоны и призы">
        <NumInput label="Перенос MMR %" value={(merged.season_carry_over ?? 0.5) * 100} fieldKey="season_carry_over" onChange={(k, v) => handleChange(k, v / 100)} />
        <NumInput label="Калибровка (дней)" value={merged.calibration_days ?? 14} fieldKey="calibration_days" onChange={handleChange} />
        <NumInput label="Приз 1 место ($)" value={merged.prize_1st ?? 200} fieldKey="prize_1st" onChange={handleChange} />
        <NumInput label="Приз 2 место ($)" value={merged.prize_2nd ?? 150} fieldKey="prize_2nd" onChange={handleChange} />
        <NumInput label="Приз 3 место ($)" value={merged.prize_3rd ?? 100} fieldKey="prize_3rd" onChange={handleChange} />
      </FieldGroup>

      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving || Object.keys(form).length === 0}
          className="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white text-sm rounded-lg transition-colors"
        >
          {saving ? 'Сохранение…' : 'Сохранить настройки'}
        </button>
      </div>
    </div>
  )
}

// ── Tab: Призы ────────────────────────────────────────────────────────────

function PrizesTab() {
  const qc = useQueryClient()
  const { data: seasonsData } = useQuery<{ seasons: Season[] }>({
    queryKey: ['mmr-seasons'],
    queryFn: () => api.get('/api/v1/mmr/seasons').then(r => r.data),
  })
  const seasons = (seasonsData?.seasons ?? []).filter(s => !s.is_active)
  const [selectedSeason, setSelectedSeason] = useState<number | null>(null)
  const sid = selectedSeason ?? seasons[0]?.id

  const { data: resultsData, isLoading } = useQuery<{ season: Season; results: SeasonResult[] }>({
    queryKey: ['mmr-season-results', sid],
    queryFn: () => api.get(`/api/v1/mmr/seasons/${sid}/results`).then(r => r.data),
    enabled: !!sid,
  })

  const markPaid = useMutation({
    mutationFn: ({ season_id, chatter_id }: { season_id: number; chatter_id: number }) =>
      api.post(`/api/v1/mmr/seasons/${season_id}/mark-prize-paid/${chatter_id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mmr-season-results', sid] }),
  })

  if (seasons.length === 0) {
    return (
      <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-10 text-center">
        <p className="text-slate-400 text-sm">Завершённых сезонов ещё нет</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {seasons.map(s => (
          <button
            key={s.id}
            onClick={() => setSelectedSeason(s.id)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm transition-colors',
              (selectedSeason ?? seasons[0]?.id) === s.id
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
            )}
          >
            {s.name}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-slate-500 text-sm">Загрузка…</p>
      ) : resultsData ? (
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50 bg-slate-700/20">
                <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">#</th>
                <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Чаттер</th>
                <th className="text-left px-4 py-3 text-xs text-slate-400 uppercase">Лига</th>
                <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase">MMR</th>
                <th className="text-right px-4 py-3 text-xs text-slate-400 uppercase">Приз</th>
                <th className="text-center px-4 py-3 text-xs text-slate-400 uppercase">Выплата</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {resultsData.results.map(r => (
                <tr key={r.chatter_id} className="hover:bg-slate-700/20">
                  <td className="px-4 py-3"><RankBadge rank={r.rank} /></td>
                  <td className="px-4 py-3 text-sm font-medium text-slate-200">{r.chatter_name}</td>
                  <td className="px-4 py-3"><LeagueBadge league={r.final_league} /></td>
                  <td className="px-4 py-3 text-right text-sm font-bold text-indigo-300">{r.final_mmr}</td>
                  <td className="px-4 py-3 text-right">
                    {r.prize_amount > 0 ? (
                      <span className="text-sm font-semibold text-emerald-400">${r.prize_amount.toFixed(0)}</span>
                    ) : (
                      <span className="text-sm text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {r.prize_amount > 0 ? (
                      r.prize_paid ? (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Выплачено
                        </span>
                      ) : (
                        <button
                          onClick={() => markPaid.mutate({ season_id: sid!, chatter_id: r.chatter_id })}
                          disabled={markPaid.isPending}
                          className="text-xs px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-40"
                        >
                          Отметить выплачено
                        </button>
                      )
                    ) : (
                      <span className="text-slate-600 text-xs">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function RankingPage() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Рейтинг чаттеров" />
      <div className="flex-1 p-6 overflow-y-auto">
        <Tabs defaultValue="leaderboard" className="space-y-5">
          <TabsList className="bg-slate-800/80 border border-slate-700/50 p-1 rounded-xl">
            <TabsTrigger value="leaderboard" className="rounded-lg text-sm data-[state=active]:bg-slate-700 data-[state=active]:text-slate-100">
              Лидерборд
            </TabsTrigger>
            <TabsTrigger value="seasons" className="rounded-lg text-sm data-[state=active]:bg-slate-700 data-[state=active]:text-slate-100">
              Сезоны
            </TabsTrigger>
            <TabsTrigger value="settings" className="rounded-lg text-sm data-[state=active]:bg-slate-700 data-[state=active]:text-slate-100">
              Настройки
            </TabsTrigger>
            <TabsTrigger value="prizes" className="rounded-lg text-sm data-[state=active]:bg-slate-700 data-[state=active]:text-slate-100">
              Призы
            </TabsTrigger>
          </TabsList>

          <TabsContent value="leaderboard"><LeaderboardTab /></TabsContent>
          <TabsContent value="seasons"><SeasonsTab /></TabsContent>
          <TabsContent value="settings"><SettingsTab /></TabsContent>
          <TabsContent value="prizes"><PrizesTab /></TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
