import { TrendingDown, TrendingUp } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface MetricCardProps {
  label: string
  value: string
  delta?: number
  deltaLabel?: string
  icon?: React.ReactNode
  className?: string
}

export function MetricCard({ label, value, delta, deltaLabel, icon, className }: MetricCardProps) {
  const isPositive = delta !== undefined && delta >= 0

  return (
    <Card className={cn('', className)}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{label}</CardTitle>
          {icon && <span className="text-slate-500">{icon}</span>}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold text-slate-100">{value}</p>
        {delta !== undefined && (
          <p
            className={cn(
              'mt-1.5 flex items-center gap-1 text-xs',
              isPositive ? 'text-emerald-400' : 'text-red-400'
            )}
          >
            {isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
            {isPositive ? '+' : ''}
            {delta.toFixed(1)}% {deltaLabel ?? 'к прошлому месяцу'}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function MetricCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-24" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-32 mb-2" />
        <Skeleton className="h-3 w-20" />
      </CardContent>
    </Card>
  )
}
