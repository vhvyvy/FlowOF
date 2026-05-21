'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn, formatCurrency, formatMonth } from '@/lib/utils'
import { useMonthsSummary, type MonthSummary } from '@/lib/hooks/useMonthsSummary'
import type { TeamScope } from '@/lib/hooks/useTeam'

const MONTH_NAMES_SHORT = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

interface MonthPickerProps {
  month: number
  year: number
  onChange: (month: number, year: number) => void
  teamId: TeamScope
}

export function MonthPicker({ month, year, onChange, teamId }: MonthPickerProps) {
  const [open, setOpen] = useState(false)
  const [viewYear, setViewYear] = useState(year)
  const containerRef = useRef<HTMLDivElement>(null)

  // Закрываем popover по клику вне / Esc.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // При открытии — синхронизируем viewYear с активным годом.
  useEffect(() => {
    if (open) setViewYear(year)
  }, [open, year])

  const { data } = useMonthsSummary(teamId)

  const summaryByKey = useMemo(() => {
    const map = new Map<string, MonthSummary>()
    for (const m of data?.months ?? []) {
      map.set(`${m.year}-${m.month}`, m)
    }
    return map
  }, [data])

  // Максимум по выручке за весь year для нормализации высоты баров.
  const maxRevenueInYear = useMemo(() => {
    let max = 0
    for (let m = 1; m <= 12; m++) {
      const s = summaryByKey.get(`${viewYear}-${m}`)
      if (s && s.revenue > max) max = s.revenue
    }
    return max
  }, [summaryByKey, viewYear])

  // Доступные годы — где есть хотя бы один месяц с данными + текущий.
  const availableYears = useMemo(() => {
    const ys = new Set<number>()
    for (const m of data?.months ?? []) ys.add(m.year)
    ys.add(year)
    ys.add(new Date().getFullYear())
    return Array.from(ys).sort((a, b) => b - a)
  }, [data, year])

  const minYear = availableYears.length ? Math.min(...availableYears) : viewYear
  const maxYear = availableYears.length ? Math.max(...availableYears) : viewYear

  const handlePick = (m: number) => {
    onChange(m, viewYear)
    setOpen(false)
  }

  const now = new Date()
  const isFuture = (m: number, y: number) => y > now.getFullYear() || (y === now.getFullYear() && m > now.getMonth() + 1)

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-sm text-slate-200 hover:text-white rounded-md px-2.5 py-1.5 hover:bg-slate-800 transition-colors min-w-[140px] justify-center"
      >
        <span>{formatMonth(month, year)}</span>
        <ChevronDown
          className={cn('h-3.5 w-3.5 text-slate-500 transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-80 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl p-3">
          {/* Year switcher */}
          <div className="flex items-center justify-between mb-3 px-1">
            <button
              type="button"
              onClick={() => setViewYear((y) => y - 1)}
              disabled={viewYear <= minYear - 1}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm font-medium text-slate-100">{viewYear}</span>
            <button
              type="button"
              onClick={() => setViewYear((y) => y + 1)}
              disabled={viewYear >= maxYear + 1}
              className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:hover:bg-transparent"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* 4×3 grid of months */}
          <div className="grid grid-cols-4 gap-1.5">
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
              const summary = summaryByKey.get(`${viewYear}-${m}`)
              const prev = m === 1
                ? summaryByKey.get(`${viewYear - 1}-12`)
                : summaryByKey.get(`${viewYear}-${m - 1}`)
              const isActive = m === month && viewYear === year
              const isCurrent = m === now.getMonth() + 1 && viewYear === now.getFullYear()
              const future = isFuture(m, viewYear)
              const hasData = !!summary && summary.revenue > 0

              const barPct = maxRevenueInYear > 0 && summary
                ? Math.max(8, Math.round((summary.revenue / maxRevenueInYear) * 100))
                : 0

              const trend: 'up' | 'down' | 'neutral' =
                !summary || !prev || prev.revenue === 0
                  ? 'neutral'
                  : summary.revenue >= prev.revenue
                    ? 'up'
                    : 'down'

              const barColor =
                trend === 'up'
                  ? 'bg-emerald-500'
                  : trend === 'down'
                    ? 'bg-rose-500'
                    : hasData
                      ? 'bg-indigo-500'
                      : 'bg-slate-700/40'

              const tooltip = summary
                ? `${MONTH_NAMES_SHORT[m - 1]} ${viewYear} — ${formatCurrency(summary.revenue)} · ${summary.transactions_count} тр.`
                : future
                  ? 'Будущий период'
                  : 'Нет данных'

              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => handlePick(m)}
                  disabled={future}
                  title={tooltip}
                  className={cn(
                    'group relative flex flex-col items-stretch rounded-lg border px-1.5 pt-1.5 pb-1 transition-all h-[58px]',
                    isActive
                      ? 'border-indigo-500 bg-indigo-500/10'
                      : 'border-slate-700/60 bg-slate-800/30 hover:border-slate-500 hover:bg-slate-800/60',
                    future && 'opacity-40 cursor-not-allowed hover:border-slate-700/60 hover:bg-slate-800/30',
                    !hasData && !future && 'border-dashed'
                  )}
                >
                  {/* mini bar */}
                  <div className="flex-1 flex items-end justify-center mb-1">
                    {hasData ? (
                      <div
                        className={cn('w-3 rounded-sm transition-all', barColor)}
                        style={{ height: `${barPct}%` }}
                      />
                    ) : (
                      <div className="w-3 h-1 rounded-sm bg-slate-700/40" />
                    )}
                  </div>
                  <span
                    className={cn(
                      'text-[11px] font-medium text-center leading-none',
                      isActive ? 'text-indigo-200' : isCurrent ? 'text-slate-100' : 'text-slate-400'
                    )}
                  >
                    {MONTH_NAMES_SHORT[m - 1]}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Legend */}
          <div className="flex items-center justify-between mt-3 px-1 text-[10px] text-slate-500">
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-sm bg-emerald-500" />
              <span>больше</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-sm bg-rose-500" />
              <span>меньше</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-sm bg-indigo-500" />
              <span>первый</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2 h-2 rounded-sm border border-dashed border-slate-600" />
              <span>нет данных</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
