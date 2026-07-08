'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ShieldCheck,
  UserX,
  Plus,
  Copy,
  Check,
  Trash2,
  Loader2,
  RefreshCcw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/use-toast'
import api, { resolveApiBaseURL } from '@/lib/api'

// ── Types ──────────────────────────────────────────────────────────────────

interface AdminUser {
  id: number
  name: string | null
  email: string
  admin_shift_id: number | null
  shift_name: string | null
  open_cases_count: number
  current_month_kpi: { total_points: number; cases_opened: number } | null
}

interface Invite {
  id: number
  token: string
  invited_email: string | null
  created_at: string | null
  expires_at: string | null
  shift_name: string
  admin_shift_id: number
  join_url: string
}

interface Shift {
  id: number
  name: string
}

// ── API helpers ─────────────────────────────────────────────────────────────

async function fetchAdmins(): Promise<AdminUser[]> {
  const res = await api.get('/api/v1/dashboard/admins-review/admins')
  return Array.isArray(res.data) ? res.data : (res.data.items ?? [])
}

async function fetchInvites(): Promise<Invite[]> {
  const res = await api.get('/api/v1/admin-invites/')
  return res.data.items ?? []
}

async function fetchShifts(): Promise<Shift[]> {
  const res = await api.get('/api/v1/catalog/shifts')
  return (res.data.items ?? res.data) as Shift[]
}

// ── Main component ──────────────────────────────────────────────────────────

