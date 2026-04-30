'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

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
  const skipImport = Boolean(data.skip_import)
  const isExcel = src === 'excel' && !skipImport
  const uploadId = data.upload_id as string | undefined
  const mapping = (data.mapping_confirmed as Record<string, string>) || {}
  const previewRows = (data.preview_rows as Record<string, unknown>[]) || []
  const totalRows = typeof data.total_rows === 'number' ? data.total_rows : 0

  const [busy, setBusy] = useState(false)
  const [impErr, setImpErr] = useState<string | null>(null)
  const [importStats, setImportStats] = useState<{ imported: number; skipped: number } | null>(null)

  const runImport = async () => {
    if (!isExcel || !uploadId) return
    setBusy(true)
    setImpErr(null)
    try {
      const res = await api.post('/api/v1/import/confirm', {
        upload_id: uploadId,
        mapping: {
          date: mapping.date || null,
          model: mapping.model || null,
          chatter: mapping.chatter || null,
          amount: mapping.amount || null,
          shift_id: mapping.shift_id || null,
        },
        original_filename: String(data.original_filename ?? ''),
      })
      const body = res.data as { rows_imported?: number; rows_skipped?: number }
      setImportStats({
        imported: body.rows_imported ?? 0,
        skipped: body.rows_skipped ?? 0,
      })
    } catch (e: unknown) {
      const msg =
        typeof e === 'object' &&
        e !== null &&
        'response' in e &&
        typeof (e as { response?: { data?: { detail?: string } } }).response?.data?.detail === 'string'
          ? (e as { response: { data: { detail: string } } }).response.data.detail
          : 'Не удалось выполнить импорт'
      setImpErr(msg)
    } finally {
      setBusy(false)
    }
  }

  const finish = () => onComplete({})

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Готово</h2>
      <p className="text-slate-400 text-sm mb-6">
        Проверьте параметры. После входа в дашборд вы сможете изменить интеграции в настройках.
      </p>
      <ul className="space-y-2 text-sm text-slate-300 mb-6 bg-slate-800/40 rounded-lg p-4 border border-slate-700/50">
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

      {isExcel && (
        <div className="mb-6">
          <p className="text-slate-400 text-sm mb-2">
            Превью (первые строки), всего в файле: {totalRows}
          </p>
          <div className="overflow-x-auto rounded-lg border border-slate-700/50 max-h-48 text-xs">
            <table className="min-w-full text-left text-slate-300">
              <thead className="bg-slate-800/80 text-slate-400">
                <tr>
                  {previewRows[0]
                    ? Object.keys(previewRows[0]).map((k) => (
                        <th key={k} className="px-2 py-1 font-normal">
                          {k}
                        </th>
                      ))
                    : null}
                </tr>
              </thead>
              <tbody>
                {previewRows.slice(0, 8).map((row, i) => (
                  <tr key={i} className="border-t border-slate-700/40">
                    {Object.values(row).map((v, j) => (
                      <td key={j} className="px-2 py-1 whitespace-nowrap max-w-[140px] truncate">
                        {v === null || v === undefined ? '—' : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {importStats && (
            <p className="text-emerald-400 text-sm mt-3">
              Импортировано: {importStats.imported}, пропущено строк: {importStats.skipped}
            </p>
          )}
          {impErr && <p className="text-red-400 text-sm mt-2">{impErr}</p>}
          {!importStats && (
            <Button className="w-full mt-4" onClick={runImport} disabled={busy || !uploadId}>
              {busy ? 'Импорт…' : 'Импортировать данные'}
            </Button>
          )}
        </div>
      )}

      <Button
        className="w-full"
        onClick={finish}
        disabled={isExcel && !importStats && !skipImport}
      >
        Завершить и открыть дашборд
      </Button>
      {isExcel && !importStats && !skipImport && (
        <p className="text-slate-500 text-xs mt-2 text-center">Сначала нажмите «Импортировать данные».</p>
      )}
    </div>
  )
}
