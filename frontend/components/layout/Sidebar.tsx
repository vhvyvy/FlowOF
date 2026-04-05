'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  TrendingUp,
  Users,
  BarChart3,
  Sparkles,
  LogOut,
  ChevronLeft,
  ChevronRight,
  FlaskConical,
  Settings,
  ClipboardList,
  PieChart,
  CalendarDays,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { logout } from '@/lib/auth'
import { useTenant } from '@/lib/hooks/useTenant'
import { Badge } from '@/components/ui/badge'

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Overview', icon: LayoutDashboard, exact: true },
  { href: '/dashboard/finance', label: 'Финансы', icon: TrendingUp },
  { href: '/dashboard/structure', label: 'Структура', icon: PieChart },
  { href: '/dashboard/chatters', label: 'Чаттеры', icon: Users },
  { href: '/dashboard/kpi', label: 'KPI', icon: BarChart3 },
  { href: '/dashboard/shifts', label: 'Смены', icon: CalendarDays },
  { href: '/dashboard/plans', label: 'Планы', icon: ClipboardList },
  { href: '/dashboard/lab', label: 'Лаборатория', icon: FlaskConical },
  { href: '/dashboard/ai', label: 'AI Аналитик', icon: Sparkles },
  { href: '/dashboard/settings', label: 'Настройки', icon: Settings },
]

export function Sidebar() {
  const pathname = usePathname()
  const { data: tenant } = useTenant()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={cn(
        'flex flex-col h-screen bg-slate-900 border-r border-slate-700/50 transition-all duration-200',
        collapsed ? 'w-16' : 'w-56'
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between p-4 border-b border-slate-700/50">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-indigo-500 flex items-center justify-center">
              <span className="text-white font-bold text-xs">S</span>
            </div>
            <span className="font-semibold text-slate-100 text-sm">Skynet</span>
          </div>
        )}
        {collapsed && (
          <div className="w-7 h-7 rounded-lg bg-indigo-500 flex items-center justify-center mx-auto">
            <span className="text-white font-bold text-xs">S</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-slate-500 hover:text-slate-300 transition-colors ml-auto"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      {/* Tenant info */}
      {!collapsed && tenant && (
        <div className="px-4 py-3 border-b border-slate-700/50">
          <p className="text-xs text-slate-500 truncate">{tenant.email}</p>
          <div className="flex items-center gap-2 mt-1">
            <p className="text-sm font-medium text-slate-200 truncate flex-1">{tenant.name}</p>
            <Badge variant="secondary" className="text-xs">
              {tenant.plan}
            </Badge>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map(({ href, label, icon: Icon, exact }) => {
          const active = exact ? pathname === href : pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                active
                  ? 'bg-indigo-500/15 text-indigo-300'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              )}
            >
              <Icon className={cn('h-4 w-4 shrink-0', active ? 'text-indigo-400' : '')} />
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
