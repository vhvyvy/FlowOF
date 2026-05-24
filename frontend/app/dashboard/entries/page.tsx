'use client'

import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'
import { Header } from '@/components/layout/Header'
import { AddTransactionForm } from '@/components/entries/AddTransactionForm'
import { SourceBadge } from '@/components/entries/SourceBadge'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Pencil, Trash2, Check, X, Loader2, RefreshCw } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TxRow {
  id: number
  date: string
  amount: string | number
  source: string
  model_id: number | null
  chatter_id: number | null
  shift_catalog_id: number | null
  model_name: string | null
  chatter_name: string | null
  shift_name: string | null
}

interface CatalogItem { id: number; name: string }

// ─── Edit form state ──────────────────────────────────────────────────────────

interface EditState {
  date: string
  model_id: string
  chatter_id: string
  shift_catalog_id: string
  amount: string
}

function rowToEdit(row: TxRow): EditState {
  return {
    date: row.date,
    model_id: row.model_id != null ? String(row.model_id) : '',
    chatter_id: row.chatter_id != null ? String(row.chatter_id) : '',
    shift_catalog_id: row.shift_catalog_id != null ? String(row.shift_catalog_id) : '',
    amount: String(row.amount),
  }
}

// ─── Filter tab ───────────────────────────────────────────────────────────────

