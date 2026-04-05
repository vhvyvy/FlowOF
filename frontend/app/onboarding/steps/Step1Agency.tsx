'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export default function Step1Agency({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const [agency, setAgency] = useState(String(data.agency_name ?? ''))
  const [currency, setCurrency] = useState(String(data.currency ?? 'USD'))

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Агентство</h2>
      <p className="text-slate-400 text-sm mb-6">
        Как называется агентство и в какой валюте считать выручку в дашборде.
      </p>
      <label className="block text-xs text-slate-500 mb-1">Название</label>
      <Input
        value={agency}
        onChange={(e) => setAgency(e.target.value)}
        placeholder="Например, Default Agency"
        className="mb-4 bg-slate-800/80 border-slate-600"
      />
      <label className="block text-xs text-slate-500 mb-1">Валюта</label>
      <select
        value={currency}
        onChange={(e) => setCurrency(e.target.value)}
        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 mb-6"
      >
        <option value="USD">USD ($)</option>
        <option value="EUR">EUR (€)</option>
        <option value="RUB">RUB (₽)</option>
      </select>
      <Button
        className="w-full"
        disabled={!agency.trim()}
        onClick={() =>
          onComplete({
            agency_name: agency.trim(),
            currency,
            name: agency.trim(),
          })
        }
      >
        Далее
      </Button>
    </div>
  )
}
