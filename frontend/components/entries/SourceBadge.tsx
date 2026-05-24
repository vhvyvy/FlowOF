'use client'

interface SourceBadgeProps {
  source: string | null | undefined
}

const CONFIG: Record<string, { label: string; cls: string }> = {
  manual:        { label: 'Вручную',       cls: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
  google_sheets: { label: 'Google Sheets', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  import:        { label: 'Импорт',        cls: 'bg-blue-500/15 text-blue-300 border-blue-500/30' },
}

export function SourceBadge({ source }: SourceBadgeProps) {
  const key = source ?? 'import'
  const c = CONFIG[key] ?? CONFIG.import
  return (
    <span className={`inline-flex text-xs px-2 py-0.5 rounded border font-medium ${c.cls}`}>
      {c.label}
    </span>
  )
}
