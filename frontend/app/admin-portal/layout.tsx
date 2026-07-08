'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, Users, Briefcase, History, LogOut,
  ChevronLeft, ChevronRight, ShieldCheck,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { logout, isAuthenticated, getUserIsAdmin } from '@/lib/auth'

const NAV = [
  { href: '/admin-portal',          label: 'Обзор',       icon: LayoutDashboard, exact: true },
  { href: '/admin-portal/chatters', label: 'Чаттеры',     icon: Users },
  { href: '/admin-portal/cases',    label: 'Мои кейсы',   icon: Briefcase },
  { href: '/admin-portal/history',  label: 'История',     icon: History },
]

function AdminSidebar() {
  const pathname  = usePathname()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside className={cn(
      'flex flex-col h-screen bg-slate-900 border-r border-slate-700/50 transition-all duration-200 shrink-0',
      collapsed ? 'w-16' : 'w-56',
    )}>
      {/* Logo */}
      <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
        {!collapsed && (
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-amber-500 flex items-center justify-center shrink-0">
              <ShieldCheck className="h-4 w-4 text-white" />
            </div>
            <span className="font-semibold text-slate-100 text-sm truncate">Кабинет&nbsp;Адм.</span>
          </div>
        )}
        {collapsed && (
          <div className="w-7 h-7 rounded-lg bg-amber-500 flex items-center justify-center mx-auto">
            <ShieldCheck className="h-4 w-4 text-white" />
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-slate-500 hover:text-slate-300 transition-colors ml-auto shrink-0"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {NAV.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? pathname === href : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                active
                  ? 'bg-amber-500/15 text-amber-300'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800',
              )}
            >
              <Icon className={cn('h-4 w-4 shrink-0', active ? 'text-amber-400' : '')} />
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

export default function AdminPortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login')
      return
    }
    if (!getUserIsAdmin()) {
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
      <AdminSidebar />
      <main className="flex-1 overflow-y-auto bg-slate-950">{children}</main>
    </div>
  )
}
