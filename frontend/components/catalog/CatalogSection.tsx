'use client'

import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { Plus, Pencil, X, Check, GripVertical } from 'lucide-react'

interface CatalogItem {
  id: number
  name: string
  sort_order?: number
}

interface CatalogSectionProps {
  title: string
  endpoint: string
  /** Placeholder для поля ввода */
  placeholder?: string
  /** Показывать sort_order у смен */
  showOrder?: boolean
}

export function CatalogSection({ title, endpoint, placeholder, showOrder }: CatalogSectionProps) {
  const [items, setItems] = useState<CatalogItem[]>([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const load = async () => {
    try {
      const res = await api.get(`/api/v1/catalog/${endpoint}`)
      setItems(res.data.items)
    } catch {
      setErr('Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [endpoint])

  const add = async () => {
    const name = newName.trim()
    if (!name) return
    setAdding(true)
    setErr(null)
    try {
      await api.post(`/api/v1/catalog/${endpoint}`, null, { params: { name } })
      setNewName('')
      await load()
    } catch {
      setErr('Не удалось добавить')
    } finally {
      setAdding(false)
    }
  }

  const startEdit = (item: CatalogItem) => {
    setEditId(item.id)
    setEditName(item.name)
  }

  const saveEdit = async (id: number) => {
    const name = editName.trim()
    if (!name) { setEditId(null); return }
    try {
      await api.patch(`/api/v1/catalog/${endpoint}/${id}`, null, { params: { name } })
      setEditId(null)
      await load()
    } catch {
      setErr('Не удалось сохранить')
    }
  }

  const remove = async (id: number) => {
    try {
      await api.delete(`/api/v1/catalog/${endpoint}/${id}`)
      await load()
    } catch {
      setErr('Не удалось удалить')
    }
  }

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-5 space-y-4">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">{title}</p>

      {err && (
        <p className="text-xs text-red-400">{err}</p>
      )}

      {/* Список */}
      {loading ? (
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-8 w-24 rounded-lg bg-slate-700/40 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {items.map(item => (
            <div
              key={item.id}
              className="flex items-center gap-1.5 bg-slate-700/50 border border-slate-600/50 rounded-lg px-3 py-1.5 text-sm text-slate-200 group"
            >
              {showOrder && (
                <GripVertical className="h-3.5 w-3.5 text-slate-500 shrink-0" />
              )}

              {editId === item.id ? (
                <>
                  <input
                    autoFocus
                    value={editName}
                    onChange={e => setEditName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') void saveEdit(item.id)
                      if (e.key === 'Escape') setEditId(null)
                    }}
                    className="bg-transparent outline-none border-b border-indigo-400 text-slate-100 w-28 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => void saveEdit(item.id)}
                    className="text-emerald-400 hover:text-emerald-300"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditId(null)}
                    className="text-slate-500 hover:text-slate-300"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </>
              ) : (
                <>
                  <span>{item.name}</span>
                  <button
                    type="button"
                    onClick={() => startEdit(item)}
                    className="text-slate-500 hover:text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Pencil className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(item.id)}
                    className="text-slate-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
            </div>
          ))}

          {items.length === 0 && !loading && (
            <span className="text-slate-500 text-sm">Пока пусто</span>
          )}
        </div>
      )}

      {/* Форма добавления */}
      <div className="flex gap-2">
        <input
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && void add()}
          placeholder={placeholder ?? `Добавить ${title.toLowerCase()}`}
          className="flex-1 bg-slate-700/50 text-slate-200 placeholder-slate-500 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void add()}
          disabled={adding || !newName.trim()}
          className="flex items-center gap-1.5 px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors"
        >
          <Plus className="h-4 w-4" />
          {adding ? '…' : 'Добавить'}
        </button>
      </div>
    </div>
  )
}
