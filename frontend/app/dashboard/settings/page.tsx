'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult } from '@tanstack/react-query'
import api from '@/lib/api'
import { TEAM_COLOR_OPTIONS, teamColor } from '@/lib/teamColors'
import { Header } from '@/components/layout/Header'
import { Skeleton } from '@/components/ui/skeleton'
import { Save, RefreshCw, AlertCircle, CheckCircle2, Key, Eye, EyeOff, Users, Pencil, Trash2, Check, X, CloudDownload } from 'lucide-react'
import type { TeamOut } from '@/types'

interface Settings {
  model_percent: string
  chatter_percent: string
  admin_percent: string
  withdraw_percent: string
  use_withdraw: string
  use_retention: string
  /** ID баз Notion с расходами, через запятую; глобально для агентства, не по командам */
  notion_expenses_database_ids: string
}

const DEFAULTS: Settings = {
  model_percent: '23',
  chatter_percent: '25',
  admin_percent: '9',
  withdraw_percent: '6',
  use_withdraw: '1',
  use_retention: '1',
  notion_expenses_database_ids: '',
}

interface NotionSyncResult {
  inserted: number
  updated: number
  skipped: number
  skipped_no_model?: number
  skipped_parse?: number
  databases: number
  assigned_rows: number
  message: string
}

type NotionImportMutation = UseMutationResult<NotionSyncResult, Error, void, unknown>

function useNotionImportMutation(): NotionImportMutation {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      api.post<NotionSyncResult>('/api/v1/sync/notion-transactions').then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
      qc.invalidateQueries({ queryKey: ['chatters'] })
    },
  })
}

function syncErrorDetail(err: unknown): string {
  return (
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Ошибка импорта'
  )
}

function SliderRow({
  label, hint, value, onChange, max = 60,
}: {
  label: string; hint: string; value: number; onChange: (v: number) => void; max?: number
}) {
  return (
    <div className="py-4 border-b border-slate-700/40 last:border-0">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-sm font-medium text-slate-200">{label}</p>
          <p className="text-xs text-slate-500 mt-0.5">{hint}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            max={max}
            value={value}
            onChange={(e) => onChange(Math.min(max, Math.max(0, Number(e.target.value))))}
            className="w-14 text-right bg-slate-700 border border-slate-600 rounded-lg px-2 py-1 text-sm font-bold text-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <span className="text-sm text-slate-400 w-3">%</span>
        </div>
      </div>
      <div className="relative">
        <input
          type="range"
          min={0}
          max={max}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-2 rounded-full appearance-none cursor-pointer accent-indigo-500"
          style={{
            background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${(value / max) * 100}%, #334155 ${(value / max) * 100}%, #334155 100%)`
          }}
        />
      </div>
    </div>
  )
}

