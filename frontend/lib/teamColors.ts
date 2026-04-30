export const TEAM_COLOR_OPTIONS = [
  { key: 'indigo', text: 'text-indigo-300', border: 'border-indigo-500/40', bg: 'bg-indigo-500/10', dot: 'bg-indigo-400' },
  { key: 'emerald', text: 'text-emerald-300', border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', dot: 'bg-emerald-400' },
  { key: 'sky', text: 'text-sky-300', border: 'border-sky-500/40', bg: 'bg-sky-500/10', dot: 'bg-sky-400' },
  { key: 'amber', text: 'text-amber-300', border: 'border-amber-500/40', bg: 'bg-amber-500/10', dot: 'bg-amber-400' },
  { key: 'fuchsia', text: 'text-fuchsia-300', border: 'border-fuchsia-500/40', bg: 'bg-fuchsia-500/10', dot: 'bg-fuchsia-400' },
  { key: 'rose', text: 'text-rose-300', border: 'border-rose-500/40', bg: 'bg-rose-500/10', dot: 'bg-rose-400' },
] as const

export type TeamColorKey = (typeof TEAM_COLOR_OPTIONS)[number]['key']

function colorByKey(key: string | null | undefined) {
  return TEAM_COLOR_OPTIONS.find((x) => x.key === key)
}

export function teamColor(teamId: number, key?: string | null) {
  const explicit = colorByKey(key)
  if (explicit) return explicit
  const idx = Math.abs(Number(teamId) || 0) % TEAM_COLOR_OPTIONS.length
  return TEAM_COLOR_OPTIONS[idx]
}
