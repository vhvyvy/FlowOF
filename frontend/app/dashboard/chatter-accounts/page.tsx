'use client'

import { useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search, MoreHorizontal, KeyRound, UserCheck, UserX, Trash2,
  X, Copy, Check, RefreshCcw, Users, UserPlus, Shield, ShieldOff,
} from 'lucide-react'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ChatterAccount {
  id: number | null       // user_id (null if no account)
  chatter_id: number
  chatter_name: string | null
  email: string | null
  full_name: string | null
  active: boolean
  created_at: string | null
  has_account: boolean
  avatar_base64: string | null
}

type StatusFilter = 'all' | 'active' | 'inactive' | 'no_account'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' }) }
  catch { return '—' }
}

function Avatar({ account }: { account: ChatterAccount }) {
  const label = (account.chatter_name || account.full_name || account.email || '?').slice(0, 1).toUpperCase()
  if (account.avatar_base64) {
    return <img src={account.avatar_base64} alt="" className="w-9 h-9 rounded-full object-cover shrink-0 ring-1 ring-slate-600/40" />
  }
  return (
    <div className="w-9 h-9 rounded-full bg-slate-700 flex items-center justify-center shrink-0 text-sm font-bold text-slate-400">
      {label}
    </div>
  )
}

// ─── New-password modal ───────────────────────────────────────────────────────