function ToggleRow({
  label, hint, checked, onChange,
}: {
  label: string; hint: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between py-4 border-b border-slate-700/40 last:border-0">
      <div>
        <p className="text-sm font-medium text-slate-200">{label}</p>
        <p className="text-xs text-slate-500 mt-0.5">{hint}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ${checked ? 'bg-indigo-500' : 'bg-slate-600'}`}
      >
        <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-md transition-transform duration-200 mt-0.5 ${checked ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </button>
    </div>
  )
}

interface ProfileOut {
  name: string
  email: string
  has_onlymonster_key: boolean
  onlymonster_key_preview: string | null
  has_notion_token?: boolean
  notion_token_preview?: string | null
}

function GlobalExpensesNotionSection({
  value,
  onChange,
  notionImport,
  onSaveThenImport,
  savePending,
  saveDisabled,
}: {
  value: string
  onChange: (v: string) => void
  notionImport: NotionImportMutation
  /** Сохраняет настройки на сервер, затем запускает тот же импорт, что и кнопка ниже (актуальные ID расходов). */
  onSaveThenImport: () => void
  savePending: boolean
  saveDisabled: boolean
}) {
  const busy = notionImport.isPending || savePending
  return (
    <div className="bg-slate-800/60 border border-amber-500/20 rounded-xl px-5 py-5 space-y-3">
      <p className="text-xs font-semibold text-amber-200/90 uppercase tracking-widest">Глобальные расходы (Notion)</p>
      <p className="text-xs text-slate-500">
        Расходы относятся ко всему агентству. Укажите ID баз(ы) с расходами; несколько ID — через запятую.
        Кнопка «Сохранить» внизу страницы <span className="text-slate-400">только записывает настройки</span> в базу —{' '}
        строки из Notion сами не подтягиваются, пока вы не нажмёте загрузку ниже (или в блоке «Команды»).
      </p>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Можно вставить ссылку из Notion или 32-символьный ID; несколько — через запятую"
        rows={2}
        className="w-full bg-slate-700/80 border border-slate-600 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 placeholder-slate-500"
      />
      <div className="flex flex-wrap gap-2 items-center">
        <button
          type="button"
          onClick={() => notionImport.mutate()}
          disabled={busy}
          className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 border border-indigo-500 text-white disabled:opacity-50"
        >
          {notionImport.isPending && !savePending ? (
            <RefreshCw className="h-4 w-4 animate-spin" />
          ) : (
            <CloudDownload className="h-4 w-4" />
          )}
          Загрузить из Notion (транзакции + расходы)
        </button>
        <button
          type="button"
          onClick={onSaveThenImport}
          disabled={busy || saveDisabled}
          className="text-sm px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-200 disabled:opacity-50"
        >
          {savePending ? (
            <span className="inline-flex items-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin" /> Сохранение…
            </span>
          ) : notionImport.isPending ? (
            <span className="inline-flex items-center gap-2">
              <RefreshCw className="h-4 w-4 animate-spin" /> Загрузка из Notion…
            </span>
          ) : (
            'Сохранить ID и загрузить из Notion'
          )}
        </button>
      </div>
      {notionImport.isSuccess && notionImport.data && (
        <p className="text-xs text-emerald-400 whitespace-pre-wrap">{notionImport.data.message}</p>
      )}
      {notionImport.isError && (
        <p className="text-xs text-red-400">{syncErrorDetail(notionImport.error)}</p>
      )}
      <p className="text-[11px] text-slate-600">
        В таблице расходов должны быть колонки с <span className="text-slate-500">датой</span> и{' '}
        <span className="text-slate-500">суммой</span> (как в Notion). Альтернатива для сервера: переменная{' '}
        <code className="text-slate-500">NOTION_EXPENSES_DATABASE_ID</code>.
      </p>
    </div>
  )
}

function TeamsSection({ notionImport }: { notionImport: NotionImportMutation }) {
  const qc = useQueryClient()
  const [name, setName] = useState('Команда 2')
  const [notionId, setNotionId] = useState('')
  const [chatterMax, setChatterMax] = useState(22)
  const [adminTotal, setAdminTotal] = useState(8)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [teamDrafts, setTeamDrafts] = useState<Record<number, {
    color_key: string | null
    chatter_max_pct: number | null
    default_chatter_pct: number | null
    admin_percent_total: number | null
    inherit_economics: boolean
    notion_database_id: string | null
  }>>({})

  const { data: teams, isLoading } = useQuery({
    queryKey: ['teams'],
    queryFn: () => api.get<TeamOut[]>('/api/v1/teams').then((r) => r.data),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['teams'] })
    qc.invalidateQueries({ queryKey: ['overview'] })
    qc.invalidateQueries({ queryKey: ['finance'] })
    qc.invalidateQueries({ queryKey: ['chatters'] })
  }

  const createMut = useMutation({
    mutationFn: () =>
      api.post('/api/v1/teams', {
        name: name.trim() || 'Команда',
        inherit_economics: false,
        notion_database_id: notionId.trim() || undefined,
        chatter_max_pct: chatterMax,
        default_chatter_pct: chatterMax,
        admin_percent_total: adminTotal,
      }),
    onSuccess: invalidate,
  })

  const renameMut = useMutation({
    mutationFn: ({ id, newName }: { id: number; newName: string }) =>
      api.patch(`/api/v1/teams/${id}`, { name: newName }),
    onSuccess: () => { setEditingId(null); invalidate() },
  })

  const updateEcoMut = useMutation({
    mutationFn: (payload: {
      id: number
      color_key: string | null
      chatter_max_pct: number | null
      default_chatter_pct: number | null
      admin_percent_total: number | null
      inherit_economics: boolean
      notion_database_id: string | null
    }) =>
      api.patch(`/api/v1/teams/${payload.id}`, {
        color_key: payload.color_key,
        chatter_max_pct: payload.chatter_max_pct,
        default_chatter_pct: payload.default_chatter_pct,
        admin_percent_total: payload.admin_percent_total,
        inherit_economics: payload.inherit_economics,
        notion_database_id: payload.notion_database_id?.trim() || null,
      }),
    onSuccess: invalidate,
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/teams/${id}`),
    onSuccess: () => { setDeletingId(null); invalidate() },
  })

  const reconcileMut = useMutation({
    mutationFn: () =>
      api
        .post<{ assigned_rows: number; backfilled_pages: number }>('/api/v1/teams/reconcile-notion')
        .then((r) => r.data),
    onSuccess: invalidate,
  })

  const [debugResult, setDebugResult] = useState<Record<string, unknown> | null>(null)
  const [debugLoading, setDebugLoading] = useState(false)
  const runDebug = async () => {
    setDebugLoading(true)
    setDebugResult(null)
    try {
      const r = await api.get<Record<string, unknown>>('/api/v1/sync/debug-chatter-fields')
      setDebugResult(r.data)
    } catch (e: unknown) {
      setDebugResult({ error: (e as { message?: string })?.message ?? String(e) })
    } finally {
      setDebugLoading(false)
    }
  }

  const defaultTeamId = teams?.[0]?.id

  useEffect(() => {
    if (!teams) return
    const next: typeof teamDrafts = {}
    for (const t of teams) {
      next[t.id] = {
        color_key: t.color_key ?? null,
        chatter_max_pct: t.chatter_max_pct ?? null,
        default_chatter_pct: t.default_chatter_pct ?? null,
        admin_percent_total: t.admin_percent_total ?? null,
        inherit_economics: t.inherit_economics,
        notion_database_id: t.notion_database_id ?? null,
      }
    }
    setTeamDrafts(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teams])

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-5 space-y-4">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-indigo-400" />
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Команды</p>
      </div>
      <p className="text-xs text-slate-500">
        У каждой команды своя база <span className="text-slate-400">транзакций</span> в Notion и свои проценты (если не
        включено «Наследовать»). Глобальные проценты по умолчанию — в блоке «Распределение выручки» ниже. Для импорта
        нужен Notion token в «Интеграциях».
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => reconcileMut.mutate()}
          disabled={reconcileMut.isPending}
          className="text-sm px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 border border-slate-600 text-slate-200 disabled:opacity-50"
        >
          {reconcileMut.isPending ? 'Сопоставление…' : 'Сопоставить транзакции с командами (Notion)'}
        </button>
        <button
          type="button"
          onClick={() => notionImport.mutate()}
          disabled={notionImport.isPending}
          className="text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 border border-indigo-500 text-white disabled:opacity-50"
        >
          {notionImport.isPending ? 'Загрузка из Notion…' : 'Загрузить транзакции из Notion в базу'}
        </button>
      </div>
      {notionImport.isSuccess && notionImport.data && (
        <p className="text-xs text-emerald-400 whitespace-pre-wrap">{notionImport.data.message}</p>
      )}
      {notionImport.isError && (
        <p className="text-xs text-red-400">{syncErrorDetail(notionImport.error)}</p>
      )}
      {reconcileMut.isSuccess && reconcileMut.data && (
        <p className="text-xs text-emerald-400">
          Обновлено страниц из API: {reconcileMut.data.backfilled_pages}, привязано строк:{' '}
          {reconcileMut.data.assigned_rows}
        </p>
      )}

      {/* Диагностика: почему чаттер не парсится */}
      <div className="pt-1">
        <button
          type="button"
          onClick={runDebug}
          disabled={debugLoading}
          className="text-xs px-3 py-1.5 rounded-lg bg-slate-700/60 hover:bg-slate-600/60 border border-slate-600/50 text-slate-400 hover:text-slate-200 disabled:opacity-50"
        >
          {debugLoading ? 'Диагностика…' : '🔍 Диагностика: почему чаттер не парсится?'}
        </button>
        {debugResult && (
          <div className="mt-2 p-3 bg-slate-900 rounded-lg border border-slate-700 text-xs font-mono text-slate-300 overflow-auto max-h-72 whitespace-pre-wrap">
            {JSON.stringify(debugResult, null, 2)}
          </div>
        )}
      </div>

      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="space-y-4">
          {teams?.map((t) => {
            const isDefault = t.id === defaultTeamId
            const isEditing = editingId === t.id
            const isDeleting = deletingId === t.id
            const d = teamDrafts[t.id] ?? {
              notion_database_id: t.notion_database_id ?? null,
              color_key: t.color_key ?? null,
              chatter_max_pct: t.chatter_max_pct ?? null,
              default_chatter_pct: t.default_chatter_pct ?? null,
              admin_percent_total: t.admin_percent_total ?? null,
              inherit_economics: t.inherit_economics,
            }
            const c = teamColor(t.id, d.color_key)
            return (
              <div
                key={t.id}
                className={`flex flex-col gap-3 text-sm rounded-xl px-4 py-4 border ${c.bg} ${c.border}`}
              >
                {isEditing ? (
                  <>
                    <input
                      autoFocus
                      value={editingName}
                      onChange={(e) => setEditingName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') renameMut.mutate({ id: t.id, newName: editingName })
                        if (e.key === 'Escape') setEditingId(null)
                      }}
                      className="flex-1 min-w-0 bg-slate-700 border border-indigo-500 rounded px-2 py-0.5 text-sm text-slate-200 focus:outline-none"
                    />
                    <button
                      onClick={() => renameMut.mutate({ id: t.id, newName: editingName })}
                      disabled={renameMut.isPending || !editingName.trim()}
                      className="p-1 text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
                      title="Сохранить"
                    >
                      <Check className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="p-1 text-slate-500 hover:text-slate-300"
                      title="Отмена"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </>
                ) : isDeleting ? (
                  <>
                    <span className="flex-1 text-rose-300 text-xs">Удалить «{t.name}»? Транзакции перейдут в основную.</span>
                    <button
                      onClick={() => deleteMut.mutate(t.id)}
                      disabled={deleteMut.isPending}
                      className="text-xs px-2 py-1 rounded bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-50"
                    >
                      {deleteMut.isPending ? '…' : 'Да, удалить'}
                    </button>
                    <button
                      onClick={() => setDeletingId(null)}
                      className="text-xs px-2 py-1 rounded bg-slate-600 hover:bg-slate-500 text-slate-200"
                    >
                      Отмена
                    </button>
                  </>
                ) : (
                  <>
                    <div className="flex flex-wrap items-center gap-2 w-full">
                      <span className="flex-1 min-w-0 font-medium text-slate-200">{t.name}</span>
                      <span className="text-xs text-slate-500">
                        {t.inherit_economics
                          ? 'экономика как в настройках'
                          : `чаттер ≤${t.chatter_max_pct ?? '—'}%, админы ${t.admin_percent_total ?? '—'}%`}
                      </span>
                      <button
                        onClick={() => { setEditingId(t.id); setEditingName(t.name) }}
                        className="p-1 text-slate-500 hover:text-slate-300"
                        title="Переименовать"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      {!isDefault && (
                        <button
                          onClick={() => setDeletingId(t.id)}
                          className="p-1 text-slate-500 hover:text-rose-400"
                          title="Удалить команду"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                    <label className="text-[11px] text-slate-500 w-full block">
                      Notion: database ID (транзакции этой команды)
                      <input
                        type="text"
                        value={d.notion_database_id ?? ''}
                        onChange={(e) =>
                          setTeamDrafts((prev) => ({
                            ...prev,
                            [t.id]: { ...d, notion_database_id: e.target.value.trim() || null },
                          }))
                        }
                        placeholder="Ссылка из Notion или 32-символьный ID"
                        className="mt-1 w-full bg-slate-700/80 border border-slate-600 rounded-lg px-2 py-1.5 text-xs font-mono text-slate-200"
                      />
                    </label>
                    <div className="w-full grid grid-cols-1 md:grid-cols-5 gap-2">
                      <label className="text-[11px] text-slate-500">
                        Цвет
                        <select
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
                          value={d.color_key ?? ''}
                          onChange={(e) =>
                            setTeamDrafts((prev) => ({
                              ...prev,
                              [t.id]: { ...d, color_key: e.target.value || null },
                            }))
                          }
                        >
                          <option value="">Авто</option>
                          {TEAM_COLOR_OPTIONS.map((opt) => (
                            <option key={opt.key} value={opt.key}>
                              {opt.key}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="text-[11px] text-slate-500">
                        Макс чаттер %
                        <input
                          type="number"
                          value={d.chatter_max_pct ?? ''}
                          onChange={(e) =>
                            setTeamDrafts((prev) => ({
                              ...prev,
                              [t.id]: {
                                ...d,
                                chatter_max_pct: e.target.value === '' ? null : Number(e.target.value),
                              },
                            }))
                          }
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
                        />
                      </label>
                      <label className="text-[11px] text-slate-500">
                        Дефолт чаттер %
                        <input
                          type="number"
                          value={d.default_chatter_pct ?? ''}
                          onChange={(e) =>
                            setTeamDrafts((prev) => ({
                              ...prev,
                              [t.id]: {
                                ...d,
                                default_chatter_pct: e.target.value === '' ? null : Number(e.target.value),
                              },
                            }))
                          }
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
                        />
                      </label>
                      <label className="text-[11px] text-slate-500">
                        Админы %
                        <input
                          type="number"
                          value={d.admin_percent_total ?? ''}
                          onChange={(e) =>
                            setTeamDrafts((prev) => ({
                              ...prev,
                              [t.id]: {
                                ...d,
                                admin_percent_total: e.target.value === '' ? null : Number(e.target.value),
                              },
                            }))
                          }
                          className="mt-1 w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200"
                        />
                      </label>
                      <div className="flex items-end gap-2">
                        <button
                          type="button"
                          onClick={() =>
                            updateEcoMut.mutate({
                              id: t.id,
                              notion_database_id: d.notion_database_id,
                              color_key: d.color_key,
                              chatter_max_pct: d.chatter_max_pct,
                              default_chatter_pct: d.default_chatter_pct,
                              admin_percent_total: d.admin_percent_total,
                              inherit_economics: d.inherit_economics,
                            })
                          }
                          disabled={updateEcoMut.isPending}
                          className="text-xs px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white"
                        >
                          {updateEcoMut.isPending ? '…' : 'Сохранить'}
                        </button>
                        <label className="text-[11px] text-slate-500 flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={d.inherit_economics}
                            onChange={(e) =>
                              setTeamDrafts((prev) => ({
                                ...prev,
                                [t.id]: { ...d, inherit_economics: e.target.checked },
                              }))
                            }
                          />
                          Наследовать
                        </label>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}

      {teams && teams.length >= 1 && (
        <div className="border-t border-slate-700/50 pt-4 space-y-3">
          <p className="text-xs text-slate-400">Добавить команду с отдельной экономикой</p>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название"
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200"
          />
          <input
            type="text"
            value={notionId}
            onChange={(e) => setNotionId(e.target.value)}
            placeholder="Notion database ID (транзакции команды)"
            className="w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm font-mono text-slate-300"
          />
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-500">
              Макс % чаттерам
              <input
                type="number"
                value={chatterMax}
                onChange={(e) => setChatterMax(Number(e.target.value))}
                className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Админы всего %
              <input
                type="number"
                value={adminTotal}
                onChange={(e) => setAdminTotal(Number(e.target.value))}
                className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-2 py-1.5 text-sm"
              />
            </label>
          </div>
          <button
            type="button"
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending}
            className="text-sm px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50"
          >
            {createMut.isPending ? 'Создание…' : 'Добавить команду'}
          </button>
        </div>
      )}
    </div>
  )
}

function IntegrationsSection() {
  const qc = useQueryClient()
  const [omKey, setOmKey] = useState('')
  const [omIds, setOmIds] = useState('')
  const [notionToken, setNotionToken] = useState('')
  const [show, setShow] = useState(false)
  const [showNotion, setShowNotion] = useState(false)
  const [saved, setSaved] = useState(false)

  const { data: profile } = useQuery<ProfileOut>({
    queryKey: ['profile'],
    queryFn: () => api.get('/api/v1/profile').then(r => r.data),
  })

  const mutation = useMutation({
    mutationFn: () => api.patch('/api/v1/profile', {
      onlymonster_key: omKey || undefined,
      onlymonster_account_ids: omIds || undefined,
      notion_token: notionToken || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profile'] })
      qc.invalidateQueries({ queryKey: ['kpi'] })
      setSaved(true)
      setOmKey('')
      setNotionToken('')
      setTimeout(() => setSaved(false), 3000)
    },
  })

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-5 space-y-4">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Интеграции</p>

      <div className="space-y-3">
        <div>
          <label className="text-sm font-medium text-slate-200 flex items-center gap-2 mb-1.5">
            <Key className="h-3.5 w-3.5 text-amber-400" />
            Notion — Internal Integration Secret
          </label>
          {profile?.has_notion_token && !notionToken && (
            <p className="text-xs text-emerald-400 mb-2 flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              Токен сохранён: <span className="font-mono">{profile.notion_token_preview}</span>
            </p>
          )}
          <div className="relative">
            <input
              type={showNotion ? 'text' : 'password'}
              value={notionToken}
              onChange={(e) => setNotionToken(e.target.value)}
              placeholder={profile?.has_notion_token ? 'Вставьте новый токен для замены' : 'secret_… из notion.so/my-integrations'}
              className="w-full bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 pr-10 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 font-mono"
            />
            <button
              type="button"
              onClick={() => setShowNotion((s) => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              {showNotion ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Нужен для кнопок «Загрузить из Notion» и сопоставления команд. Интеграцию добавьте в каждую базу Notion (Share → Connections).
          </p>
        </div>

        <div>
          <label className="text-sm font-medium text-slate-200 flex items-center gap-2 mb-1.5">
            <Key className="h-3.5 w-3.5 text-indigo-400" />
            Onlymonster API Key
          </label>
          {profile?.has_onlymonster_key && !omKey && (
            <p className="text-xs text-emerald-400 mb-2 flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />
              Ключ сохранён: <span className="font-mono">{profile.onlymonster_key_preview}</span>
            </p>
          )}
          <div className="relative">
            <input
              type={show ? 'text' : 'password'}
              value={omKey}
              onChange={e => setOmKey(e.target.value)}
              placeholder={profile?.has_onlymonster_key ? 'Введите новый ключ для замены' : 'Вставьте API-ключ из Onlymonster'}
              className="w-full bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 pr-10 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
            />
            <button
              type="button"
              onClick={() => setShow(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-xs text-slate-500 mt-1">Найдёте в личном кабинете Onlymonster → Settings → API</p>
        </div>

        <div>
          <label className="text-sm font-medium text-slate-200 mb-1.5 block">
            Account IDs <span className="text-slate-500 font-normal text-xs">(опционально, через запятую)</span>
          </label>
          <input
            type="text"
            value={omIds}
            onChange={e => setOmIds(e.target.value)}
            placeholder={profile?.has_onlymonster_key ? 'Оставьте пустым чтобы не менять' : 'напр. 12345, 67890'}
            className="w-full bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
          />
          <p className="text-xs text-slate-500 mt-1">ID аккаунтов для фильтрации метрик. Оставьте пустым — подтянутся все.</p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || (!omKey && !omIds && !notionToken)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
          >
            {mutation.isPending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Сохранить
          </button>
          {saved && <span className="text-xs text-emerald-400 flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> Сохранено</span>}
          {mutation.isError && <span className="text-xs text-rose-400 flex items-center gap-1"><AlertCircle className="h-3.5 w-3.5" /> Ошибка</span>}
          {profile?.has_onlymonster_key && (
            <button
              onClick={() => { setOmKey(' '); mutation.mutate() }}
              className="text-xs text-rose-400 hover:text-rose-300 transition-colors"
            >
              Удалить ключ
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const notionImport = useNotionImportMutation()
  const [local, setLocal] = useState<Settings>(DEFAULTS)
  const [saved, setSaved] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/api/v1/settings').then((r) => r.data.settings as Settings),
  })

  useEffect(() => { if (data) setLocal(data) }, [data])

  const mutation = useMutation({
    mutationFn: (s: Settings) => api.put('/api/v1/settings', s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const set = (key: keyof Settings, value: string) =>
    setLocal((prev) => ({ ...prev, [key]: value }))

  const model = Number(local.model_percent)
  const chatter = Number(local.chatter_percent)
  const admin = Number(local.admin_percent)
  const withdraw = Number(local.withdraw_percent)
  const useWithdraw = local.use_withdraw === '1'
  const useRetention = local.use_retention === '1'

  const totalDeductions = model + chatter + admin + (useWithdraw ? withdraw : 0)
  const retentionBonus = useRetention ? (model + chatter) * 0.025 : 0
  const agencyPct = 100 - totalDeductions + retentionBonus
  const overLimit = totalDeductions > 100

  const saveThenImportFromNotion = () => {
    mutation.mutate(local, {
      onSuccess: () => {
        notionImport.mutate()
      },
    })
  }

  if (isLoading) return (
    <div className="flex flex-col h-full">
      <Header title="Настройки" />
      <div className="flex-1 p-6 space-y-4 overflow-y-auto max-w-xl">
        {[1,2,3,4].map(i => <Skeleton key={i} className="h-20 bg-slate-800 rounded-xl" />)}
      </div>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <Header title="Настройки" />
      <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl space-y-6">

      <IntegrationsSection />

      <GlobalExpensesNotionSection
        value={local.notion_expenses_database_ids}
        onChange={(v) => set('notion_expenses_database_ids', v)}
        notionImport={notionImport}
        onSaveThenImport={saveThenImportFromNotion}
        savePending={mutation.isPending}
        saveDisabled={overLimit}
      />

      <TeamsSection notionImport={notionImport} />

      {/* Sliders — глобальные проценты по умолчанию */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest pt-5 pb-2">Распределение выручки</p>
        <p className="text-[11px] text-slate-500 pb-2">
          Базовые доли для агентства; у команды могут быть свои значения, если отключено «Наследовать».
        </p>
        <SliderRow label="Модель" hint="Доля модели от выручки" value={model} onChange={(v) => set('model_percent', String(v))} />
        <SliderRow label="Чаттеры" hint="Доля чаттеров от выручки" value={chatter} onChange={(v) => set('chatter_percent', String(v))} />
        <SliderRow label="Админы" hint="Доля администраторов" value={admin} onChange={(v) => set('admin_percent', String(v))} />
        <SliderRow label="Вывод" hint="Комиссия за вывод средств" value={withdraw} onChange={(v) => set('withdraw_percent', String(v))} />
      </div>

      {/* Toggles */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest pt-5 pb-2">Дополнительно</p>
        <ToggleRow
          label="Комиссия вывода"
          hint={`Учитывать ${withdraw}% от выручки как комиссию платформы`}
          checked={useWithdraw}
          onChange={(v) => set('use_withdraw', v ? '1' : '0')}
        />
        <ToggleRow
          label="Retention 2.5%"
          hint="Агентство получает 2.5% от доли модели и чаттера обратно"
          checked={useRetention}
          onChange={(v) => set('use_retention', v ? '1' : '0')}
        />
      </div>

      {/* Summary */}
      <div className={`rounded-xl border px-5 py-4 ${overLimit ? 'bg-red-900/20 border-red-700/50' : 'bg-slate-800/60 border-slate-700/50'}`}>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3">Структура</p>
        <div className="space-y-1.5 text-sm">
          {[
            { label: 'Модель', value: model },
            { label: 'Чаттеры', value: chatter },
            { label: 'Админы', value: admin },
            ...(useWithdraw ? [{ label: 'Вывод', value: withdraw }] : []),
          ].map(({ label, value }) => (
            <div key={label} className="flex justify-between">
              <span className="text-slate-400">{label}</span>
              <span className="text-slate-300">{value}%</span>
            </div>
          ))}
          <div className="flex justify-between pt-2 mt-2 border-t border-slate-700">
            <span className="text-slate-400">Итого удержаний</span>
            <span className={`font-semibold ${overLimit ? 'text-red-400' : 'text-slate-200'}`}>{totalDeductions}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Агентству остаётся</span>
            <span className={`font-bold text-base ${agencyPct < 0 ? 'text-red-400' : 'text-emerald-400'}`}>≈{agencyPct.toFixed(1)}%</span>
          </div>
        </div>
        {overLimit && (
          <div className="flex items-center gap-2 mt-3 text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Сумма превышает 100% — проверьте значения
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-4">
          <button
            onClick={() => mutation.mutate(local)}
            disabled={mutation.isPending || overLimit}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
          >
            {mutation.isPending
              ? <RefreshCw className="h-4 w-4 animate-spin" />
              : <Save className="h-4 w-4" />}
            Сохранить
          </button>
          {saved && (
            <span className="flex items-center gap-1.5 text-emerald-400 text-sm">
              <CheckCircle2 className="h-4 w-4" /> Сохранено
            </span>
          )}
          {mutation.isError && (
            <span className="flex items-center gap-1.5 text-red-400 text-sm">
              <AlertCircle className="h-4 w-4" /> Ошибка
            </span>
          )}
        </div>
        <p className="text-[11px] text-slate-500 max-w-xl">
          Сохранение не запускает импорт из Notion. Чтобы подтянуть транзакции и расходы в базу, нажмите «Загрузить из
          Notion» в блоке «Глобальные расходы» выше или в «Команды», либо «Сохранить ID и загрузить из Notion».
        </p>
      </div>
      </div>
      </div>
    </div>
  )
}
