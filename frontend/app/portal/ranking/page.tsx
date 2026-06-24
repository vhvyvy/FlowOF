'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { TrendingUp, TrendingDown, Trophy, Star, CalendarDays } from 'lucide-react'
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

interface MmrEvent {
  event_date: string
  event_type: string
  category: string
  points: number
  description: string
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
        // find current league threshold to compute filled %
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
        {/* League + MMR */}
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

        {/* Rank */}
        <div className="text-right">
          <p className="text-xs text-slate-500 mb-1">Место в агентстве</p>
          <p className="text-3xl font-bold text-violet-300">{data.rank}</p>
          <p className="text-xs text-slate-500">из {data.total_chatters}</p>
        </div>
      </div>

      {/* Progress / Calibration */}
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
            formatter={(v) => [`${Number(v)} MMR`, '']}
          />
          <Area type="monotone" dataKey="mmr" stroke="#8b5cf6" strokeWidth={2} fill="url(#mmrGrad)" dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Section: Events feed ──────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  overperform:  { label: 'Перевыполнение', color: 'text-emerald-400' },
  perform:      { label: 'Выполнение',     color: 'text-sky-400' },
  underperform: { label: 'Недовыполнение', color: 'text-red-400' },
  kpi_high:     { label: 'KPI высокий',    color: 'text-emerald-400' },
  kpi_low:      { label: 'KPI низкий',     color: 'text-red-400' },
  season_carry: { label: 'Перенос MMR',    color: 'text-violet-400' },
}

function EventsFeed() {
  const { data, isLoading } = useQuery<{ events: MmrEvent[] }>({
    queryKey: ['portal-mmr-events'],
    queryFn: () => api.get('/api/v1/me/mmr/events').then(r => r.data),
  })
  const events = data?.events ?? []

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-700/40">
        <p className="text-sm font-semibold text-slate-300">Лента событий</p>
      </div>
      {isLoading ? (
        <div className="p-4 space-y-3">
          {[1,2,3].map(i => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : events.length === 0 ? (
        <p className="text-slate-500 text-sm p-5">Событий пока нет</p>
      ) : (
        <div className="divide-y divide-slate-700/30">
          {events.map((ev, i) => {
            const cfg = CATEGORY_CONFIG[ev.category] ?? { label: ev.category, color: 'text-slate-400' }
            const positive = ev.points > 0
            return (
              <div key={i} className="flex items-center gap-3 px-5 py-3 hover:bg-slate-700/20">
                <div className={cn('p-1.5 rounded-lg', positive ? 'bg-emerald-500/10' : 'bg-red-500/10')}>
                  {positive
                    ? <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                    : <TrendingDown className="h-3.5 w-3.5 text-red-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={cn('text-xs font-medium', cfg.color)}>{cfg.label}</span>
                    <span className="text-xs text-slate-600">·</span>
                    <span className="text-xs text-slate-500">
                      {ev.event_type === 'finance' ? 'Финансы' : ev.event_type === 'kpi' ? 'KPI' : ev.event_type}
                    </span>
                  </div>
                  {ev.description && (
                    <p className="text-xs text-slate-500 truncate mt-0.5">{ev.description}</p>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <p className={cn('text-sm font-bold', positive ? 'text-emerald-400' : 'text-red-400')}>
                    {positive ? '+' : ''}{ev.points}
                  </p>
                  <p className="text-xs text-slate-600">{ev.event_date.slice(5)}</p>
                </div>
              </div>
            )
          })}
        </div>
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
                  {r.chatter_name}
                  {r.is_me && <span className="ml-2 text-xs text-violet-400">(вы)</span>}
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
                    {me.chatter_name}
                    <span className="ml-2 text-xs text-violet-400">(вы)</span>
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