export default function AdminsPage() {
  const qc = useQueryClient()
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteShiftId, setInviteShiftId] = useState<string>('')
  const [copiedToken, setCopiedToken] = useState<string | null>(null)
  const [modalUrl, setModalUrl] = useState<string | null>(null)
  const [revokeConfirm, setRevokeConfirm] = useState<number | null>(null)

  const { data: admins = [], isLoading: loadingAdmins } = useQuery({
    queryKey: ['admins-list'],
    queryFn: fetchAdmins,
  })

  const { data: invites = [], isLoading: loadingInvites } = useQuery({
    queryKey: ['admin-invites'],
    queryFn: fetchInvites,
  })

  const { data: shifts = [], isLoading: loadingShifts } = useQuery({
    queryKey: ['shifts-catalog'],
    queryFn: fetchShifts,
  })

  // Create invite
  const createInvite = useMutation({
    mutationFn: async () => {
      if (!inviteShiftId) throw new Error('Выберите смену')
      const body: Record<string, unknown> = {
        admin_shift_id: Number(inviteShiftId),
        expires_in_days: 14,
      }
      if (inviteEmail.trim()) body.invited_email = inviteEmail.trim()
      const res = await api.post('/api/v1/admin-invites/create', body)
      return res.data as { join_url: string; shift_name: string }
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['admin-invites'] })
      setInviteEmail('')
      setInviteShiftId('')
      setModalUrl(data.join_url)
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Ошибка создания инвайта'
      toast({ title: msg, variant: 'destructive' })
    },
  })

  // Revoke invite
  const deleteInvite = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/admin-invites/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-invites'] }),
    onError: () => toast({ title: 'Ошибка при отзыве инвайта', variant: 'destructive' }),
  })

  // Revoke admin access
  const revokeAdmin = useMutation({
    mutationFn: (userId: number) =>
      api.patch(`/api/v1/admin-invites/users/${userId}/revoke`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admins-list'] })
      toast({ title: 'Доступ администратора отозван' })
      setRevokeConfirm(null)
    },
    onError: () => toast({ title: 'Ошибка при отзыве доступа', variant: 'destructive' }),
  })

  function copyUrl(url: string, token: string) {
    navigator.clipboard.writeText(url).then(() => {
      setCopiedToken(token)
      setTimeout(() => setCopiedToken(null), 2000)
    })
  }

  const isCreating = createInvite.isPending

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-8">
      <div className="flex items-center gap-3">
        <ShieldCheck className="h-6 w-6 text-amber-400" />
        <h1 className="text-xl font-bold text-slate-100">Управление администраторами</h1>
      </div>

      {/* ── Existing admins ─────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Активные администраторы
        </h2>
        {loadingAdmins ? (
          <div className="flex items-center gap-2 text-slate-500 py-6">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Загрузка…</span>
          </div>
        ) : admins.length === 0 ? (
          <p className="text-sm text-slate-500 py-4">
            Администраторов пока нет. Создайте инвайт ниже.
          </p>
        ) : (
          <div className="space-y-2">
            {admins.map((admin) => (
              <div
                key={admin.id}
                className="flex items-center justify-between bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center shrink-0">
                    <span className="text-amber-300 text-xs font-bold">
                      {(admin.name ?? admin.email)[0].toUpperCase()}
                    </span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-100 truncate">
                      {admin.name ?? '—'}
                    </p>
                    <p className="text-xs text-slate-400 truncate">{admin.email}</p>
                  </div>
                </div>

                <div className="flex items-center gap-4 shrink-0 ml-4">
                  {admin.shift_name && (
                    <Badge className="bg-amber-500/15 text-amber-300 border-amber-500/30 text-xs">
                      {admin.shift_name}
                    </Badge>
                  )}
                  <span className="text-xs text-slate-400 hidden sm:block">
                    {admin.open_cases_count} активных кейсов
                  </span>
                  {revokeConfirm === admin.id ? (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-red-400">Точно отозвать?</span>
                      <Button
                        size="sm"
                        variant="destructive"
                        className="h-7 text-xs"
                        disabled={revokeAdmin.isPending}
                        onClick={() => revokeAdmin.mutate(admin.id)}
                      >
                        {revokeAdmin.isPending ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          'Да'
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs text-slate-400"
                        onClick={() => setRevokeConfirm(null)}
                      >
                        Отмена
                      </Button>
                    </div>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 gap-1.5 text-slate-400 hover:text-red-400 hover:bg-red-400/10"
                      onClick={() => setRevokeConfirm(admin.id)}
                    >
                      <UserX className="h-4 w-4" />
                      <span className="hidden sm:block text-xs">Отозвать доступ</span>
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Create invite ────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">
          Пригласить администратора
        </h2>
        <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">
                Смена <span className="text-red-400">*</span>
              </label>
              {loadingShifts ? (
                <div className="flex items-center gap-2 h-9">
                  <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
                  <span className="text-sm text-slate-500">Загрузка смен…</span>
                </div>
              ) : (
                <Select value={inviteShiftId} onValueChange={setInviteShiftId}>
                  <SelectTrigger className="bg-slate-700/50 border-slate-600">
                    <SelectValue placeholder="Выберите смену" />
                  </SelectTrigger>
                  <SelectContent>
                    {shifts.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1.5">
                Email (необязательно)
              </label>
              <Input
                type="email"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="admin@example.com"
                className="bg-slate-700/50 border-slate-600"
              />
            </div>
          </div>
          <Button
            className="bg-amber-600 hover:bg-amber-500 text-white gap-2"
            disabled={!inviteShiftId || isCreating}
            onClick={() => createInvite.mutate()}
          >
            {isCreating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            Создать инвайт
          </Button>
        </div>
      </section>

      {/* ── Active invites ───────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">
            Активные инвайты
          </h2>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 text-slate-400 hover:text-slate-200"
            onClick={() => qc.invalidateQueries({ queryKey: ['admin-invites'] })}
          >
            <RefreshCcw className="h-3.5 w-3.5" />
            <span className="text-xs">Обновить</span>
          </Button>
        </div>

        {loadingInvites ? (
          <div className="flex items-center gap-2 text-slate-500 py-4">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Загрузка…</span>
          </div>
        ) : invites.length === 0 ? (
          <p className="text-sm text-slate-500 py-4">Активных инвайтов нет.</p>
        ) : (
          <div className="space-y-2">
            {invites.map((inv) => (
              <div
                key={inv.id}
                className="flex items-center justify-between bg-slate-800/50 border border-slate-700/50 rounded-xl px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge className="bg-amber-500/15 text-amber-300 border-amber-500/30 text-xs">
                      {inv.shift_name}
                    </Badge>
                    {inv.invited_email && (
                      <span className="text-xs text-slate-400">{inv.invited_email}</span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-1">
                    Создан:{' '}
                    {inv.created_at
                      ? new Date(inv.created_at).toLocaleDateString('ru-RU')
                      : '—'}
                    {inv.expires_at &&
                      ` · Истекает: ${new Date(inv.expires_at).toLocaleDateString('ru-RU')}`}
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0 ml-3">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 gap-1.5 border-slate-600 text-slate-300 hover:text-slate-100 text-xs"
                    onClick={() => copyUrl(inv.join_url, inv.token)}
                  >
                    {copiedToken === inv.token ? (
                      <Check className="h-3.5 w-3.5 text-green-400" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                    {copiedToken === inv.token ? 'Скопировано' : 'Ссылка'}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 text-slate-400 hover:text-red-400 hover:bg-red-400/10"
                    onClick={() => deleteInvite.mutate(inv.id)}
                    disabled={deleteInvite.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Modal: show new join URL ─────────────────────────────────────── */}
      <Dialog open={!!modalUrl} onOpenChange={(o) => !o && setModalUrl(null)}>
        <DialogContent className="bg-slate-800 border-slate-700 max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-slate-100">Инвайт создан</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <p className="text-sm text-slate-400">
              Отправьте эту ссылку будущему администратору.
              Ссылка действует 14 дней.
            </p>
            <div className="bg-slate-700/60 border border-slate-600 rounded-lg px-3 py-2 break-all text-xs text-amber-300 font-mono">
              {modalUrl}
            </div>
            <div className="flex gap-2">
              <Button
                className="flex-1 bg-amber-600 hover:bg-amber-500 text-white gap-2"
                onClick={() => {
                  if (modalUrl) navigator.clipboard.writeText(modalUrl)
                  setCopiedToken('modal')
                  setTimeout(() => setCopiedToken(null), 2000)
                }}
              >
                {copiedToken === 'modal' ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                {copiedToken === 'modal' ? 'Скопировано!' : 'Скопировать'}
              </Button>
              <Button
                variant="outline"
                className="flex-1 border-slate-600 text-slate-300 hover:text-slate-100"
                onClick={() => setModalUrl(null)}
              >
                Готово
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
