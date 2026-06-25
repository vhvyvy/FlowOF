'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, List, BarChart3, User, LogOut,
  ChevronLeft, ChevronRight, Trophy, FileText,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { logout, isAuthenticated, getUserRole } from '@/lib/auth'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { getPrevMonth, getNextMonth } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

const PORTAL_NAV = [
  { href: '/portal', label: 'Мой обзор', icon: LayoutDashboard, exact: true },
  { href: '/portal/transactions', label: 'Мои транзакции', icon: List },
  { href: '/portal/ranking', label: 'Рейтинг', icon: Trophy },
  { href: '/portal/scripts', label: 'Скрипты', icon: FileText },
  { href: '/portal/kpi', label: 'Мой KPI', icon: BarChart3 },
  { href: '/portal/profile', label: 'Профиль', icon: User },
]

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

interface Profile {
  full_name: string
  chatter_name: string
  avatar_base64: string | null
}

function PortalSidebar() {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)
  const { month, year, setMonth } = useMonthStore()

  const { data: profile } = useQuery<Profile>({
    queryKey: ['portal-profile'],
    queryFn: () => api.get<Profile>('/api/v1/me/profile').then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })

  const displayName = profile?.full_name || profile?.chatter_name || ''
  const initials    = (displayName || 'F').slice(0, 1).toUpperCase()
  const avatar      = profile?.avatar_base64

  const now = new Date()
  const isCurrent = month === now.getMonth() + 1 && year === now.getFullYear()

  const prev = () => {
    const p = getPrevMonth(month, year)
    setMonth(p.month, p.year)
  }
  const next = () => {
    if (isCurrent) return
    const n = getNextMonth(month, year)
    setMonth(n.month, n.year)
  }

  return (
    <aside
      className={cn(
        'flex flex-col h-screen bg-slate-900 border-r border-slate-700/50 transition-all duration-200 shrink-0',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      {/* Logo / avatar */}
      <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
        {!collapsed && (
          <div className="flex items-center gap-2 min-w-0">
            {avatar ? (
              <img
                src={avatar}
                alt="avatar"
                className="w-7 h-7 rounded-full object-cover ring-1 ring-violet-500/40 shrink-0"
              />
            ) : (
              <div className="w-7 h-7 rounded-lg bg-violet-500 flex items-center justify-center shrink-0">
                <span className="text-white font-bold text-xs">{initials}</span>
              </div>
            )}
            <span className="font-semibold text-slate-100 text-sm truncate">Кабинет</span>
          </div>
        )}
        {collapsed && (
          avatar ? (
            <img
              src={avatar}
              alt="avatar"
              className="w-7 h-7 rounded-full object-cover ring-1 ring-violet-500/40 mx-auto"
            />
          ) : (
            <div className="w-7 h-7 rounded-lg bg-violet-500 flex items-center justify-center mx-auto">
              <span className="text-white font-bold text-xs">{initials}</span>
            </div>
          )
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-slate-500 hover:text-slate-300 transition-colors ml-auto shrink-0"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      {/* Month switcher */}
      {!collapsed && (
        <div className="px-3 py-3 border-b border-slate-700/50">
          <p className="text-xs text-slate-500 mb-2 font-medium uppercase tracking-wide">Период</p>
          <div className="flex items-center gap-1">
            <button
              onClick={prev}
              className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span className="flex-1 text-center text-sm font-medium text-slate-200">
              {MONTHS_RU[month - 1]} {year}
            </span>
            <button
              onClick={next}
              disabled={isCurrent}
              className="p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors disabled:opacity-30"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {PORTAL_NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? pathname === href : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                active
                  ? 'bg-violet-500/15 text-violet-300'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              )}
            >
              <Icon className={cn('h-4 w-4 shrink-0', active ? 'text-violet-400' : '')} />
              {!collapsed && <span>{label}</span>}
            </Link>
          )
        })}
      </nav>

      {/* Logout */}
      <div className="p-2 border-t border-slate-700/50">
        <button
          onClick={logout}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:text-red-400 hover:bg-slate-800 transition-colors"
        >
          <LogOut className="h-4 w-4 shrink-0" />
          {!collapsed && <span>Выйти</span>}
        </button>
      </div>
    </aside>
  )
}

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login')
      return
    }
    const role = getUserRole()
    if (role === 'owner') {
      router.replace('/dashboard')
      return
    }
    setReady(true)
  }, [router])

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950">
        <p className="text-slate-500 text-sm">Загрузка…</p>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950">
      <PortalSidebar />
      <main className="flex-1 overflow-y-auto bg-slate-950">{children}</main>
    </div>
  )
}
