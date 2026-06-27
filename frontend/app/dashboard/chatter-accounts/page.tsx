'use client'

import { useState, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search, MoreHorizontal, KeyRound, UserCheck, UserX, Trash2,
  X, Copy, Check, RefreshCcw, Users,
} from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatterAccount {
  id: number
  email: string
  full_name: string | null
  chatter_id: number | null
  chatter_name: string | null
  active: boolean
  created_at: string | null
  avatar_base64: string | null
}

type StatusFilter = 'all' | 'active' | 'inactive'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' })
  } catch { return '—' }
}

function Avatar({ account }: { account: ChatterAccount }) {
  const label = (account.chatter_name || account.full_name || account.email || '?').slice(0, 1).toUpperCase()
  if (account.avatar_base64) {
    return <img src={account.avatar_base64} alt="" className="w-8 h-8 rounded-full object-cover shrink-0" />
  }
  return (
    <div className="w-8 h-8 rounded-full bg-violet-500/20 flex items-center justify-center shrink-0 text-xs font-bold text-violet-400">
      {label}
    </div>
  )
}

// ─── New-password modal ───────────────────────────────────────────────────────

function NewPasswordModal({ name, password, onClose }: { name: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try { await navigator.clipboard.writeText(password) } catch { /* ignore */ }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="w-full max-w-sm bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <p className="text-sm font-semibold text-slate-100">Новый пароль</p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-slate-400">Пароль для <span className="text-slate-200 font-medium">{name}</span> сброшен. Передайте его чаттеру.</p>
          <div className="bg-slate-700/50 border border-slate-600/40 rounded-xl px-4 py-3 flex items-center gap-3">
            <span className="flex-1 font-mono text-base text-slate-100 tracking-wider">{password}</span>
            <button onClick={copy} className="text-slate-400 hover:text-violet-300 transition-colors">
              {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-[11px] text-amber-400/80">Пароль больше не будет показан. Скопируйте и передайте чаттеру.</p>
        </div>
        <div className="px-5 pb-4">
          <button onClick={onClose} className="w-full py-2.5 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/40 text-slate-300 text-sm rounded-xl transition-colors">
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Confirm modal ────────────────────────────────────────────────────────────

function ConfirmModal({
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onClose,
  loading,
}: {
  title: string
  message: string
  confirmLabel: string
  danger?: boolean
  onConfirm: () => void
  onClose: () => void
  loading?: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="w-full max-w-sm bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <p className="text-sm font-semibold text-slate-100">{title}</p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-slate-300 leading-relaxed">{message}</p>
        </div>
        <div className="px-5 pb-4 flex gap-2">
          <button
            onClick={onConfirm}
            disabled={loading}
            className={cn(
              'flex-1 py-2.5 text-sm font-semibold rounded-xl transition-colors disabled:opacity-50',
              danger
                ? 'bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400'
                : 'bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-300'
            )}
          >
            {loading ? 'Загрузка…' : confirmLabel}
          </button>
          <button onClick={onClose} className="px-5 py-2.5 bg-slate-700/40 hover:bg-slate-700 border border-slate-600/30 text-slate-400 text-sm rounded-xl transition-colors">
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Row actions menu ─────────────────────────────────────────────────────────

function ActionsMenu({
  account,
  onResetPassword,
  onToggleActive,
  onDelete,
}: {
  account: ChatterAccount
  onResetPassword: () => void
  onToggleActive: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="p-1.5 rounded-lg text-slate-500 hover:text-slate-200 hover:bg-slate-700/60 transition-colors"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <>
          {/* backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-8 z-20 w-48 bg-slate-800 border border-slate-700/60 rounded-xl shadow-2xl py-1 overflow-hidden">
            <button
              onClick={() => { setOpen(false); onResetPassword() }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/60 transition-colors"
            >
              <KeyRound className="h-3.5 w-3.5 text-amber-400" />
              Сбросить пароль
            </button>
            <button
              onClick={() => { setOpen(false); onToggleActive() }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-slate-300 hover:bg-slate-700/60 transition-colors"
            >
              {account.active
                ? <><UserX className="h-3.5 w-3.5 text-orange-400" />Отключить аккаунт</>
                : <><UserCheck className="h-3.5 w-3.5 text-emerald-400" />Активировать</>}
            </button>
            <div className="border-t border-slate-700/40 my-1" />
            <button
              onClick={() => { setOpen(false); onDelete() }}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-400 hover:bg-slate-700/60 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Удалить аккаунт
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ChatterAccountsPage() {
  const qc = useQueryClient()
  const searchParams = useSearchParams()
  const [search,      setSearch]      = useState(searchParams.get('q') ?? '')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [toast,       setToast]       = useState<string | null>(null)

  // Modal states
  const [confirmReset,    setConfirmReset]    = useState<ChatterAccount | null>(null)
  const [confirmToggle,   setConfirmToggle]   = useState<ChatterAccount | null>(null)
  const [confirmDelete,   setConfirmDelete]   = useState<ChatterAccount | null>(null)
  const [newPassword,     setNewPassword]     = useState<{ name: string; password: string } | null>(null)

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const { data, isLoading, refetch } = useQuery<{ items: ChatterAccount[] }>({
    queryKey: ['manage-chatters'],
    queryFn: () => api.get('/api/v1/manage/chatters').then(r => r.data),
  })
  const accounts = data?.items ?? []

  // ── Mutations ─────────────────────────────────────────────────────────────

  const resetPasswordMut = useMutation({
    mutationFn: (userId: number) =>
      api.post<{ temp_password: string }>(`/api/v1/manage/chatters/${userId}/reset-password`).then(r => r.data),
    onSuccess: (data, userId) => {
      const account = accounts.find(a => a.id === userId)
      const name = account?.chatter_name || account?.email || 'чаттер'
      setConfirmReset(null)
      setNewPassword({ name, password: data.temp_password })
    },
    onError: () => showToast('Ошибка сброса пароля'),
  })

  const toggleActiveMut = useMutation({
    mutationFn: (a: ChatterAccount) =>
      api.post(`/api/v1/manage/chatters/${a.id}/${a.active ? 'deactivate' : 'activate'}`).then(r => r.data),
    onSuccess: (_, a) => {
      qc.invalidateQueries({ queryKey: ['manage-chatters'] })
      setConfirmToggle(null)
      showToast(a.active ? 'Аккаунт отключён' : 'Аккаунт активирован')
    },
    onError: () => showToast('Ошибка изменения статуса'),
  })

  const deleteMut = useMutation({
    mutationFn: (userId: number) =>
      api.delete(`/api/v1/manage/chatters/${userId}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['manage-chatters'] })
      setConfirmDelete(null)
      showToast('Аккаунт удалён')
    },
    onError: () => showToast('Ошибка удаления'),
  })

  // ── Filtered list ─────────────────────────────────────────────────────────

  const filtered = accounts.filter(a => {
    const q = search.toLowerCase()
    const matchSearch = !q || (
      (a.chatter_name || '').toLowerCase().includes(q) ||
      (a.email || '').toLowerCase().includes(q) ||
      (a.full_name || '').toLowerCase().includes(q)
    )
    const matchStatus =
      statusFilter === 'all' ? true :
      statusFilter === 'active' ? a.active :
      !a.active
    return matchSearch && matchStatus
  })

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900 flex items-center gap-4">
        <div className="flex items-center gap-2.5 shrink-0">
          <Users className="h-5 w-5 text-indigo-400" />
          <h1 className="text-lg font-semibold text-slate-100">Аккаунты чаттеров</h1>
        </div>
        <div className="flex-1 max-w-sm relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск по имени или email…"
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-slate-800 border border-slate-700/50 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50"
          />
        </div>
        {/* Status filter */}
        <div className="flex gap-1 text-xs shrink-0">
          {(['all', 'active', 'inactive'] as const).map(f => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={cn(
                'px-3 py-1.5 rounded-lg border transition-colors',
                statusFilter === f
                  ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300'
                  : 'border-slate-700/40 text-slate-500 hover:text-slate-300 hover:border-slate-600/50'
              )}
            >
              {{ all: 'Все', active: 'Активные', inactive: 'Отключённые' }[f]}
            </button>
          ))}
        </div>
        <button
          onClick={() => refetch()}
          className="ml-auto text-slate-500 hover:text-slate-300 transition-colors"
          title="Обновить"
        >
          <RefreshCcw className="h-4 w-4" />
        </button>
      </header>

      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-700 border border-slate-600 text-slate-100 text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto p-6">
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-14 bg-slate-800/40 border border-slate-700/30 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Users className="h-10 w-10 text-slate-700 mb-3" />
            <p className="text-slate-500 text-sm">
              {accounts.length === 0
                ? 'Ни один чаттер пока не создал аккаунт'
                : 'Нет чаттеров по фильтру'}
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-2xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-700/20">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Чаттер</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Email</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Статус</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Создан</th>
                  <th className="w-10 px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {filtered.map(account => (
                  <tr key={account.id} className="hover:bg-slate-700/20 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <Avatar account={account} />
                        <div>
                          <p className="text-sm font-medium text-slate-200">
                            {account.chatter_name || account.full_name || '—'}
                          </p>
                          {account.full_name && account.chatter_name && (
                            <p className="text-xs text-slate-500">{account.full_name}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-300">{account.email}</td>
                    <td className="px-4 py-3">
                      {account.active ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                          Активен
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-red-500/10 border border-red-500/20 text-red-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
                          Отключён
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-500">{fmtDate(account.created_at)}</td>
                    <td className="px-4 py-3">
                      <ActionsMenu
                        account={account}
                        onResetPassword={() => setConfirmReset(account)}
                        onToggleActive={() => setConfirmToggle(account)}
                        onDelete={() => setConfirmDelete(account)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Confirm: reset password ── */}
      {confirmReset && (
        <ConfirmModal
          title="Сбросить пароль"
          message={`Сгенерировать новый случайный пароль для ${confirmReset.chatter_name || confirmReset.email}? Старый пароль перестанет работать.`}
          confirmLabel="Сбросить"
          onConfirm={() => resetPasswordMut.mutate(confirmReset.id)}
          onClose={() => setConfirmReset(null)}
          loading={resetPasswordMut.isPending}
        />
      )}

      {/* ── New password modal ── */}
      {newPassword && (
        <NewPasswordModal
          name={newPassword.name}
          password={newPassword.password}
          onClose={() => setNewPassword(null)}
        />
      )}

      {/* ── Confirm: toggle active ── */}
      {confirmToggle && (
        <ConfirmModal
          title={confirmToggle.active ? 'Отключить аккаунт' : 'Активировать аккаунт'}
          message={confirmToggle.active
            ? `Чаттер ${confirmToggle.chatter_name || confirmToggle.email} потеряет доступ в кабинет.`
            : `Чаттер ${confirmToggle.chatter_name || confirmToggle.email} снова сможет войти в кабинет.`}
          confirmLabel={confirmToggle.active ? 'Отключить' : 'Активировать'}
          danger={confirmToggle.active}
          onConfirm={() => toggleActiveMut.mutate(confirmToggle)}
          onClose={() => setConfirmToggle(null)}
          loading={toggleActiveMut.isPending}
        />
      )}

      {/* ── Confirm: delete ── */}
      {confirmDelete && (
        <ConfirmModal
          title="Удалить аккаунт"
          message={`Чаттер ${confirmDelete.chatter_name || confirmDelete.email} потеряет доступ. Его транзакции и данные в системе останутся. Продолжить?`}
          confirmLabel="Удалить"
          danger
          onConfirm={() => deleteMut.mutate(confirmDelete.id)}
          onClose={() => setConfirmDelete(null)}
          loading={deleteMut.isPending}
        />
      )}
    </div>
  )
}
