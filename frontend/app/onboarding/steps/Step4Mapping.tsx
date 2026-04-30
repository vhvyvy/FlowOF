'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { resolveApiBaseURL } from '@/lib/api'

const FIELDS: { key: string; label: string }[] = [
  { key: 'date', label: 'Дата транзакции' },
  { key: 'model', label: 'Модель' },
  { key: 'chatter', label: 'Чаттер' },
  { key: 'amount', label: 'Сумма' },
  { key: 'shift_id', label: 'Смена (опц.)' },
]

type UploadResponse = {
  upload_id: string
  filename: string
  columns_detected: string[]
  preview_rows: Record<string, unknown>[]
  total_rows: number
  suggested_mapping: Record<string, string | null>
}

export default function Step4Mapping({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const source = String(data.source_type ?? 'notion')
  const initial = (data.mapping_confirmed as Record<string, string>) || {}
  const [mapping, setMapping] = useState<Record<string, string>>(initial)
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null)
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  if (source !== 'excel') {
    return (
      <div>
        <h2 className="text-xl font-semibold text-slate-100 mb-2">Маппинг колонок</h2>
        <p className="text-slate-400 text-sm mb-6">
          Для Notion и других источников сопоставление полей выполняется при синхронизации с вашими базами. Перейдите к
          финальному шагу.
        </p>
        <Button className="w-full" onClick={() => onComplete({ skip_import: true, mapping_confirmed: {} })}>
          Далее
        </Button>
      </div>
    )
  }

  const cols = uploadResult?.columns_detected ?? []

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setErr(null)
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null
      const res = await fetch(`${resolveApiBaseURL()}/api/v1/import/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      })
      const body = (await res.json().catch(() => ({}))) as UploadResponse & { detail?: string }
      if (!res.ok) {
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Ошибка загрузки')
      }
      setUploadResult(body)
      const sug = body.suggested_mapping || {}
      setMapping((prev) => {
        const next = { ...prev }
        for (const { key } of FIELDS) {
          const s = sug[key]
          if (s && !next[key]) next[key] = s
        }
        return next
      })
    } catch (ex: unknown) {
      setErr(ex instanceof Error ? ex.message : 'Не удалось загрузить файл')
      setUploadResult(null)
    } finally {
      setUploading(false)
    }
  }

  const canContinue =
    !!uploadResult &&
    !!(mapping.date && mapping.amount) &&
    cols.length > 0

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Файл и маппинг колонок</h2>
      <p className="text-slate-400 text-sm mb-4">
        Загрузите CSV или Excel. Обязательно сопоставьте колонки для <strong className="text-slate-300">даты</strong> и{' '}
        <strong className="text-slate-300">суммы</strong>.
      </p>

      <div className="mb-4">
        <label className="block text-xs text-slate-500 mb-1">Файл</label>
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={onFile}
          disabled={uploading}
          className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-3 file:py-1.5 file:text-sm file:text-white"
        />
        {uploading && <p className="text-slate-500 text-xs mt-2">Чтение файла…</p>}
        {uploadResult && (
          <p className="text-slate-500 text-xs mt-2">
            {uploadResult.filename} — {uploadResult.total_rows} строк, колонок: {cols.length}
          </p>
        )}
        {err && <p className="text-red-400 text-sm mt-2">{err}</p>}
      </div>

      <div className="space-y-3 mb-6">
        {FIELDS.map(({ key, label }) => (
          <div
            key={key}
            className="flex flex-col sm:flex-row sm:items-center gap-2 bg-slate-800/50 rounded-lg p-3 border border-slate-700/50"
          >
            <div className="flex-1">
              <p className="text-sm text-slate-200">{label}</p>
              <p className="text-xs text-slate-500">поле: {key}</p>
            </div>
            <select
              value={mapping[key] ?? ''}
              onChange={(e) => setMapping((m) => ({ ...m, [key]: e.target.value }))}
              disabled={!cols.length}
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-200 min-w-[140px]"
            >
              <option value="">— не выбрано —</option>
              {cols.map((col) => (
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
        disabled={!canContinue}
        onClick={() =>
          onComplete({
            mapping_confirmed: mapping,
            upload_id: uploadResult?.upload_id,
            original_filename: uploadResult?.filename ?? '',
            columns_detected: cols,
            preview_rows: uploadResult?.preview_rows,
            total_rows: uploadResult?.total_rows,
            skip_import: false,
          })
        }
      >
        Сохранить и далее
      </Button>
    </div>
  )
}
