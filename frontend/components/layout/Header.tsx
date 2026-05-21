'use client'

import { useEffect, useRef } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { MonthPicker } from '@/components/layout/MonthPicker'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { useTeamStore } from '@/lib/hooks/useTeam'
import { useMonthsSummary } from '@/lib/hooks/useMonthsSummary'
import { getPrevMonth, getNextMonth } from '@/lib/utils'
import api from '@/lib/api'
import type { TeamOut } from '@/types'

interface HeaderProps {
  title: string
}

export function Header({ title }: HeaderProps) {
  const { month, year, setMonth } = useMonthStore()
  const { teamId, setTeamId } = useTeamStore()
  const { data: summary } = useMonthsSummary(teamId)

  const { data: teams } = useQuery({
    queryKey: ['teams'],
    queryFn: () => api.get<TeamOut[]>('/api/v1/teams').then((r) => r.data),
  })

  // Один раз за сессию — если в текущем выбранном месяце нет данных, а где-то есть,
  // прыгаем на самый свежий месяц с данными. Это решает кейс «по умолчанию текущий
  // месяц, но импорт за прошлый период — экран пустой».
  const autoSwitchedRef = useRef(false)
  useEffect(() => {
    if (autoSwitchedRef.current) return
    if (!summary || summary.months.length === 0) return
    const hasCurrent = summary.months.some(
      (m) => m.month === month && m.year === year && m.revenue > 0
    )
    if (!hasCurrent) {
      const latest = summary.months[0] // уже отсортировано год desc, месяц desc
      if (latest && (latest.month !== month || latest.year !== year)) {
        setMonth(latest.month, latest.year)
      }
    }
    autoSwitchedRef.current = true
  }, [summary, month, year, setMonth])

  const prev = () => {
    const p = getPrevMonth(month, year)
    setMonth(p.month, p.year)
  }

  const next = () => {
    const n = getNextMonth(month, year)
    setMonth(n.month, n.year)
  }

  const now = new Date()
  const isCurrent = month === now.getMonth() + 1 && year === now.getFullYear()

  return (
    <header className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50 bg-slate-900">
      <h1 className="text-lg font-semibold text-slate-100">{title}</h1>
      <div className="flex items-center gap-3 flex-wrap justify-end">
        {teams && teams.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <span className="hidden sm:inline">Команда</span>
            <select
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-200 max-w-[200px]"
              value={teamId === 'all' ? 'all' : String(teamId)}
              onChange={(e) => {
                const v = e.target.value
                setTeamId(v === 'all' ? 'all' : Number(v))
              }}
            >
              <option value="all">Все команды</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" onClick={prev}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <MonthPicker month={month} year={year} onChange={setMonth} teamId={teamId} />
          <Button variant="ghost" size="icon" onClick={next} disabled={isCurrent}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </header>
  )
}
