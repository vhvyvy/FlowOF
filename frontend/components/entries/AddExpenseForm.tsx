'use client'

import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { Plus, Loader2 } from 'lucide-react'

interface CatalogItem { id: number; name: string }

interface AddExpenseFormProps {
  onAdded: () => void
}

export function AddExpenseForm({ onAdded }: AddExpenseFormProps) {
  const [categories, setCategories] = useState<CatalogItem[]>([])
  const [models, setModels] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({
    date: today,
    category_id: '',
    model_id: '',
    amount: '',
    description: '',
  })

  useEffect(() => {
    void api.get('/api/v1/catalog/expense-categories').then(r => setCategories(r.data.items))
    void api.get('/api/v1/catalog/models').then(r => setModels(r.data.items))
  }, [])

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    if (!form.category_id || !form.amount || !form.date) return
    setLoading(true)
    setErr(null)
    try {
      await api.post('/api/v1/entries/expenses', {
        date: form.date,
        category_id: Number(form.category_id),
        model_id: form.model_id ? Number(form.model_id) : null,
        amount: Number(form.amount),
        description: form.description || null,
      })
      setForm(f => ({ ...f, amount: '', description: '' }))
      onAdded()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } } }
      setErr(ax.response?.data?.detail ?? 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const noData = categories.length === 0

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-4 space-y-3">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Добавить расход</p>

      {noData && (
        <div className="text-xs text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Сначала добавьте категории расходов в{' '}
          <a href="/dashboard/catalog" className="underline hover:text-amber-300">справочниках</a>
        </div>
      )}

      {err && <p className="text-xs text-red-400">{err}</p>}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <input
          type="date"
          value={form.date}
          onChange={e => set('date', e.target.value)}
          className="col-span-1 bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        />

        <select
          value={form.category_id}
          onChange={e => set('category_id', e.target.value)}
          className="bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Категория</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        <select
          value={form.model_id}
          onChange={e => set('model_id', e.target.value)}
          className="bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Общий расход</option>
          {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>

        <input
          type="text"
          placeholder="Описание"
          value={form.description}
          onChange={e => set('description', e.target.value)}
          className="bg-slate-700/50 text-slate-200 placeholder-slate-500 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        />

        <input
          type="number"
          placeholder="Сумма $"
          min={0}
          step="0.01"
          value={form.amount}
          onChange={e => set('amount', e.target.value)}
          onKeyDown={e => e.key === 'Enter' && void submit()}
          className="bg-slate-700/50 text-slate-200 placeholder-slate-500 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        />

        <button
          type="button"
          onClick={() => void submit()}
          disabled={loading || !form.category_id || !form.amount}
          className="flex items-center justify-center gap-1.5 px-4 py-2 text-sm bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white rounded-lg transition-colors"
        >
          {loading
            ? <Loader2 className="h-4 w-4 animate-spin" />
            : <><Plus className="h-4 w-4" />Добавить</>
          }
        </button>
      </div>
    </div>
  )
}
