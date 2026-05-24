'use client'

import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { Plus, Loader2 } from 'lucide-react'

interface CatalogItem { id: number; name: string }

interface AddTransactionFormProps {
  onAdded: () => void
}

export function AddTransactionForm({ onAdded }: AddTransactionFormProps) {
  const [models, setModels] = useState<CatalogItem[]>([])
  const [chatters, setChatters] = useState<CatalogItem[]>([])
  const [shifts, setShifts] = useState<CatalogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({
    date: today,
    model_id: '',
    chatter_id: '',
    shift_catalog_id: '',
    amount: '',
  })

  useEffect(() => {
    void api.get('/api/v1/catalog/models').then(r => setModels(r.data.items))
    void api.get('/api/v1/catalog/chatters').then(r => setChatters(r.data.items))
    void api.get('/api/v1/catalog/shifts').then(r => setShifts(r.data.items))
  }, [])

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    if (!form.model_id || !form.chatter_id || !form.amount || !form.date) return
    setLoading(true)
    setErr(null)
    try {
      await api.post('/api/v1/entries/transactions', {
        date: form.date,
        model_id: Number(form.model_id),
        chatter_id: Number(form.chatter_id),
        shift_catalog_id: form.shift_catalog_id ? Number(form.shift_catalog_id) : null,
        amount: Number(form.amount),
      })
      setForm(f => ({ ...f, amount: '' })) // сумму обнуляем, остальное оставляем
      onAdded()
    } catch (e: unknown) {
      const ax = e as { response?: { data?: { detail?: string } } }
      setErr(ax.response?.data?.detail ?? 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const noData = models.length === 0 || chatters.length === 0

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-4 space-y-3">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Добавить транзакцию</p>

      {noData && (
        <div className="text-xs text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          Сначала добавьте модели и чаттеров в{' '}
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
          value={form.model_id}
          onChange={e => set('model_id', e.target.value)}
          className="bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Модель</option>
          {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>

        <select
          value={form.chatter_id}
          onChange={e => set('chatter_id', e.target.value)}
          className="bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Чаттер</option>
          {chatters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>

        <select
          value={form.shift_catalog_id}
          onChange={e => set('shift_catalog_id', e.target.value)}
          className="bg-slate-700/50 text-slate-200 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">Смена</option>
          {shifts.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>

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
          disabled={loading || !form.model_id || !form.chatter_id || !form.amount}
          className="flex items-center justify-center gap-1.5 px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors"
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