const SOURCE_TABS: { label: string; value: string }[] = [
  { label: 'Все', value: '' },
  { label: 'Вручную', value: 'manual' },
  { label: 'Google Sheets', value: 'google_sheets' },
  { label: 'Импорт', value: 'import' },
]

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function EntriesPage() {
  const { month, year } = useMonthStore()
  const [rows, setRows] = useState<TxRow[]>([])
  const [loading, setLoading] = useState(true)
  const [sourceFilter, setSourceFilter] = useState('')
  const [editId, setEditId] = useState<number | null>(null)
  const [editState, setEditState] = useState<EditState | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)

  // Catalog for edit selects
  const [models, setModels] = useState<CatalogItem[]>([])
  const [chatters, setChatters] = useState<CatalogItem[]>([])
  const [shifts, setShifts] = useState<CatalogItem[]>([])

  useEffect(() => {
    void api.get('/api/v1/catalog/models').then(r => setModels(r.data.items))
    void api.get('/api/v1/catalog/chatters').then(r => setChatters(r.data.items))
    void api.get('/api/v1/catalog/shifts').then(r => setShifts(r.data.items))
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const params: Record<string, string | number> = { month, year }
      if (sourceFilter) params.source = sourceFilter
      const res = await api.get('/api/v1/entries/transactions', { params })
      setRows(res.data.items)
    } catch {
      setErr('Ошибка загрузки транзакций')
    } finally {
      setLoading(false)
    }
  }, [month, year, sourceFilter])

  useEffect(() => { void load() }, [load])

  // ── Edit ──────────────────────────────────────────────────────────────────

  const startEdit = (row: TxRow) => {
    setEditId(row.id)
    setEditState(rowToEdit(row))
  }

  const cancelEdit = () => { setEditId(null); setEditState(null) }

  const saveEdit = async (id: number) => {
    if (!editState) return
    setSaving(true)
    setErr(null)
    try {
      await api.put(`/api/v1/entries/transactions/${id}`, {
        date: editState.date,
        model_id: Number(editState.model_id),
        chatter_id: Number(editState.chatter_id),
        shift_catalog_id: editState.shift_catalog_id ? Number(editState.shift_catalog_id) : null,
        amount: Number(editState.amount),
      })
      cancelEdit()
      await load()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } } }
      setErr(ax.response?.data?.detail ?? 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const setEdit = (k: keyof EditState, v: string) =>
    setEditState(s => s ? { ...s, [k]: v } : s)

  // ── Delete ────────────────────────────────────────────────────────────────

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить транзакцию?')) return
    setDeletingId(id)
    try {
      await api.delete(`/api/v1/entries/transactions/${id}`)
      await load()
    } catch {
      setErr('Ошибка удаления')
    } finally {
      setDeletingId(null)
    }
  }

  // ── Totals ────────────────────────────────────────────────────────────────

  const total = rows.reduce((sum, r) => sum + Number(r.amount ?? 0), 0)

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-screen bg-slate-950">
      <Header title="Учёт" />

      <div className="flex-1 px-6 py-6 space-y-5 max-w-7xl mx-auto w-full">

        {/* Форма добавления */}
        <AddTransactionForm onAdded={load} />

        {/* Фильтр по источнику */}
        <div className="flex items-center gap-2 flex-wrap">
          {SOURCE_TABS.map(tab => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setSourceFilter(tab.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
                sourceFilter === tab.value
                  ? 'bg-indigo-600 border-indigo-500 text-white'
                  : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500'
              }`}
            >
              {tab.label}
            </button>
          ))}

          <button
            type="button"
            onClick={load}
            className="ml-auto text-slate-500 hover:text-slate-300 transition-colors"
            title="Обновить"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {/* Ошибка */}
        {err && (
          <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {err}
          </p>
        )}

        {/* Таблица */}
        <div className="rounded-xl border border-slate-700/50 overflow-hidden">
          {/* Шапка */}
          <div className="flex items-center justify-between px-4 py-3 bg-slate-800/60 border-b border-slate-700/50">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              Транзакции
            </p>
            <div className="flex items-center gap-3">
              {!loading && (
                <span className="text-xs text-slate-500">
                  {rows.length} строк · <span className="text-slate-300 font-medium">${total.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
                </span>
              )}
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16 bg-slate-900/30">
              <Loader2 className="h-6 w-6 text-slate-500 animate-spin" />
            </div>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 bg-slate-900/30 text-center">
              <p className="text-slate-500 text-sm">Нет транзакций за этот период</p>
              {sourceFilter && (
                <button
                  type="button"
                  onClick={() => setSourceFilter('')}
                  className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 underline"
                >
                  Сбросить фильтр
                </button>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50 bg-slate-800/30 text-left">
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400">Дата</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400">Модель</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400">Чаттер</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400">Смена</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400 text-right">Сумма</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400">Источник</th>
                    <th className="px-4 py-2.5 text-xs font-medium text-slate-400 w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr
                      key={row.id}
                      className={`group border-b border-slate-700/30 transition-colors ${
                        i % 2 === 0 ? 'bg-slate-900/20' : 'bg-transparent'
                      } hover:bg-slate-800/30`}
                    >
                      {editId === row.id && editState ? (
                        /* ── Режим редактирования ── */
                        <>
                          <td className="px-3 py-2">
                            <input
                              type="date"
                              value={editState.date}
                              onChange={e => setEdit('date', e.target.value)}
                              className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none w-32"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={editState.model_id}
                              onChange={e => setEdit('model_id', e.target.value)}
                              className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none"
                            >
                              <option value="">— выбрать —</option>
                              {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={editState.chatter_id}
                              onChange={e => setEdit('chatter_id', e.target.value)}
                              className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none"
                            >
                              <option value="">— выбрать —</option>
                              {chatters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            <select
                              value={editState.shift_catalog_id}
                              onChange={e => setEdit('shift_catalog_id', e.target.value)}
                              className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none"
                            >
                              <option value="">—</option>
                              {shifts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <input
                              type="number"
                              min={0}
                              step="0.01"
                              value={editState.amount}
                              onChange={e => setEdit('amount', e.target.value)}
                              onKeyDown={e => e.key === 'Enter' && void saveEdit(row.id)}
                              className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none w-24 text-right"
                            />
                          </td>
                          <td className="px-3 py-2">
                            <SourceBadge source="manual" />
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1.5 justify-end">
                              <button
                                type="button"
                                onClick={() => void saveEdit(row.id)}
                                disabled={saving}
                                className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
                              >
                                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                              </button>
                              <button
                                type="button"
                                onClick={cancelEdit}
                                className="text-slate-500 hover:text-slate-300"
                              >
                                <X className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </>
                      ) : (
                        /* ── Обычный режим ── */
                        <>
                          <td className="px-4 py-2.5 text-slate-300 tabular-nums">
                            {row.date ? new Date(row.date + 'T12:00:00').toLocaleDateString('ru', { day: '2-digit', month: 'short' }) : '—'}
                          </td>
                          <td className="px-4 py-2.5 text-slate-200">{row.model_name ?? '—'}</td>
                          <td className="px-4 py-2.5 text-slate-300">{row.chatter_name ?? '—'}</td>
                          <td className="px-4 py-2.5 text-slate-400 text-xs">{row.shift_name ?? '—'}</td>
                          <td className="px-4 py-2.5 text-right font-medium text-slate-100 tabular-nums">
                            ${Number(row.amount ?? 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className="px-4 py-2.5">
                            <SourceBadge source={row.source} />
                          </td>
                          <td className="px-4 py-2.5">
                            <div className="flex items-center gap-1.5 justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                type="button"
                                onClick={() => startEdit(row)}
                                className="text-slate-500 hover:text-slate-300"
                                title="Редактировать"
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => void handleDelete(row.id)}
                                disabled={deletingId === row.id}
                                className="text-slate-500 hover:text-red-400 disabled:opacity-50"
                                title="Удалить"
                              >
                                {deletingId === row.id
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : <Trash2 className="h-3.5 w-3.5" />
                                }
                              </button>
                            </div>
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </div>
  )
}
