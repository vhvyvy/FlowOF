'use client'

import { Button } from '@/components/ui/button'

export default function Step5Preview({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const agency = String(data.agency_name ?? '—')
  const cur = String(data.currency ?? 'USD')
  const src = String(data.source_type ?? '—')

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Готово</h2>
      <p className="text-slate-400 text-sm mb-6">
        Проверьте параметры. После входа в дашборд вы сможете изменить интеграции в настройках.
      </p>
      <ul className="space-y-2 text-sm text-slate-300 mb-8 bg-slate-800/40 rounded-lg p-4 border border-slate-700/50">
        <li>
          <span className="text-slate-500">Агентство:</span> {agency}
        </li>
        <li>
          <span className="text-slate-500">Валюта:</span> {cur}
        </li>
        <li>
          <span className="text-slate-500">Источник:</span> {src}
        </li>
      </ul>
      <Button className="w-full" onClick={() => onComplete({})}>
        Завершить и открыть дашборд
      </Button>
    </div>
  )
}
