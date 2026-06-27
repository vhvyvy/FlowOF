'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import api from '@/lib/api'
import { Plus, Pencil, X, Check, UserPlus, Copy, CheckCheck, Settings2 } from 'lucide-react'

interface ChatterItem {
  id: number
  name: string
  has_account: boolean
  user_id: number | null
  user_email: string | null
  last_login_at: string | null
}

interface InviteResult {
  invite_id: number
  token: string
  url: string
  expires_at: string
  chatter_name: string
}

// ── Модалка с инвайт-ссылкой ────────────────────────────────────────────────

function InviteModal({
  result,
  onClose,
}: {
  result: InviteResult
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(result.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
      const el = document.createElement('textarea')
      el.value = result.url
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div>
            <p className="text-sm font-semibold text-slate-100">Инвайт создан</p>
            <p className="text-xs text-slate-400 mt-0.5">Чаттер: {result.chatter_name}</p>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <p className="text-xs text-slate-400 leading-relaxed">
            Отправьте чаттеру эту ссылку. Она действительна <span className="text-slate-300 font-medium">7 дней</span> и
            одноразова — после регистрации деактивируется.
          </p>

          {/* Ссылка */}
          <div className="bg-slate-700/40 border border-slate-600/50 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-400 mb-1 font-medium uppercase tracking-wide">Ссылка</p>
            <p className="text-sm text-violet-300 break-all font-mono leading-relaxed">
              {result.url}
            </p>
          </div>

          {/* Кнопка копирования */}
          <button
            onClick={copyLink}
            className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
              copied
                ? 'bg-emerald-500/20 border border-emerald-500/30 text-emerald-400'
                : 'bg-violet-600 hover:bg-violet-500 text-white'
            }`}
          >
            {copied ? (
              <>
                <CheckCheck className="h-4 w-4" />
                Скопировано!
              </>
            ) : (
              <>
                <Copy className="h-4 w-4" />
                Скопировать ссылку
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Основной компонент ───────────────────────────────────────────────────────

export function ChatterCatalogSection() {
  const [items, setItems] = useState<ChatterItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)

  const [editId, setEditId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')

  const [inviting, setInviting] = useState<number | null>(null)
  const [inviteResult, setInviteResult] = useState<InviteResult | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/catalog/chatters')
      setItems(res.data.items)
    } catch {
      setErr('Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const add = async () => {
    const name = newName.trim()
    if (!name) return
    setAdding(true)
    setErr(null)
    try {
      await api.post('/api/v1/catalog/chatters', null, { params: { name } })
      setNewName('')
      await load()
    } catch {
      setErr('Не удалось добавить')
    } finally {
      setAdding(false)
    }
  }

  const saveEdit = async (id: number) => {
    const name = editName.trim()
    if (!name) { setEditId(null); return }
    try {
      await api.patch(`/api/v1/catalog/chatters/${id}`, null, { params: { name } })
      setEditId(null)
      await load()
    } catch {
      setErr('Не удалось сохранить')
    }
  }

  const remove = async (id: number) => {
    try {
      await api.delete(`/api/v1/catalog/chatters/${id}`)
      await load()
    } catch {
      setErr('Не удалось удалить')
    }
  }

  const createInvite = async (chatterId: number) => {
    setInviting(chatterId)
    setErr(null)
    try {
      const res = await api.post<InviteResult>(`/api/v1/invites/chatter/${chatterId}`)
      setInviteResult(res.data)
    } catch (e: any) {
      setErr(e?.response?.data?.detail ?? 'Не удалось создать инвайт')
    } finally {
      setInviting(null)
    }
  }

  function formatDate(iso: string | null): string {
    if (!iso) return '—'
    try {
      return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch {
      return '—'
    }
  }

  return (
    <>
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl px-5 py-5 space-y-4">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">Чаттеры</p>

        {err && <p className="text-xs text-red-400">{err}</p>}

        {/* Список */}
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-11 rounded-lg bg-slate-700/40 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="space-y-1.5">
            {items.map(item => (
              <div
                key={item.id}
                className="flex items-center gap-3 bg-slate-700/30 border border-slate-600/40 rounded-lg px-3 py-2.5 group"
              >
                {/* Имя / редактирование */}
                <div className="flex-1 min-w-0">
                  {editId === item.id ? (
                    <div className="flex items-center gap-1.5">
                      <input
                        autoFocus
                        value={editName}
                        onChange={e => setEditName(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') void saveEdit(item.id)
                          if (e.key === 'Escape') setEditId(null)
                        }}
                        className="bg-transparent outline-none border-b border-indigo-400 text-slate-100 flex-1 text-sm"
                      />
                      <button onClick={() => void saveEdit(item.id)} className="text-emerald-400 hover:text-emerald-300">
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button onClick={() => setEditId(null)} className="text-slate-500 hover:text-slate-300">
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : (
                    <span className="text-sm text-slate-200">{item.name}</span>
                  )}
                </div>

                {/* Статус аккаунта */}
                <div className="flex items-center gap-2 shrink-0">
                  {item.has_account ? (
                    <div className="flex items-center gap-1.5">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                        Активен
                      </span>
                      <span className="text-xs text-slate-500 hidden sm:inline">
                        {formatDate(item.last_login_at)}
                      </span>
                      <Link
                        href={`/dashboard/chatter-accounts?q=${encodeURIComponent(item.name)}`}
                        className="flex items-center gap-1 px-2 py-0.5 text-xs text-slate-400 hover:text-indigo-300 hover:bg-slate-700/60 border border-slate-600/30 hover:border-indigo-500/30 rounded-lg transition-colors"
                        title="Управление аккаунтом"
                      >
                        <Settings2 className="h-3 w-3" />
                        Управление
                      </Link>
                    </div>
                  ) : (
                    <button
                      onClick={() => void createInvite(item.id)}
                      disabled={inviting === item.id}
                      title="Пригласить в личный кабинет"
                      className="flex items-center gap-1 px-2.5 py-1 text-xs bg-violet-600/20 hover:bg-violet-600/40 border border-violet-500/30 text-violet-300 rounded-lg transition-colors disabled:opacity-50"
                    >
                      <UserPlus className="h-3.5 w-3.5" />
                      {inviting === item.id ? '…' : 'Пригласить'}
                    </button>
                  )}
                </div>

                {/* Редактировать / удалить */}
                {editId !== item.id && (
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => { setEditId(item.id); setEditName(item.name) }}
                      className="text-slate-500 hover:text-slate-300"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => void remove(item.id)}
                      className="text-slate-500 hover:text-red-400"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>
            ))}

            {items.length === 0 && !loading && (
              <span className="text-slate-500 text-sm">Пока пусто</span>
            )}
          </div>
        )}

        {/* Добавить чаттера */}
        <div className="flex gap-2">
          <input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && void add()}
            placeholder="Имя чаттера"
            className="flex-1 bg-slate-700/50 text-slate-200 placeholder-slate-500 rounded-lg px-3 py-2 text-sm border border-slate-600/50 focus:border-indigo-500 focus:outline-none"
          />
          <button
            onClick={() => void add()}
            disabled={adding || !newName.trim()}
            className="flex items-center gap-1.5 px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors"
          >
            <Plus className="h-4 w-4" />
            {adding ? '…' : 'Добавить'}
          </button>
        </div>
      </div>

      {/* Модалка с инвайт-ссылкой */}
      {inviteResult && (
        <InviteModal
          result={inviteResult}
          onClose={() => setInviteResult(null)}
        />
      )}
    </>
  )
}
