'use client'

import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import api, { formatApiError } from '@/lib/api'

type GooglePreviewRow = {
  date?: string | null
  model?: string | null
  chatter?: string | null
  amount?: number | string | null
  shift_id?: string | null
}

type GooglePreviewResponse = {
  rows?: GooglePreviewRow[]
  preview: GooglePreviewRow[]
  total_rows: number
  columns_detected: string[]
  mapping_used: Record<string, string>
  warnings: string[]
}

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
  const isExcel = src === 'excel' && !skipImport && !Boolean(data.excel_ai)
  const isGoogle = src === 'google_sheets' && !skipImport
  const isFileAI = src === 'excel' && !skipImport && Boolean(data.excel_ai)
  const uploadId = data.upload_id as string | undefined
  const mapping = (data.mapping_confirmed as Record<string, string>) || {}
  const previewRows = (data.preview_rows as Record<string, unknown>[]) || []
  const totalRows = typeof data.total_rows === 'number' ? data.total_rows : 0
  const spreadsheetId = data.spreadsheet_id as string | undefined
  const sheetName = data.sheet_name as string | undefined
  const spreadsheetName = data.spreadsheet_name as string | undefined

  // File AI mode data (from Step3 ExcelAIConnect)
  const fileAiRows = (data.ai_rows as Record<string, unknown>[] | undefined) ?? []
  const fileAiWarnings = (data.warnings as string[] | undefined) ?? []
  const fileAiTotal = typeof data.total_rows === 'number' ? data.total_rows : fileAiRows.length
  const fileAiPreview = (data.preview as Record<string, unknown>[] | undefined) ?? fileAiRows.slice(0, 10)

  const [busy, setBusy] = useState(false)
  const [impErr, setImpErr] = useState<string | null>(null)
  const [importStats, setImportStats] = useState<{ imported: number; skipped: number } | null>(null)

  // Google Sheets: AI preview state
  const [aiLoading, setAiLoading] = useState(false)
  const [aiErr, setAiErr] = useState<string | null>(null)
  const [aiData, setAiData] = useState<GooglePreviewResponse | null>(null)

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

  const analyzeGoogleSheet = useCallback(async () => {
    if (!spreadsheetId || !sheetName) {
      setAiErr('Не выбрана таблица или лист — вернитесь на шаг подключения.')
      return
    }
    setAiLoading(true)
    setAiErr(null)
    try {
      const res = await api.post<GooglePreviewResponse>('/api/v1/import/google-sheets/preview', {
        spreadsheet_id: spreadsheetId,
        sheet_name: sheetName,
      })
      setAiData(res.data)
    } catch (e) {
      setAiErr(formatApiError(e))
    } finally {
      setAiLoading(false)
    }
  }, [spreadsheetId, sheetName])

  useEffect(() => {
    if (isGoogle && !aiData && !aiLoading && !aiErr) {
      void analyzeGoogleSheet()
    }
  }, [isGoogle, aiData, aiLoading, aiErr, analyzeGoogleSheet])

  const confirmGoogleImport = async () => {
    if (!spreadsheetId || !sheetName) return
    setBusy(true)
    setImpErr(null)
    try {
      // Если есть rows из preview — шлём их, чтобы избежать повторного вызова GPT-4o (платный).
      const payload: Record<string, unknown> = {
        spreadsheet_id: spreadsheetId,
        sheet_name: sheetName,
      }
      if (aiData?.rows && aiData.rows.length > 0) {
        payload.rows = aiData.rows
      }
      const res = await api.post<{ rows_imported?: number; rows_skipped?: number }>(
        '/api/v1/import/google-sheets/confirm',
        payload
      )
      setImportStats({
        imported: res.data.rows_imported ?? 0,
        skipped: res.data.rows_skipped ?? 0,
      })
    } catch (e) {
      setImpErr(formatApiError(e))
    } finally {
      setBusy(false)
    }
  }

  const confirmFileAIImport = async () => {
    if (!fileAiRows.length) return
    setBusy(true)
    setImpErr(null)
    try {
      const res = await api.post<{ rows_imported?: number; rows_skipped?: number }>(
        '/api/v1/import/file/confirm',
        { rows: fileAiRows }
      )
      setImportStats({
        imported: res.data.rows_imported ?? 0,
        skipped: res.data.rows_skipped ?? 0,
      })
    } catch (e) {
      setImpErr(formatApiError(e))
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

      {isGoogle && (
        <div className="mb-6">
          {spreadsheetName && (
            <p className="text-slate-400 text-sm mb-2">
              Таблица: <span className="text-slate-200">{spreadsheetName}</span>
              {sheetName ? <> · лист <span className="text-slate-200">{sheetName}</span></> : null}
            </p>
          )}

          {aiLoading && (
            <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-4 text-center">
              <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p className="text-slate-200 text-sm font-medium">AI анализирует таблицу…</p>
              <p className="text-slate-500 text-xs mt-1">Обычно занимает 10–30 секунд</p>
            </div>
          )}

          {aiErr && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 mb-3">
              <p className="text-red-300 text-sm mb-2">{aiErr}</p>
              <button
                type="button"
                onClick={analyzeGoogleSheet}
                className="text-red-300 hover:text-red-200 text-xs underline"
              >
                Попробовать снова
              </button>
            </div>
          )}

          {aiData && !aiLoading && (
            <>
              <p className="text-slate-400 text-sm mb-2">
                AI нашёл <span className="text-slate-100 font-medium">{aiData.total_rows}</span> транзакций. Проверьте
                первые строки.
              </p>

              {aiData.warnings.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 mb-3 space-y-1">
                  {aiData.warnings.map((w, i) => (
                    <p key={i} className="text-amber-300 text-xs">
                      ⚠ {w}
                    </p>
                  ))}
                </div>
              )}

              <div className="overflow-x-auto rounded-lg border border-slate-700/50 max-h-56 text-xs mb-3">
                <table className="min-w-full text-left text-slate-300">
                  <thead className="bg-slate-800/80 text-slate-400 sticky top-0">
                    <tr>
                      <th className="px-2 py-1 font-normal">Дата</th>
                      <th className="px-2 py-1 font-normal">Модель</th>
                      <th className="px-2 py-1 font-normal">Чаттер</th>
                      <th className="px-2 py-1 font-normal text-right">Сумма</th>
                    </tr>
                  </thead>
                  <tbody>
                    {aiData.preview.map((row, i) => (
                      <tr key={i} className="border-t border-slate-700/40">
                        <td className="px-2 py-1 whitespace-nowrap">{row.date ?? '—'}</td>
                        <td className="px-2 py-1 whitespace-nowrap max-w-[140px] truncate">{row.model ?? '—'}</td>
                        <td className="px-2 py-1 whitespace-nowrap max-w-[140px] truncate">{row.chatter ?? '—'}</td>
                        <td className="px-2 py-1 whitespace-nowrap text-right text-emerald-400">
                          {row.amount !== null && row.amount !== undefined && row.amount !== ''
                            ? `$${Number(row.amount).toFixed(2)}`
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {importStats ? (
                <p className="text-emerald-400 text-sm">
                  Импортировано: {importStats.imported}, пропущено строк: {importStats.skipped}
                </p>
              ) : (
                <Button className="w-full" onClick={confirmGoogleImport} disabled={busy}>
                  {busy ? 'Импортируем…' : `Импортировать ${aiData.total_rows} транзакций`}
                </Button>
              )}
              {impErr && <p className="text-red-400 text-sm mt-2">{impErr}</p>}
            </>
          )}
        </div>
      )}

      {isFileAI && (
        <div className="mb-6">
          <p className="text-slate-400 text-sm mb-2">
            AI нашёл <span className="text-slate-100 font-medium">{fileAiTotal}</span> транзакций. Проверьте первые строки.
          </p>

          {fileAiWarnings.length > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 mb-3 space-y-1">
              {fileAiWarnings.map((w, i) => (
                <p key={i} className="text-amber-300 text-xs">⚠ {w}</p>
              ))}
            </div>
          )}

          <div className="overflow-x-auto rounded-lg border border-slate-700/50 max-h-56 text-xs mb-3">
            <table className="min-w-full text-left text-slate-300">
              <thead className="bg-slate-800/80 text-slate-400 sticky top-0">
                <tr>
                  <th className="px-2 py-1 font-normal">Дата</th>
                  <th className="px-2 py-1 font-normal">Модель</th>
                  <th className="px-2 py-1 font-normal">Чаттер</th>
                  <th className="px-2 py-1 font-normal text-right">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {fileAiPreview.map((row, i) => (
                  <tr key={i} className="border-t border-slate-700/40">
                    <td className="px-2 py-1 whitespace-nowrap">{String(row.date ?? '—')}</td>
                    <td className="px-2 py-1 whitespace-nowrap max-w-[140px] truncate">{String(row.model ?? '—')}</td>
                    <td className="px-2 py-1 whitespace-nowrap max-w-[140px] truncate">{String(row.chatter ?? '—')}</td>
                    <td className="px-2 py-1 whitespace-nowrap text-right text-emerald-400">
                      {row.amount !== null && row.amount !== undefined && row.amount !== ''
                        ? `$${Number(row.amount).toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {importStats ? (
            <p className="text-emerald-400 text-sm">
              Импортировано: {importStats.imported}, пропущено строк: {importStats.skipped}
            </p>
          ) : (
            <Button className="w-full" onClick={confirmFileAIImport} disabled={busy || !fileAiRows.length}>
              {busy ? 'Импортируем…' : `Импортировать ${fileAiTotal} транзакций`}
            </Button>
          )}
          {impErr && <p className="text-red-400 text-sm mt-2">{impErr}</p>}
        </div>
      )}

      <Button
        className="w-full"
        onClick={finish}
        disabled={(isExcel || isGoogle || isFileAI) && !importStats && !skipImport}
      >
        Завершить и открыть дашборд
      </Button>
      {(isExcel || isGoogle || isFileAI) && !importStats && !skipImport && (
        <p className="text-slate-500 text-xs mt-2 text-center">
          {isExcel ? 'Сначала нажмите «Импортировать данные».' : 'Сначала подтвердите импорт после анализа AI.'}
        </p>
      )}
    </div>
  )
}