function NewPasswordModal({ name, password, onClose }: { name: string; password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try { await navigator.clipboard.writeText(password) } catch { /* ignore */ }
    setCopied(true); setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="w-full max-w-sm bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <p className="text-sm font-semibold text-slate-100">Новый пароль</p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-slate-400">Пароль для <span className="text-slate-200 font-medium">{name}</span> сброшен.</p>
          <div className="bg-slate-700/60 border border-slate-600/40 rounded-xl px-4 py-3 flex items-center gap-3">
            <span className="flex-1 font-mono text-lg text-slate-100 tracking-widest">{password}</span>
            <button onClick={copy} className="text-slate-400 hover:text-violet-300 transition-colors">
              {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-[11px] text-amber-400/80">⚠ Пароль больше не будет показан. Скопируйте и передайте чаттеру.</p>
        </div>
        <div className="px-5 pb-5">
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
  title, message, confirmLabel, danger, onConfirm, onClose, loading,
}: {
  title: string; message: string; confirmLabel: string; danger?: boolean
  onConfirm: () => void; onClose: () => void; loading?: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70">
      <div className="w-full max-w-sm bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <p className="text-sm font-semibold text-slate-100">{title}</p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300"><X className="h-5 w-5" /></button>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-slate-300 leading-relaxed">{message}</p>
        </div>
        <div className="px-5 pb-5 flex gap-2">
          <button
            onClick={onConfirm} disabled={loading}
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
  account, onResetPassword, onToggleActive, onDelete,
}: {
  account: ChatterAccount
  onResetPassword: () => void
  onToggleActive: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  if (!account.has_account) return null

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
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-9 z-20 w-52 bg-slate-800 border border-slate-700/50 rounded-xl shadow-2xl py-1.5 overflow-hidden">
            <button
              onClick={() => { setOpen(false); onResetPassword() }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-slate-300 hover:bg-slate-700/60 transition-colors"
            >
              <KeyRound className="h-3.5 w-3.5 text-amber-400 shrink-0" />
              Сбросить пароль
            </button>
            <button
              onClick={() => { setOpen(false); onToggleActive() }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-slate-300 hover:bg-slate-700/60 transition-colors"
            >
              {account.active
                ? <><ShieldOff className="h-3.5 w-3.5 text-orange-400 shrink-0" />Отключить аккаунт</>
                : <><Shield className="h-3.5 w-3.5 text-emerald-400 shrink-0" />Активировать</>
              }
            </button>
            <div className="border-t border-slate-700/40 mx-2 my-1" />
            <button
              onClick={() => { setOpen(false); onDelete() }}
              className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-red-400 hover:bg-slate-700/60 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5 shrink-0" />Удалить аккаунт
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ account }: { account: ChatterAccount }) {
  if (!account.has_account) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-slate-700/60 border border-slate-600/40 text-slate-400">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
        Нет аккаунта
      </span>
    )
  }
  if (account.active) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
        Активен
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-red-500/10 border border-red-500/20 text-red-400">
      <span className="w-1.5 h-1.5 rounded-full bg-red-400" />
      Отключён
    </span>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ChatterAccountsPage() {
  const qc = useQueryClient()
  const searchParams = useSearchParams()
  const [search,       setSearch]       = useState(searchParams.get('q') ?? '')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [toast,        setToast]        = useState<string | null>(null)

  const [confirmReset,  setConfirmReset]  = useState<ChatterAccount | null>(null)
  const [confirmToggle, setConfirmToggle] = useState<ChatterAccount | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<ChatterAccount | null>(null)
  const [newPassword,   setNewPassword]   = useState<{ name: string; password: string } | null>(null)

  function showToast(msg: string) {
    setToast(msg); setTimeout(() => setToast(null), 2500)
  }

  const { data, isLoading, refetch } = useQuery<{ items: ChatterAccount[] }>({
    queryKey: ['manage-chatters'],
    queryFn: () => api.get('/api/v1/manage/chatters').then(r => r.data),
  })
  const accounts = data?.items ?? []

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

  // ── Filter ────────────────────────────────────────────────────────────────

  const filtered = accounts.filter(a => {
    const q = search.toLowerCase()
    const matchSearch = !q || (
      (a.chatter_name || '').toLowerCase().includes(q) ||
      (a.email || '').toLowerCase().includes(q) ||
      (a.full_name || '').toLowerCase().includes(q)
    )
    const matchStatus =
      statusFilter === 'all'        ? true :
      statusFilter === 'active'     ? (a.has_account && a.active) :
      statusFilter === 'inactive'   ? (a.has_account && !a.active) :
      /* no_account */                !a.has_account
    return matchSearch && matchStatus
  })

  // Stats
  const totalActive   = accounts.filter(a => a.has_account && a.active).length
  const totalInactive = accounts.filter(a => a.has_account && !a.active).length
  const totalNoAcct   = accounts.filter(a => !a.has_account).length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900 shrink-0">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2.5">
            <Users className="h-5 w-5 text-indigo-400" />
            <h1 className="text-lg font-semibold text-slate-100">Аккаунты чаттеров</h1>
          </div>

          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Поиск по имени или email…"
              className="w-full pl-8 pr-3 py-1.5 text-sm bg-slate-800 border border-slate-700/50 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50"
            />
          </div>

          {/* Status filter */}
          <div className="flex gap-1 text-xs">
            {([
              ['all', `Все (${accounts.length})`],
              ['active', `Активные (${totalActive})`],
              ['inactive', `Отключённые (${totalInactive})`],
              ['no_account', `Без аккаунта (${totalNoAcct})`],
            ] as [StatusFilter, string][]).map(([f, label]) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={cn(
                  'px-2.5 py-1.5 rounded-lg border transition-colors whitespace-nowrap',
                  statusFilter === f
                    ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300'
                    : 'border-slate-700/40 text-slate-500 hover:text-slate-300 hover:border-slate-600/50'
                )}
              >
                {label}
              </button>
            ))}
          </div>

          <button
            onClick={() => refetch()}
            className="ml-auto text-slate-500 hover:text-slate-300 transition-colors shrink-0"
            title="Обновить"
          >
            <RefreshCcw className="h-4 w-4" />
          </button>
        </div>
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
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="h-[60px] bg-slate-800/40 border border-slate-700/30 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Users className="h-10 w-10 text-slate-700 mb-3" />
            <p className="text-slate-500 text-sm">
              {accounts.length === 0 ? 'Нет чаттеров в справочнике' : 'Нет чаттеров по фильтру'}
            </p>
          </div>
        ) : (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-2xl overflow-visible">
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-slate-700/50 bg-slate-700/20">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide rounded-tl-2xl">Чаттер</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Email</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Статус</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide">Создан</th>
                  <th className="w-12 px-5 py-3 rounded-tr-2xl" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30">
                {filtered.map(account => (
                  <tr
                    key={account.chatter_id}
                    className={cn(
                      'transition-colors',
                      account.has_account ? 'hover:bg-slate-700/20' : 'opacity-60 hover:opacity-80',
                    )}
                  >
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <Avatar account={account} />
                        <div>
                          <p className="text-sm font-medium text-slate-200">
                            {account.chatter_name || '—'}
                          </p>
                          {account.full_name && account.full_name !== account.chatter_name && (
                            <p className="text-xs text-slate-500">{account.full_name}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-sm text-slate-400">
                      {account.email ?? <span className="text-slate-600 italic">нет аккаунта</span>}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge account={account} />
                    </td>
                    <td className="px-5 py-3.5 text-sm text-slate-500">
                      {account.has_account ? fmtDate(account.created_at) : '—'}
                    </td>
                    <td className="px-5 py-3.5">
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

      {/* ── Modals ── */}
      {confirmReset && (
        <ConfirmModal
          title="Сбросить пароль"
          message={`Сгенерировать новый пароль для ${confirmReset.chatter_name || confirmReset.email}? Старый перестанет работать.`}
          confirmLabel="Сбросить"
          onConfirm={() => confirmReset.id && resetPasswordMut.mutate(confirmReset.id)}
          onClose={() => setConfirmReset(null)}
          loading={resetPasswordMut.isPending}
        />
      )}
      {newPassword && (
        <NewPasswordModal name={newPassword.name} password={newPassword.password} onClose={() => setNewPassword(null)} />
      )}
      {confirmToggle && (
        <ConfirmModal
          title={confirmToggle.active ? 'Отключить аккаунт' : 'Активировать аккаунт'}
          message={confirmToggle.active
            ? `${confirmToggle.chatter_name || confirmToggle.email} потеряет доступ в кабинет.`
            : `${confirmToggle.chatter_name || confirmToggle.email} снова сможет войти в кабинет.`}
          confirmLabel={confirmToggle.active ? 'Отключить' : 'Активировать'}
          danger={confirmToggle.active}
          onConfirm={() => toggleActiveMut.mutate(confirmToggle)}
          onClose={() => setConfirmToggle(null)}
          loading={toggleActiveMut.isPending}
        />
      )}
      {confirmDelete && (
        <ConfirmModal
          title="Удалить аккаунт"
          message={`${confirmDelete.chatter_name || confirmDelete.email} потеряет доступ. Транзакции и данные останутся. Продолжить?`}
          confirmLabel="Удалить"
          danger
          onConfirm={() => confirmDelete.id && deleteMut.mutate(confirmDelete.id)}
          onClose={() => setConfirmDelete(null)}
          loading={deleteMut.isPending}
        />
      )}
    </div>
  )
}
