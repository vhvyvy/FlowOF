import { cn } from '@/lib/utils'

const LEAGUE_CONFIG: Record<string, { color: string; label: string }> = {
  bronze_iii:   { color: '#92400e', label: 'Bronze III' },
  bronze_ii:    { color: '#92400e', label: 'Bronze II' },
  bronze_i:     { color: '#92400e', label: 'Bronze I' },
  silver_iii:   { color: '#64748b', label: 'Silver III' },
  silver_ii:    { color: '#64748b', label: 'Silver II' },
  silver_i:     { color: '#64748b', label: 'Silver I' },
  gold_iii:     { color: '#ca8a04', label: 'Gold III' },
  gold_ii:      { color: '#ca8a04', label: 'Gold II' },
  gold_i:       { color: '#ca8a04', label: 'Gold I' },
  platinum_iii: { color: '#0891b2', label: 'Platinum III' },
  platinum_ii:  { color: '#0891b2', label: 'Platinum II' },
  platinum_i:   { color: '#0891b2', label: 'Platinum I' },
  diamond_iii:  { color: '#9333ea', label: 'Diamond III' },
  diamond_ii:   { color: '#9333ea', label: 'Diamond II' },
  diamond_i:    { color: '#9333ea', label: 'Diamond I' },
  master:       { color: '#db2777', label: 'Master' },
  grandmaster:  { color: '#ef4444', label: 'Grandmaster' },
}

interface LeagueBadgeProps {
  league: string | null | undefined
  className?: string
}

export function LeagueBadge({ league, className }: LeagueBadgeProps) {
  if (!league) {
    return (
      <span className={cn('text-xs px-2 py-0.5 rounded font-medium bg-slate-700/50 text-slate-400', className)}>
        Калибровка
      </span>
    )
  }
  const cfg = LEAGUE_CONFIG[league] ?? LEAGUE_CONFIG.bronze_iii
  return (
    <span
      className={cn('text-xs px-2 py-0.5 rounded font-medium', className)}
      style={{ background: cfg.color + '22', color: cfg.color }}
    >
      {cfg.label}
    </span>
  )
}
