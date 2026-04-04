'use client'

import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { formatMonth, getPrevMonth, getNextMonth } from '@/lib/utils'

interface HeaderProps {
  title: string
}

export function Header({ title }: HeaderProps) {
  const { month, year, setMonth } = useMonthStore()

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
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={prev}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="text-sm text-slate-300 min-w-[130px] text-center">
          {formatMonth(month, year)}
        </span>
        <Button variant="ghost" size="icon" onClick={next} disabled={isCurrent}>
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </header>
  )
}
