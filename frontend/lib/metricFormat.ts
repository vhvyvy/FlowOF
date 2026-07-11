/** Shared metric value formatting for admin-portal KPI cases. */

export type MetricType =
  | 'ppv_open_rate'
  | 'rpc'
  | 'apv'
  | 'total_chats'
  | 'revenue'

export function fmtMetricValue(metric: string | null | undefined, v: number | null | undefined): string {
  if (v == null || metric == null) return '—'
  if (metric === 'ppv_open_rate') return `${v.toFixed(1)}%`
  if (metric === 'total_chats') return String(Math.round(v))
  if (metric === 'revenue') return `$${v.toFixed(0)}`
  return `$${v.toFixed(2)}`
}

export function fmtDayMonth(isoDate: string | null | undefined): string {
  if (!isoDate) return '—'
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
  })
}

export function fmtMonthName(isoDate: string | null | undefined): string {
  if (!isoDate) return '—'
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString('ru-RU', { month: 'long' })
}

export function fmtPrevMonthName(asOf: string | null | undefined): string {
  if (!asOf) return '—'
  const d = new Date(`${asOf}T12:00:00`)
  d.setMonth(d.getMonth() - 1)
  return d.toLocaleDateString('ru-RU', { month: 'long' })
}

export function weekRangeLabel(asOf: string | null | undefined): string {
  if (!asOf) return '—'
  const end = new Date(`${asOf}T12:00:00`)
  end.setDate(end.getDate() - 1)
  const start = new Date(end)
  start.setDate(start.getDate() - 6)
  const fmt = (d: Date) =>
    d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }).replace('.', '')
  return `${fmt(start)}–${fmt(end)}`
}

export function pctDelta(
  from: number | null | undefined,
  to: number | null | undefined,
): { pct: string; improved: boolean | null } | null {
  if (from == null || to == null || from === 0) return null
  const raw = ((to - from) / Math.abs(from)) * 100
  return {
    pct: `${raw >= 0 ? '+' : ''}${raw.toFixed(1)}%`,
    improved: raw > 0 ? true : raw < 0 ? false : null,
  }
}
