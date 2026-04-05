'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

const SOURCES: { id: string; label: string; hint: string }[] = [
  { id: 'notion', label: 'Notion', hint: 'База транзакций в Notion' },
  { id: 'google_sheets', label: 'Google Таблицы', hint: 'Скоро' },
  { id: 'excel', label: 'Excel / CSV', hint: 'Загрузка файла' },
  { id: 'manual', label: 'Пока без импорта', hint: 'Заполнение вручную в дашборде' },
]

export default function Step2Source({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const [source, setSource] = useState(String(data.source_type ?? 'notion'))

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Источник данных</h2>
      <p className="text-slate-400 text-sm mb-6">Откуда будем подтягивать транзакции. Можно сменить позже в настройках.</p>
      <div className="space-y-2 mb-6">
        {SOURCES.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSource(s.id)}
            className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
              source === s.id
                ? 'border-indigo-500 bg-indigo-500/10 text-slate-100'
                : 'border-slate-700 bg-slate-800/40 text-slate-300 hover:border-slate-600'
            }`}
          >
            <p className="font-medium">{s.label}</p>
            <p className="text-xs text-slate-500 mt-0.5">{s.hint}</p>
          </button>
        ))}
      </div>
      <Button className="w-full" onClick={() => onComplete({ source_type: source })}>
        Далее
      </Button>
    </div>
  )
}
