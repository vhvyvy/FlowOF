'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import api, { formatApiError, resolveApiBaseURL } from '@/lib/api'
import { UploadCloud, FileSpreadsheet, CheckCircle2, AlertCircle } from 'lucide-react'

type Spreadsheet = { id: string; name: string; modifiedTime?: string }
type Sheet = { id: number | string; name: string }
type GoogleStatus = {
  connected: boolean
  active: boolean
  spreadsheet_id: string | null
  sheet_name: string | null
}

type Stage = 'connect' | 'spreadsheets' | 'sheets' | 'ready'

export default function Step3Connect({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const src = String(data.source_type ?? 'notion')

  if (src === 'google_sheets') {
    return <GoogleSheetsConnect onComplete={onComplete} data={data} />
  }

  if (src === 'excel') {
    return <ExcelAIConnect onComplete={onComplete} />
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Подключение</h2>
      {src === 'notion' && (
        <>
          <p className="text-slate-400 text-sm mb-4">
            После онбординга откройте <strong className="text-slate-300">Настройки → Интеграции</strong> и вставьте{' '}
            <span className="text-indigo-300">Notion Internal Integration Secret</span>. Затем в Notion: Share →
            Connections на ваших базах.
          </p>
          <p className="text-slate-500 text-xs mb-6">
            Импорт и сопоставление колонок можно настроить в следующих шагах, когда API будет готов к полному сценарию.
          </p>
        </>
      )}
      {src === 'excel' && (
        <p className="text-slate-400 text-sm mb-6">
          Загрузка Excel/CSV будет доступна из раздела импорта. Пока можно завершить онбординг и вернуться к этому позже.
        </p>
      )}
      {src === 'manual' && (
        <p className="text-slate-400 text-sm mb-6">
          Без интеграции — данные будете вносить вручную из дашборда.
        </p>
      )}
      <Button className="w-full" onClick={() => onComplete({})}>
        Понятно, далее
      </Button>
    </div>
  )
}

// ─────────────────────────── Excel / CSV AI sub-flow ─────────────────────────

type FileAIPreviewResponse = {
  rows: Record<string, unknown>[]
  preview: Record<string, unknown>[]
  total_rows: number
  columns_detected: string[]
  mapping_used: Record<string, string>
  warnings: string[]
}

function ExcelAIConnect({
  onComplete,
}: {
  onComplete: (data: Record<string, unknown>) => void
}) {
  const [stage, setStage] = useState<'drop' | 'analyzing' | 'done' | 'error'>('drop')
  const [err, setErr] = useState<string | null>(null)
  const [fileName, setFileName] = useState<string>('')
  const [aiData, setAiData] = useState<FileAIPreviewResponse | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const uploadFile = async (file: File) => {
    setFileName(file.name)
    setErr(null)
    setStage('analyzing')

    const fd = new FormData()
    fd.append('file', file)
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null

    try {
      const res = await fetch(`${resolveApiBaseURL()}/api/v1/import/file/preview`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: fd,
      })
      const body = (await res.json().catch(() => ({}))) as FileAIPreviewResponse & { detail?: string }
      if (!res.ok) {
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Ошибка AI-анализа')
      }
      setAiData(body)
      setStage('done')
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Не удалось обработать файл')
      setStage('error')
    }
  }

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) void uploadFile(file)
  }

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) void uploadFile(file)
  }

  const handleContinue = () => {
    if (!aiData) return
    onComplete({
      excel_ai: true,
      ai_rows: aiData.rows,
      preview: aiData.preview,
      total_rows: aiData.total_rows,
      columns_detected: aiData.columns_detected,
      warnings: aiData.warnings,
      skip_import: false,
    })
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">Загрузи файл</h2>
      <p className="text-slate-400 text-sm mb-6">
        Поддерживаются <span className="text-slate-200">.xlsx, .xls, .csv</span>. AI сам разберётся со структурой — маппинг не нужен.
      </p>

      {/* Drop zone */}
      {(stage === 'drop' || stage === 'error') && (
        <>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
              dragging
                ? 'border-indigo-400 bg-indigo-500/10'
                : 'border-slate-700 bg-slate-800/30 hover:border-slate-500 hover:bg-slate-800/50'
            }`}
          >
            <UploadCloud className="h-10 w-10 text-slate-500 mx-auto mb-3" />
            <p className="text-slate-300 text-sm font-medium">Перетащи файл сюда или нажми</p>
            <p className="text-slate-500 text-xs mt-1">.xlsx, .xls, .csv · до 15 МБ</p>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={onInputChange}
          />
          {err && (
            <div className="flex items-start gap-2 mt-3 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {err}
            </div>
          )}
          {stage === 'error' && (
            <button
              type="button"
              onClick={() => { setStage('drop'); setErr(null) }}
              className="text-xs text-slate-500 hover:text-slate-300 mt-2 w-full text-center"
            >
              Попробовать другой файл
            </button>
          )}
        </>
      )}

      {/* Analyzing */}
      {stage === 'analyzing' && (
        <div className="rounded-xl border border-slate-700/50 bg-slate-800/40 px-6 py-10 text-center">
          <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-200 text-sm font-medium">AI анализирует таблицу…</p>
          <p className="text-slate-500 text-xs mt-1">{fileName}</p>
          <p className="text-slate-500 text-xs mt-1">Обычно занимает 10–30 секунд</p>
        </div>
      )}

      {/* Done */}
      {stage === 'done' && aiData && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3">
            <CheckCircle2 className="h-5 w-5 text-emerald-400 shrink-0" />
            <div>
              <p className="text-sm text-emerald-300 font-medium">
                AI нашёл {aiData.total_rows} транзакций
              </p>
              <p className="text-xs text-slate-500 mt-0.5 flex items-center gap-1">
                <FileSpreadsheet className="h-3 w-3" />
                {fileName}
              </p>
            </div>
          </div>

          {aiData.warnings.length > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 space-y-1">
              {aiData.warnings.map((w, i) => (
                <p key={i} className="text-amber-300 text-xs">⚠ {w}</p>
              ))}
            </div>
          )}

          {/* Mini preview */}
          <div className="rounded-lg border border-slate-700/50 overflow-hidden text-xs max-h-44 overflow-y-auto">
            <table className="min-w-full text-left text-slate-300">
              <thead className="bg-slate-800/80 text-slate-400 sticky top-0">
                <tr>
                  <th className="px-2 py-1.5 font-normal">Дата</th>
                  <th className="px-2 py-1.5 font-normal">Модель</th>
                  <th className="px-2 py-1.5 font-normal">Чаттер</th>
                  <th className="px-2 py-1.5 font-normal text-right">Сумма</th>
                </tr>
              </thead>
              <tbody>
                {aiData.preview.map((row, i) => (
                  <tr key={i} className="border-t border-slate-700/30">
                    <td className="px-2 py-1 whitespace-nowrap">{String(row.date ?? '—')}</td>
                    <td className="px-2 py-1 max-w-[120px] truncate">{String(row.model ?? '—')}</td>
                    <td className="px-2 py-1 max-w-[120px] truncate">{String(row.chatter ?? '—')}</td>
                    <td className="px-2 py-1 text-right text-emerald-400">
                      {row.amount !== null && row.amount !== undefined && row.amount !== ''
                        ? `$${Number(row.amount).toFixed(2)}`
                        : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Button className="w-full" onClick={handleContinue}>
            Далее — импорт
          </Button>
          <button
            type="button"
            onClick={() => { setStage('drop'); setAiData(null); setFileName('') }}
            className="w-full text-xs text-slate-500 hover:text-slate-300"
          >
            Загрузить другой файл
          </button>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────── Google Sheets sub-flow ───────────────────────────

function GoogleSheetsConnect({
  onComplete,
  data,
}: {
  onComplete: (data: Record<string, unknown>) => void
  data: Record<string, unknown>
}) {
  const [stage, setStage] = useState<Stage>('connect')
  const [spreadsheets, setSpreadsheets] = useState<Spreadsheet[]>([])
  const [sheets, setSheets] = useState<Sheet[]>([])
  const [selectedSpreadsheet, setSelectedSpreadsheet] = useState<string>(
    String((data.spreadsheet_id as string) ?? '')
  )
  const [selectedSheet, setSelectedSheet] = useState<string>(String((data.sheet_name as string) ?? ''))
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const loadSpreadsheets = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const res = await api.get<{ spreadsheets: Spreadsheet[] }>('/api/v1/google/spreadsheets')
      setSpreadsheets(res.data.spreadsheets)
      setStage('spreadsheets')
    } catch (e) {
      setErr(formatApiError(e))
    } finally {
      setLoading(false)
    }
  }, [])

  // Стартовая инициализация: проверяем URL params после OAuth-редиректа
  // и /status, чтобы не заставлять заново жать «Войти через Google».
  useEffect(() => {
    let cancelled = false
    const init = async () => {
      const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null
      const googleError = params?.get('google_error')
      const googleConnected = params?.get('google_connected') === 'true'

      if (googleError) {
        setErr(`Google вернул ошибку: ${googleError}`)
        if (params && typeof window !== 'undefined') {
          // Чистим URL, чтобы повторные перезагрузки не показывали ошибку.
          const url = new URL(window.location.href)
          url.searchParams.delete('google_error')
          url.searchParams.delete('google_connected')
          window.history.replaceState({}, '', url.toString())
        }
      }

      try {
        const res = await api.get<GoogleStatus>('/api/v1/google/status')
        if (cancelled) return
        if (res.data.connected) {
          // Подключение есть — сразу к выбору таблицы.
          if (params && typeof window !== 'undefined') {
            const url = new URL(window.location.href)
            url.searchParams.delete('google_connected')
            window.history.replaceState({}, '', url.toString())
          }
          await loadSpreadsheets()
          return
        }
        if (googleConnected) {
          // Status ещё не отразил подключение — пробуем подгрузить таблицы напрямую.
          await loadSpreadsheets()
          return
        }
      } catch {
        // молчим: оставляем стартовую кнопку
      }
    }
    void init()
    return () => {
      cancelled = true
    }
  }, [loadSpreadsheets])

  const connectGoogle = async () => {
    setErr(null)
    setLoading(true)
    try {
      const res = await api.get<{ url: string }>('/api/v1/google/auth-url')
      if (typeof window !== 'undefined') {
        window.location.href = res.data.url
      }
    } catch (e) {
      setErr(formatApiError(e))
      setLoading(false)
    }
  }

  const selectSpreadsheet = async (id: string) => {
    setSelectedSpreadsheet(id)
    setSelectedSheet('')
    setLoading(true)
    setErr(null)
    try {
      const res = await api.get<{ sheets: Sheet[] }>(`/api/v1/google/sheets/${encodeURIComponent(id)}`)
      setSheets(res.data.sheets)
      setStage('sheets')
    } catch (e) {
      setErr(formatApiError(e))
    } finally {
      setLoading(false)
    }
  }

  const handleNext = () => {
    if (!selectedSpreadsheet || !selectedSheet) return
    const chosen = spreadsheets.find((s) => s.id === selectedSpreadsheet)
    onComplete({
      spreadsheet_id: selectedSpreadsheet,
      sheet_name: selectedSheet,
      spreadsheet_name: chosen?.name ?? '',
    })
  }

  const heading = useMemo(() => {
    if (stage === 'connect') return 'Подключи Google Таблицы'
    if (stage === 'spreadsheets') return 'Выбери таблицу'
    return 'Выбери лист'
  }, [stage])

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100 mb-2">{heading}</h2>

      {stage === 'connect' && (
        <>
          <p className="text-slate-400 text-sm mb-6">
            Запрашиваем доступ только на чтение (Sheets + Drive). Данные не передаются третьим лицам.
          </p>
          {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
          <Button className="w-full" onClick={connectGoogle} disabled={loading}>
            {loading ? 'Открываем Google…' : 'Войти через Google'}
          </Button>
        </>
      )}

      {stage === 'spreadsheets' && (
        <>
          <p className="text-slate-400 text-sm mb-4">
            Последние таблицы из твоего Google Drive. Выбери ту, где лежат транзакции.
          </p>
          {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
          {loading && <p className="text-slate-500 text-xs mb-2">Загружаем таблицы…</p>}
          <div className="space-y-2 mb-4 max-h-80 overflow-y-auto">
            {spreadsheets.length === 0 && !loading && (
              <p className="text-slate-500 text-sm">В Google Drive не найдено таблиц.</p>
            )}
            {spreadsheets.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => selectSpreadsheet(s.id)}
                className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
                  selectedSpreadsheet === s.id
                    ? 'border-indigo-500 bg-indigo-500/10 text-slate-100'
                    : 'border-slate-700 bg-slate-800/40 text-slate-300 hover:border-slate-600'
                }`}
              >
                <p className="font-medium">{s.name}</p>
                {s.modifiedTime && (
                  <p className="text-xs text-slate-500 mt-0.5">
                    Изменено: {new Date(s.modifiedTime).toLocaleDateString('ru')}
                  </p>
                )}
              </button>
            ))}
          </div>
          <Button variant="outline" className="w-full" onClick={() => loadSpreadsheets()} disabled={loading}>
            Обновить список
          </Button>
        </>
      )}

      {stage === 'sheets' && (
        <>
          <p className="text-slate-400 text-sm mb-4">
            На каком листе таблицы лежат транзакции?
          </p>
          {err && <p className="text-red-400 text-sm mb-3">{err}</p>}
          {loading && <p className="text-slate-500 text-xs mb-2">Загружаем листы…</p>}
          <div className="space-y-2 mb-6 max-h-60 overflow-y-auto">
            {sheets.map((s) => (
              <button
                key={String(s.id)}
                type="button"
                onClick={() => setSelectedSheet(s.name)}
                className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${
                  selectedSheet === s.name
                    ? 'border-indigo-500 bg-indigo-500/10 text-slate-100'
                    : 'border-slate-700 bg-slate-800/40 text-slate-300 hover:border-slate-600'
                }`}
              >
                <p className="font-medium">{s.name}</p>
              </button>
            ))}
          </div>
          <Button className="w-full" disabled={!selectedSheet} onClick={handleNext}>
            Далее — анализ AI
          </Button>
          <button
            type="button"
            className="w-full text-slate-500 hover:text-slate-300 text-xs mt-3"
            onClick={() => setStage('spreadsheets')}
          >
            ← Назад к выбору таблицы
          </button>
        </>
      )}
    </div>
  )
}
