'use client'

import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'
import { Header } from '@/components/layout/Header'
import { AddTransactionForm } from '@/components/entries/AddTransactionForm'
import { AddExpenseForm } from '@/components/entries/AddExpenseForm'
import { SourceBadge } from '@/components/entries/SourceBadge'
import { useMonthStore } from '@/lib/hooks/useMonth'
import { Pencil, Trash2, Check, X, Loader2, RefreshCw } from 'lucide-react'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TxRow {
  id: number; date: string; amount: string | number; source: string
  model_id: number | null; chatter_id: number | null; shift_catalog_id: number | null
  model_name: string | null; chatter_name: string | null; shift_name: string | null
}

interface ExpRow {
  id: number; date: string; amount: string | number; source: string
  category_id: number | null; model_id: number | null
  category_name: string | null; model_name: string | null
  description: string | null; vendor: string | null
}

interface CatalogItem { id: number; name: string }

// ─── Edit state ───────────────────────────────────────────────────────────────

interface TxEdit { date: string; model_id: string; chatter_id: string; shift_catalog_id: string; amount: string }
interface ExpEdit { date: string; category_id: string; model_id: string; amount: string; description: string }

function txToEdit(row: TxRow): TxEdit {
  return {
    date: row.date, amount: String(row.amount),
    model_id: row.model_id != null ? String(row.model_id) : '',
    chatter_id: row.chatter_id != null ? String(row.chatter_id) : '',
    shift_catalog_id: row.shift_catalog_id != null ? String(row.shift_catalog_id) : '',
  }
}

function expToEdit(row: ExpRow): ExpEdit {
  return {
    date: row.date, amount: String(row.amount),
    category_id: row.category_id != null ? String(row.category_id) : '',
    model_id: row.model_id != null ? String(row.model_id) : '',
    description: row.description ?? '',
  }
}

// ─── Source filter tabs ───────────────────────────────────────────────────────

const SOURCE_TABS = [
  { label: 'Все', value: '' },
  { label: 'Вручную', value: 'manual' },
  { label: 'Google Sheets', value: 'google_sheets' },
  { label: 'Импорт', value: 'import' },
]

// ─── Shared FilterBar ─────────────────────────────────────────────────────────

