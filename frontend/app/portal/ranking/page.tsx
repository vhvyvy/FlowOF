'use client'

import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, Dot,
} from 'recharts'
import { TrendingUp, TrendingDown, Trophy, CalendarDays } from 'lucide-react'
import { LeagueBadge } from '@/components/mmr/LeagueBadge'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ──────────────────────────────────────────────────────────────────

interface MmrMain {
  has_season: boolean
  season_name?: string
  season_end_date?: string
  season_days_left?: number
  current_mmr: number
  peak_mmr: number
  current_league: string | null
  calibration_complete: boolean
  calibration_days: number
  calibration_days_left: number
  days_active: number
  rank: number
  total_chatters: number
  next_league: string | null
  mmr_to_next: number | null
  prize_info: { '1st': number; '2nd': number; '3rd': number }
}

interface FinanceEvent {
  model_name: string | null
  shift_name: string | null
  plan: number | null
  revenue: number | null
  performance_pct: number | null
  points: number
  category: string
  description: string
}

interface KpiMetric {
  name: string | null
  value: number | null
  avg: number | null
  pct: number | null
  points: number
  direction: 'up' | 'down'
  category: string
}

interface KpiSummary {
  metrics: KpiMetric[]
  kpi_total: number
}

interface DayGroup {
  date: string
  total_points: number
  finance_events: FinanceEvent[]
  kpi_summary: KpiSummary | null
}

interface HistoryPoint { date: string; mmr: number }

interface LeaderboardRow {
  rank: number
  chatter_id: number
  chatter_name: string
  current_mmr: number
  current_league: string | null
  days_active: number
  calibration_complete: boolean
  avatar_base64: string | null
  is_me: boolean
}

// ── Helpers ────────────────────────────────────────────────────────────────

const LEAGUE_LABELS: Record<string, string> = {
  bronze_iii: 'Bronze III', bronze_ii: 'Bronze II', bronze_i: 'Bronze I',
  silver_iii: 'Silver III', silver_ii: 'Silver II', silver_i: 'Silver I',
  gold_iii: 'Gold III', gold_ii: 'Gold II', gold_i: 'Gold I',
  platinum_iii: 'Platinum III', platinum_ii: 'Platinum II', platinum_i: 'Platinum I',
  diamond_iii: 'Diamond III', diamond_ii: 'Diamond II', diamond_i: 'Diamond I',
  master: 'Master', grandmaster: 'Grandmaster',
}
const leagueLabel = (l: string | null) => (l ? (LEAGUE_LABELS[l] ?? l) : 'Калибровка')

function RankBadge({ rank }: { rank: number }) {
  const colors: Record<number, string> = {
    1: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
    2: 'bg-slate-400/20 text-slate-300 border border-slate-400/30',
    3: 'bg-amber-700/20 text-amber-600 border border-amber-700/30',
  }
  return (
    <span className={cn(
      'inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold',
      colors[rank] ?? 'bg-slate-700/50 text-slate-400',
    )}>
      {rank}
    </span>
  )
}

// ── Section: Hero card ────────────────────────────────────────────────────

