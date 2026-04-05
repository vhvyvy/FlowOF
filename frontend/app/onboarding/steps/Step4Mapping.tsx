'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'

const FIELDS: { key: string; label: string }[] = [
  { key: 'date', label: 'Дата транзакции' },
  { key: 'model', label: 'Модель' },
  { key: 'chatter', label: 'Чаттер' },
  { key: 'amount', label: 'Сумма' },
  { key: 'shift_id', label: 'Смена (опц.)' },
]

/** Заглушка: когда появится импорт с AI-маппингом, сюда придут columns_detected с API. */
const MOCK_COLS = ['Date', 'модель', 'чаттер', 'Сумма выхода', 'Смена']

export default function Step4Mapping({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const initial = (data.mapping_confirmed as Record<string, string>) || {}
  const [mapping, setMapping] = useState<Record<string, string>>(initial)

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Маппинг колонок</h2>
      <p className="text-slate-400 text-sm mb-6">
        Когда подключите источник и запустите превью импорта, здесь появятся ваши колонки. Пока — пример соответствия
        полям FlowOF.
      </p>
      <div className="space-y-3 mb-6">
        {FIELDS.map(({ key, label }) => (
          <div key={key} className="flex flex-col sm:flex-row sm:items-center gap-2 bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="flex-1">
              <p className="text-sm text-slate-200">{label}</p>
              <p className="text-xs text-slate-500">поле: {key}</p>
            </div>
            <select
              value={mapping[key] ?? ''}
              onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-200 min-w-[140px]"
            >
              <option value="">— не выбрано —</option>
              {MOCK_COLS.map((col) => (
                <option key={col} value={col}>
                  {col}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      <Button
        className="w-full"
        onClick={() => onComplete({ mapping_confirmed: mapping, columns_detected: MOCK_COLS })}
      >
        Сохранить и далее
      </Button>
    </div>
  )
}
