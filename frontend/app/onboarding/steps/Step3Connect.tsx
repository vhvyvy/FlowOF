'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import api, { formatApiError } from '@/lib/api'

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