function HeroCard({ data }: { data: MmrMain }) {
  const progressPct = data.next_league && data.mmr_to_next != null
    ? (() => {
        const thresholds = [0,100,200,300,450,600,800,1000,1250,1500,1800,2100,2500,3000,3500,4500,6000]
        const currentThreshold = thresholds.filter(t => t <= data.current_mmr).at(-1) ?? 0
        const nextThreshold = currentThreshold + data.mmr_to_next
        const range = nextThreshold - currentThreshold
        return range > 0 ? Math.round((data.current_mmr - currentThreshold) / range * 100) : 100
      })()
    : 100

  return (
    <div className="bg-gradient-to-br from-violet-500/10 via-slate-800/60 to-slate-800/40 border border-violet-500/20 rounded-2xl p-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="mb-2">
            <LeagueBadge league={data.current_league} className="text-sm px-3 py-1" />
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-5xl font-bold text-slate-100">{data.current_mmr}</span>
            <span className="text-sm text-slate-500">MMR</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">Пик: {data.peak_mmr} MMR</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500 mb-1">Место в агентстве</p>
          <p className="text-3xl font-bold text-violet-300">{data.rank}</p>
          <p className="text-xs text-slate-500">из {data.total_chatters}</p>
        </div>
      </div>
      <div className="mt-5">
        {!data.calibration_complete ? (
          <div>
            <div className="flex justify-between text-xs text-slate-400 mb-2">
              <span>Калибровка</span>
              <span>{data.days_active}/{data.calibration_days} дней</span>
            </div>
            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-violet-500 rounded-full transition-all"
                style={{ width: `${Math.round(data.days_active / data.calibration_days * 100)}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-1.5">
              Осталось {data.calibration_days_left} дней до присвоения лиги
            </p>
          </div>
        ) : data.next_league ? (
          <div>
            <div className="flex justify-between text-xs text-slate-400 mb-2">
              <span>До <span className="text-violet-300">{leagueLabel(data.next_league)}</span></span>
              <span>{data.mmr_to_next} MMR</span>
            </div>
            <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-violet-500 rounded-full transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        ) : (
          <p className="text-sm text-yellow-400 font-semibold">🏆 Grandmaster — максимальная лига!</p>
        )}
      </div>
    </div>
  )
}

// ── Section: Season card ──────────────────────────────────────────────────

function SeasonCard({ data }: { data: MmrMain }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <CalendarDays className="h-4 w-4 text-violet-400" />
        <p className="text-sm font-semibold text-slate-300">{data.season_name}</p>
        {data.season_days_left != null && (
          <span className="ml-auto text-xs text-slate-500">
            Осталось {data.season_days_left} дн.
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3 mt-3">
        {[
          { place: '1 место', prize: data.prize_info['1st'], color: 'text-yellow-400' },
          { place: '2 место', prize: data.prize_info['2nd'], color: 'text-slate-300' },
          { place: '3 место', prize: data.prize_info['3rd'], color: 'text-amber-600' },
        ].map(({ place, prize, color }) => (
          <div key={place} className="bg-slate-700/30 rounded-lg p-3 text-center">
            <p className="text-xs text-slate-500">{place}</p>
            <p className={`text-lg font-bold mt-1 ${color}`}>${prize.toFixed(0)}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Section: MMR history chart ────────────────────────────────────────────

// Custom active dot — shown on hover
function ActiveDot(props: { cx?: number; cy?: number; [key: string]: unknown }) {
  const { cx, cy } = props
  return (
    <circle
      cx={cx} cy={cy} r={5}
      fill="#8b5cf6" stroke="#1e293b" strokeWidth={2}
    />
  )
}

// Regular dot — small circle on every data point
function RegularDot(props: { cx?: number; cy?: number; [key: string]: unknown }) {
  const { cx, cy } = props
  return (
    <circle
      cx={cx} cy={cy} r={3}
      fill="#8b5cf6" stroke="#1e293b" strokeWidth={1.5}
      opacity={0.7}
    />
  )
}

function MmrChart() {
  const { data, isLoading } = useQuery<{ history: HistoryPoint[] }>({
    queryKey: ['portal-mmr-history'],
    queryFn: () => api.get('/api/v1/me/mmr/history').then(r => r.data),
  })
  const points = data?.history ?? []
  if (isLoading) return <Skeleton className="h-40 w-full rounded-xl" />
  if (!points.length) return null

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
      <p className="text-sm font-semibold text-slate-300 mb-4">MMR за сезон</p>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={points} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="mmrGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.4} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            tickFormatter={(v: string) => v.slice(5)}
            axisLine={false} tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#94a3b8' }}
            axisLine={false} tickLine={false} width={40}
          />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#94a3b8', fontSize: 12 }}
            labelFormatter={(label) => String(label)}
            formatter={(v) => [`${Number(v)} MMR`, 'MMR']}
          />
          <Area
            type="monotone"
            dataKey="mmr"
            stroke="#8b5cf6"
            strokeWidth={2}
            fill="url(#mmrGrad)"
            dot={<RegularDot />}
            activeDot={<ActiveDot />}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Section: Events feed ──────────────────────────────────────────────────

const TYPE_FILTERS = [
  { key: '', label: 'Все' },
  { key: 'finance', label: 'Финансы' },
  { key: 'kpi', label: 'KPI' },
] as const

const RU_MONTHS = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек']
function fmtDate(iso: string) {
  const d = new Date(iso)
  return `${d.getDate()} ${RU_MONTHS[d.getMonth()]}`
}

function FinanceRow({ ev }: { ev: FinanceEvent }) {
  const pos = ev.points > 0
  return (
    <div className="flex items-center gap-2 py-1.5">
      <div className={cn('p-1 rounded shrink-0', pos ? 'bg-emerald-500/10' : 'bg-red-500/10')}>
        {pos
          ? <TrendingUp className="h-3 w-3 text-emerald-400" />
          : <TrendingDown className="h-3 w-3 text-red-400" />}
      </div>
      <span className="text-xs text-slate-300 flex-1 min-w-0 truncate">
        {[ev.model_name, ev.shift_name].filter(Boolean).join(' · ')}
        {ev.plan != null && ev.revenue != null && (
          <span className="text-slate-500">
            {' '}· Plan ${ev.plan.toFixed(0)}, rev ${ev.revenue.toFixed(0)}
            {ev.performance_pct != null && ` (${ev.performance_pct}%)`}
          </span>
        )}
      </span>
      <span className={cn('text-xs font-bold shrink-0 tabular-nums', pos ? 'text-emerald-400' : 'text-red-400')}>
        {pos ? '+' : ''}{ev.points}
      </span>
    </div>
  )
}

function KpiRow({ summary }: { summary: KpiSummary }) {
  const pos = summary.kpi_total > 0
  return (
    <div className="flex items-start gap-2 py-1.5">
      <div className={cn('p-1 rounded shrink-0 mt-0.5', pos ? 'bg-emerald-500/10' : 'bg-red-500/10')}>
        {pos
          ? <TrendingUp className="h-3 w-3 text-emerald-400" />
          : <TrendingDown className="h-3 w-3 text-red-400" />}
      </div>
      <div className="flex-1 min-w-0">
        <span className="text-xs text-slate-400 font-medium">KPI: </span>
        {summary.metrics.map((m, i) => (
          <span key={i} className="text-xs">
            <span className="text-slate-500">{m.name} </span>
            {m.direction === 'up'
              ? <span className="text-emerald-400">↑+{m.points}</span>
              : <span className="text-red-400">↓{m.points}</span>}
            {i < summary.metrics.length - 1 && <span className="text-slate-600">, </span>}
          </span>
        ))}
      </div>
      <span className={cn('text-xs font-bold shrink-0 tabular-nums', pos ? 'text-emerald-400' : 'text-red-400')}>
        {pos ? '+' : ''}{summary.kpi_total}
      </span>
    </div>
  )
}

function DayCard({ day }: { day: DayGroup }) {
  const pos = day.total_points > 0
  const hasContent = day.finance_events.length > 0 || day.kpi_summary

  return (
    <div className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-400">{fmtDate(day.date)}</span>
        <span className={cn('text-sm font-bold tabular-nums', pos ? 'text-emerald-400' : 'text-red-400')}>
          {pos ? '+' : ''}{day.total_points}
        </span>
      </div>
      {hasContent && (
        <div className="divide-y divide-slate-700/20">
          {day.finance_events.map((ev, i) => <FinanceRow key={i} ev={ev} />)}
          {day.kpi_summary && <KpiRow summary={day.kpi_summary} />}
        </div>
      )}
    </div>
  )
}

function EventsFeed() {
  const PAGE = 14
  const [typeFilter, setTypeFilter] = useState<'' | 'finance' | 'kpi'>('')
  // pages stores the list of offsets we have fetched and accumulated
  const [pages, setPages] = useState<number[]>([0])
  const [allDays, setAllDays] = useState<DayGroup[]>([])
  const [hasMore, setHasMore] = useState(false)
  // Track which data we've already merged to prevent double-appends
  const lastMergedRef = useRef<string | null>(null)

  const currentOffset = pages[pages.length - 1]

  const { data: eventsData, isLoading, isFetching } = useQuery<{
    days: DayGroup[]
    offset: number
    limit: number
  }>({
    queryKey: ['portal-mmr-events', typeFilter, currentOffset],
    queryFn: () => {
      const base = `/api/v1/me/mmr/events?limit=${PAGE}&offset=${currentOffset}`
      const url = typeFilter ? `${base}&event_type=${typeFilter}` : base
      return api.get(url).then(r => r.data)
    },
  })

  useEffect(() => {
    if (!eventsData) return
    // Deduplicate: build a key for this response
    const key = `${typeFilter}:${eventsData.offset}:${eventsData.days.length}`
    if (lastMergedRef.current === key) return
    lastMergedRef.current = key

    if (eventsData.offset === 0) {
      setAllDays(eventsData.days)
    } else {
      setAllDays(prev => {
        // Avoid duplicates by date key
        const existing = new Set(prev.map(d => d.date))
        const fresh = eventsData.days.filter(d => !existing.has(d.date))
        return [...prev, ...fresh]
      })
    }
    setHasMore(eventsData.days.length === PAGE)
  }, [eventsData, typeFilter])

  const handleFilter = (f: '' | 'finance' | 'kpi') => {
    lastMergedRef.current = null
    setTypeFilter(f)
    setPages([0])
    setAllDays([])
    setHasMore(false)
  }

  const loadMore = () => {
    const nextOffset = allDays.length  // use actual accumulated length as next offset
    setPages(prev => [...prev, nextOffset])
  }

  const showLoadMore = hasMore && allDays.length > 0

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      {/* Header + filter tabs */}
      <div className="px-5 py-3 border-b border-slate-700/40 flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm font-semibold text-slate-300">Лента событий</p>
        <div className="flex gap-1">
          {TYPE_FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => handleFilter(f.key)}
              className={cn(
                'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                typeFilter === f.key
                  ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-700/40',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading && allDays.length === 0 ? (
        <div className="p-4 space-y-3">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
        </div>
      ) : allDays.length === 0 ? (
        <p className="text-slate-500 text-sm p-5">Событий пока нет</p>
      ) : (
        <>
          <div className="p-4 space-y-3">
            {allDays.map(day => <DayCard key={day.date} day={day} />)}
          </div>

          <div className="px-5 py-3 border-t border-slate-700/40">
            {showLoadMore ? (
              <button
                onClick={loadMore}
                disabled={isFetching}
                className="w-full text-xs text-slate-400 hover:text-violet-300 transition-colors disabled:opacity-50 py-1"
              >
                {isFetching ? 'Загружаем...' : 'Показать ещё 14 дней'}
              </button>
            ) : (
              <p className="text-center text-xs text-slate-600">Все события загружены</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── Section: Leaderboard ──────────────────────────────────────────────────

function Leaderboard() {
  const { data, isLoading } = useQuery<{ rows: LeaderboardRow[]; my_rank: number | null }>({
    queryKey: ['portal-mmr-leaderboard'],
    queryFn: () => api.get('/api/v1/me/mmr/leaderboard').then(r => r.data),
  })
  const rows = data?.rows ?? []
  const top10 = rows.slice(0, 10)
  const me = rows.find(r => r.is_me)
  const showMeSeparate = me && (me.rank ?? 99) > 10

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-700/40">
        <p className="text-sm font-semibold text-slate-300">Топ агентства</p>
      </div>
      {isLoading ? (
        <div className="p-4 space-y-3">{[1,2,3].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
      ) : (
        <table className="w-full">
          <tbody className="divide-y divide-slate-700/30">
            {top10.map(r => (
              <tr
                key={r.chatter_id}
                className={cn(
                  'hover:bg-slate-700/20 transition-colors',
                  r.is_me && 'bg-violet-500/10',
                )}
              >
                <td className="px-4 py-2.5 w-10"><RankBadge rank={r.rank} /></td>
                <td className="px-4 py-2.5 text-sm font-medium text-slate-200">
                  <div className="flex items-center gap-2">
                    {r.avatar_base64 ? (
                      <img src={r.avatar_base64} alt="" className="w-6 h-6 rounded-full object-cover shrink-0" />
                    ) : (
                      <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center shrink-0 text-[10px] text-slate-400 font-bold">
                        {r.chatter_name.slice(0,1).toUpperCase()}
                      </div>
                    )}
                    {r.chatter_name}
                    {r.is_me && <span className="ml-1 text-xs text-violet-400">(вы)</span>}
                  </div>
                </td>
                <td className="px-4 py-2.5"><LeagueBadge league={r.current_league} /></td>
                <td className="px-4 py-2.5 text-right text-sm font-bold text-violet-300">{r.current_mmr}</td>
              </tr>
            ))}
            {showMeSeparate && me && (
              <>
                <tr><td colSpan={4} className="px-4 py-1 text-center text-slate-600 text-xs">···</td></tr>
                <tr className="bg-violet-500/10">
                  <td className="px-4 py-2.5 w-10"><RankBadge rank={me.rank} /></td>
                  <td className="px-4 py-2.5 text-sm font-medium text-slate-200">
                    <div className="flex items-center gap-2">
                      {me.avatar_base64 ? (
                        <img src={me.avatar_base64} alt="" className="w-6 h-6 rounded-full object-cover shrink-0" />
                      ) : (
                        <div className="w-6 h-6 rounded-full bg-slate-700 flex items-center justify-center shrink-0 text-[10px] text-slate-400 font-bold">
                          {me.chatter_name.slice(0,1).toUpperCase()}
                        </div>
                      )}
                      {me.chatter_name}
                      <span className="ml-1 text-xs text-violet-400">(вы)</span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5"><LeagueBadge league={me.current_league} /></td>
                  <td className="px-4 py-2.5 text-right text-sm font-bold text-violet-300">{me.current_mmr}</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function PortalRankingPage() {
  const { data, isLoading } = useQuery<MmrMain>({
    queryKey: ['portal-mmr'],
    queryFn: () => api.get('/api/v1/me/mmr').then(r => r.data),
  })

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900 flex items-center gap-2">
        <Trophy className="h-5 w-5 text-violet-400" />
        <h1 className="text-lg font-semibold text-slate-100">Мой рейтинг</h1>
      </header>

      <div className="flex-1 p-6 space-y-5 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-4">
            <Skeleton className="h-48 w-full rounded-2xl" />
            <Skeleton className="h-28 w-full rounded-xl" />
          </div>
        ) : !data?.has_season ? (
          <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-10 text-center">
            <Trophy className="h-10 w-10 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-300 font-medium mb-1">MMR-рейтинг ещё не запущен</p>
            <p className="text-slate-500 text-sm">Попросите владельца агентства запустить пересчёт в разделе Рейтинг.</p>
          </div>
        ) : data ? (
          <>
            <HeroCard data={data} />
            <SeasonCard data={data} />
            <MmrChart />
            <EventsFeed />
            <Leaderboard />
          </>
        ) : null}
      </div>
    </div>
  )
}