function FilterBar({ value, onChange, onRefresh }: { value: string; onChange: (v: string) => void; onRefresh: () => void }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {SOURCE_TABS.map(tab => (
        <button key={tab.value} type="button" onClick={() => onChange(tab.value)}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
            value === tab.value
              ? 'bg-indigo-600 border-indigo-500 text-white'
              : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500'
          }`}>
          {tab.label}
        </button>
      ))}
      <button type="button" onClick={onRefresh} className="ml-auto text-slate-500 hover:text-slate-300" title="Обновить">
        <RefreshCw className="h-4 w-4" />
      </button>
    </div>
  )
}

// ─── Transactions tab ─────────────────────────────────────────────────────────

function TransactionsTab() {
  const { month, year } = useMonthStore()
  const [rows, setRows] = useState<TxRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [editId, setEditId] = useState<number | null>(null)
  const [editState, setEditState] = useState<TxEdit | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [models, setModels] = useState<CatalogItem[]>([])
  const [chatters, setChatters] = useState<CatalogItem[]>([])
  const [shifts, setShifts] = useState<CatalogItem[]>([])

  useEffect(() => {
    void api.get('/api/v1/catalog/models').then(r => setModels(r.data.items))
    void api.get('/api/v1/catalog/chatters').then(r => setChatters(r.data.items))
    void api.get('/api/v1/catalog/shifts').then(r => setShifts(r.data.items))
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const params: Record<string, string | number> = { month, year }
      if (filter) params.source = filter
      const res = await api.get('/api/v1/entries/transactions', { params })
      setRows(res.data.items)
    } catch { setErr('Ошибка загрузки') } finally { setLoading(false) }
  }, [month, year, filter])

  useEffect(() => { void load() }, [load])

  const cancelEdit = () => { setEditId(null); setEditState(null) }
  const setEdit = (k: keyof TxEdit, v: string) => setEditState(s => s ? { ...s, [k]: v } : s)

  const saveEdit = async (id: number) => {
    if (!editState) return
    setSaving(true); setErr(null)
    try {
      await api.put(`/api/v1/entries/transactions/${id}`, {
        date: editState.date,
        model_id: Number(editState.model_id),
        chatter_id: Number(editState.chatter_id),
        shift_catalog_id: editState.shift_catalog_id ? Number(editState.shift_catalog_id) : null,
        amount: Number(editState.amount),
      })
      cancelEdit(); await load()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } } }
      setErr(ax.response?.data?.detail ?? 'Ошибка сохранения')
    } finally { setSaving(false) }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить транзакцию?')) return
    setDeletingId(id)
    try { await api.delete(`/api/v1/entries/transactions/${id}`); await load() }
    catch { setErr('Ошибка удаления') } finally { setDeletingId(null) }
  }

  const total = rows.reduce((s, r) => s + Number(r.amount ?? 0), 0)

  return (
    <div className="space-y-4">
      <AddTransactionForm onAdded={load} />
      <FilterBar value={filter} onChange={setFilter} onRefresh={load} />
      {err && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{err}</p>}

      <div className="rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 bg-slate-800/60 border-b border-slate-700/50">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Транзакции</p>
          {!loading && <span className="text-xs text-slate-500">{rows.length} строк · <span className="text-slate-300 font-medium">${total.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></span>}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 bg-slate-900/30"><Loader2 className="h-6 w-6 text-slate-500 animate-spin" /></div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 bg-slate-900/30">
            <p className="text-slate-500 text-sm">Нет транзакций за этот период</p>
            {filter && <button type="button" onClick={() => setFilter('')} className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 underline">Сбросить фильтр</button>}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-800/30 text-left">
                  {['Дата', 'Модель', 'Чаттер', 'Смена', 'Сумма', 'Источник', ''].map(h => (
                    <th key={h} className={`px-4 py-2.5 text-xs font-medium text-slate-400 ${h === 'Сумма' ? 'text-right' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={row.id} className={`group border-b border-slate-700/30 transition-colors ${i % 2 === 0 ? 'bg-slate-900/20' : ''} hover:bg-slate-800/30`}>
                    {editId === row.id && editState ? (
                      <>
                        <td className="px-3 py-2"><input type="date" value={editState.date} onChange={e => setEdit('date', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none w-32" /></td>
                        <td className="px-3 py-2"><select value={editState.model_id} onChange={e => setEdit('model_id', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none"><option value="">—</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></td>
                        <td className="px-3 py-2"><select value={editState.chatter_id} onChange={e => setEdit('chatter_id', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none"><option value="">—</option>{chatters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></td>
                        <td className="px-3 py-2"><select value={editState.shift_catalog_id} onChange={e => setEdit('shift_catalog_id', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none"><option value="">—</option>{shifts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></td>
                        <td className="px-3 py-2 text-right"><input type="number" min={0} step="0.01" value={editState.amount} onChange={e => setEdit('amount', e.target.value)} onKeyDown={e => e.key === 'Enter' && void saveEdit(row.id)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none w-24 text-right" /></td>
                        <td className="px-3 py-2"><SourceBadge source="manual" /></td>
                        <td className="px-3 py-2"><div className="flex items-center gap-1.5 justify-end"><button type="button" onClick={() => void saveEdit(row.id)} disabled={saving} className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}</button><button type="button" onClick={cancelEdit} className="text-slate-500 hover:text-slate-300"><X className="h-4 w-4" /></button></div></td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-2.5 text-slate-300 tabular-nums">{row.date ? new Date(row.date + 'T12:00:00').toLocaleDateString('ru', { day: '2-digit', month: 'short' }) : '—'}</td>
                        <td className="px-4 py-2.5 text-slate-200">{row.model_name ?? '—'}</td>
                        <td className="px-4 py-2.5 text-slate-300">{row.chatter_name ?? '—'}</td>
                        <td className="px-4 py-2.5 text-slate-400 text-xs">{row.shift_name ?? '—'}</td>
                        <td className="px-4 py-2.5 text-right font-medium text-slate-100 tabular-nums">${Number(row.amount ?? 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="px-4 py-2.5"><SourceBadge source={row.source} /></td>
                        <td className="px-4 py-2.5"><div className="flex items-center gap-1.5 justify-end opacity-0 group-hover:opacity-100 transition-opacity"><button type="button" onClick={() => { setEditId(row.id); setEditState(txToEdit(row)) }} className="text-slate-500 hover:text-slate-300" title="Редактировать"><Pencil className="h-3.5 w-3.5" /></button><button type="button" onClick={() => void handleDelete(row.id)} disabled={deletingId === row.id} className="text-slate-500 hover:text-red-400 disabled:opacity-50" title="Удалить">{deletingId === row.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}</button></div></td>
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
  )
}

// ─── Expenses tab ─────────────────────────────────────────────────────────────

function ExpensesTab() {
  const { month, year } = useMonthStore()
  const [rows, setRows] = useState<ExpRow[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [editId, setEditId] = useState<number | null>(null)
  const [editState, setEditState] = useState<ExpEdit | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [categories, setCategories] = useState<CatalogItem[]>([])
  const [models, setModels] = useState<CatalogItem[]>([])

  useEffect(() => {
    void api.get('/api/v1/catalog/expense-categories').then(r => setCategories(r.data.items))
    void api.get('/api/v1/catalog/models').then(r => setModels(r.data.items))
  }, [])

  const load = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const params: Record<string, string | number> = { month, year }
      if (filter) params.source = filter
      const res = await api.get('/api/v1/entries/expenses', { params })
      setRows(res.data.items)
    } catch { setErr('Ошибка загрузки') } finally { setLoading(false) }
  }, [month, year, filter])

  useEffect(() => { void load() }, [load])

  const cancelEdit = () => { setEditId(null); setEditState(null) }
  const setEdit = (k: keyof ExpEdit, v: string) => setEditState(s => s ? { ...s, [k]: v } : s)

  const saveEdit = async (id: number) => {
    if (!editState) return
    setSaving(true); setErr(null)
    try {
      await api.put(`/api/v1/entries/expenses/${id}`, {
        date: editState.date,
        category_id: Number(editState.category_id),
        model_id: editState.model_id ? Number(editState.model_id) : null,
        amount: Number(editState.amount),
        description: editState.description || null,
      })
      cancelEdit(); await load()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } } }
      setErr(ax.response?.data?.detail ?? 'Ошибка сохранения')
    } finally { setSaving(false) }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить расход?')) return
    setDeletingId(id)
    try { await api.delete(`/api/v1/entries/expenses/${id}`); await load() }
    catch { setErr('Ошибка удаления') } finally { setDeletingId(null) }
  }

  const total = rows.reduce((s, r) => s + Number(r.amount ?? 0), 0)

  return (
    <div className="space-y-4">
      <AddExpenseForm onAdded={load} />
      <FilterBar value={filter} onChange={setFilter} onRefresh={load} />
      {err && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{err}</p>}

      <div className="rounded-xl border border-slate-700/50 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 bg-slate-800/60 border-b border-slate-700/50">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Расходы</p>
          {!loading && <span className="text-xs text-slate-500">{rows.length} строк · <span className="text-rose-300 font-medium">${total.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span></span>}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16 bg-slate-900/30"><Loader2 className="h-6 w-6 text-slate-500 animate-spin" /></div>
        ) : rows.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 bg-slate-900/30">
            <p className="text-slate-500 text-sm">Нет расходов за этот период</p>
            {filter && <button type="button" onClick={() => setFilter('')} className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 underline">Сбросить фильтр</button>}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-800/30 text-left">
                  {['Дата', 'Категория', 'Модель', 'Описание', 'Сумма', 'Источник', ''].map(h => (
                    <th key={h} className={`px-4 py-2.5 text-xs font-medium text-slate-400 ${h === 'Сумма' ? 'text-right' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={row.id} className={`group border-b border-slate-700/30 transition-colors ${i % 2 === 0 ? 'bg-slate-900/20' : ''} hover:bg-slate-800/30`}>
                    {editId === row.id && editState ? (
                      <>
                        <td className="px-3 py-2"><input type="date" value={editState.date} onChange={e => setEdit('date', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:border-indigo-500 focus:outline-none w-32" /></td>
                        <td className="px-3 py-2"><select value={editState.category_id} onChange={e => setEdit('category_id', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none"><option value="">—</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></td>
                        <td className="px-3 py-2"><select value={editState.model_id} onChange={e => setEdit('model_id', e.target.value)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none"><option value="">Общий</option>{models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></td>
                        <td className="px-3 py-2"><input type="text" value={editState.description} onChange={e => setEdit('description', e.target.value)} placeholder="Описание" className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none w-32" /></td>
                        <td className="px-3 py-2 text-right"><input type="number" min={0} step="0.01" value={editState.amount} onChange={e => setEdit('amount', e.target.value)} onKeyDown={e => e.key === 'Enter' && void saveEdit(row.id)} className="bg-slate-700 text-slate-200 rounded px-2 py-1 text-xs border border-slate-600 focus:outline-none w-24 text-right" /></td>
                        <td className="px-3 py-2"><SourceBadge source="manual" /></td>
                        <td className="px-3 py-2"><div className="flex items-center gap-1.5 justify-end"><button type="button" onClick={() => void saveEdit(row.id)} disabled={saving} className="text-emerald-400 hover:text-emerald-300 disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}</button><button type="button" onClick={cancelEdit} className="text-slate-500 hover:text-slate-300"><X className="h-4 w-4" /></button></div></td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-2.5 text-slate-300 tabular-nums">{row.date ? new Date(row.date + 'T12:00:00').toLocaleDateString('ru', { day: '2-digit', month: 'short' }) : '—'}</td>
                        <td className="px-4 py-2.5 text-slate-200">{row.category_name ?? '—'}</td>
                        <td className="px-4 py-2.5 text-slate-300">{row.model_name ?? <span className="text-slate-500 text-xs italic">Общий</span>}</td>
                        <td className="px-4 py-2.5 text-slate-400 text-xs max-w-[160px] truncate">{row.description ?? row.vendor ?? '—'}</td>
                        <td className="px-4 py-2.5 text-right font-medium text-rose-300 tabular-nums">${Number(row.amount ?? 0).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="px-4 py-2.5"><SourceBadge source={row.source} /></td>
                        <td className="px-4 py-2.5"><div className="flex items-center gap-1.5 justify-end opacity-0 group-hover:opacity-100 transition-opacity"><button type="button" onClick={() => { setEditId(row.id); setEditState(expToEdit(row)) }} className="text-slate-500 hover:text-slate-300" title="Редактировать"><Pencil className="h-3.5 w-3.5" /></button><button type="button" onClick={() => void handleDelete(row.id)} disabled={deletingId === row.id} className="text-slate-500 hover:text-red-400 disabled:opacity-50" title="Удалить">{deletingId === row.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}</button></div></td>
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
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type Tab = 'transactions' | 'expenses'

export default function EntriesPage() {
  const [tab, setTab] = useState<Tab>('transactions')

  return (
    <div className="flex flex-col min-h-screen bg-slate-950">
      <Header title="Учёт" />

      <div className="flex-1 px-6 py-6 space-y-5 max-w-7xl mx-auto w-full">
        {/* Tab switcher */}
        <div className="flex gap-1 bg-slate-800/50 border border-slate-700/50 rounded-xl p-1 w-fit">
          <button
            type="button"
            onClick={() => setTab('transactions')}
            className={`px-5 py-2 text-sm font-medium rounded-lg transition-colors ${
              tab === 'transactions'
                ? 'bg-indigo-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Транзакции
          </button>
          <button
            type="button"
            onClick={() => setTab('expenses')}
            className={`px-5 py-2 text-sm font-medium rounded-lg transition-colors ${
              tab === 'expenses'
                ? 'bg-rose-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Расходы
          </button>
        </div>

        {tab === 'transactions' ? <TransactionsTab /> : <ExpensesTab />}
      </div>
    </div>
  )
}
