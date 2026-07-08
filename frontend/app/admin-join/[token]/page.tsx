'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Loader2, ShieldCheck, AlertCircle, Eye, EyeOff } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { resolveApiBaseURL } from '@/lib/api'

interface InviteInfo {
  tenant_name: string
  shift_name: string
  invited_email: string | null
}

type PageState = 'loading' | 'ready' | 'invalid' | 'success'

const REASON_LABELS: Record<string, string> = {
  used:      'Ссылка уже была использована',
  expired:   'Срок действия ссылки истёк',
  not_found: 'Ссылка не найдена',
}

function saveAdminToken(data: {
  access_token: string
  role: string
  is_admin: boolean
}) {
  if (typeof window === 'undefined') return
  localStorage.setItem('token', data.access_token)
  const role = data.role ?? 'owner'
  localStorage.setItem('user_role', role)
  localStorage.setItem('is_admin', '1')
  const expires = new Date(Date.now() + 30 * 864e5).toUTCString()
  document.cookie = `user_role=${encodeURIComponent(role)}; path=/; expires=${expires}; SameSite=Lax`
  document.cookie = `is_admin=1; path=/; expires=${expires}; SameSite=Lax`
}

export default function AdminJoinPage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()

  const [pageState, setPageState] = useState<PageState>('loading')
  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [invalidReason, setInvalidReason] = useState('')

  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  useEffect(() => {
    if (!token) return
    const base = resolveApiBaseURL()
    fetch(`${base}/api/v1/admin-invites/validate/${token}`)
      .then(async (res) => {
        const data = await res.json().catch(() => ({}))
        if (!data.valid) {
          setInvalidReason(REASON_LABELS[data.reason] ?? 'Ссылка недействительна')
          setPageState('invalid')
          return
        }
        const inv = data as InviteInfo
        setInfo(inv)
        if (inv.invited_email) setEmail(inv.invited_email)
        setPageState('ready')
      })
      .catch(() => {
        setInvalidReason('Ошибка сети — попробуйте позже')
        setPageState('invalid')
      })
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    setFormError('')

    if (password !== confirmPassword) {
      setFormError('Пароли не совпадают')
      return
    }
    if (password.length < 8) {
      setFormError('Минимальная длина пароля — 8 символов')
      return
    }

    setSubmitting(true)
    try {
      const base = resolveApiBaseURL()
      const res = await fetch(`${base}/api/v1/admin-invites/activate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          email: email.trim(),
          password,
          display_name: displayName.trim(),
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setFormError(data.detail ?? 'Ошибка регистрации')
        return
      }
      saveAdminToken(data)
      router.replace('/admin-portal')
    } catch {
      setFormError('Ошибка сети — попробуйте позже')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      {/* Background glow — amber tint for admin */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[500px] h-[500px] bg-amber-600/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-amber-500 flex items-center justify-center mb-4 shadow-lg shadow-amber-500/25">
            <span className="text-white font-bold text-xl">F</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-100">FlowOF</h1>
          <p className="text-slate-400 text-sm mt-1">Портал администратора</p>
        </div>

        <div className="bg-slate-800/60 backdrop-blur-xl border border-slate-700/50 rounded-2xl p-8 shadow-2xl">
          {/* Loading */}
          {pageState === 'loading' && (
            <div className="flex flex-col items-center gap-4 py-8">
              <Loader2 className="h-8 w-8 animate-spin text-amber-400" />
              <p className="text-slate-400 text-sm">Проверяем приглашение…</p>
            </div>
          )}

          {/* Invalid */}
          {pageState === 'invalid' && (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <AlertCircle className="h-10 w-10 text-red-400" />
              <h2 className="text-lg font-semibold text-slate-100">Ссылка недействительна</h2>
              <p className="text-sm text-slate-400">{invalidReason}</p>
              <p className="text-xs text-slate-500 mt-2">
                Попросите владельца агентства создать новую ссылку.
              </p>
              <Button
                variant="outline"
                className="mt-2 border-slate-600 text-slate-300 hover:text-slate-100"
                onClick={() => router.replace('/')}
              >
                На главную
              </Button>
            </div>
          )}

          {/* Registration form */}
          {pageState === 'ready' && info && (
            <>
              {/* Invite banner */}
              <div className="flex items-start gap-3 mb-6 p-4 bg-amber-500/10 border border-amber-500/20 rounded-xl">
                <ShieldCheck className="h-5 w-5 text-amber-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-slate-100">
                    Приглашение в агентство
                  </p>
                  <p className="text-sm text-amber-300 font-medium mt-0.5">
                    {info.tenant_name}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Роль: <span className="text-slate-200 font-medium">
                      Администратор смены «{info.shift_name}»
                    </span>
                  </p>
                </div>
              </div>

              <h2 className="text-base font-semibold text-slate-100 mb-5">Создайте аккаунт</h2>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">
                    Отображаемое имя
                  </label>
                  <Input
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Имя Фамилия"
                    required
                    autoComplete="name"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">Email</label>
                  <Input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    autoComplete="email"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">Пароль</label>
                  <div className="relative">
                    <Input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Минимум 8 символов"
                      required
                      minLength={8}
                      autoComplete="new-password"
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">
                    Повторите пароль
                  </label>
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Повторите пароль"
                    required
                    autoComplete="new-password"
                  />
                </div>

                {formError && (
                  <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
                    <p className="text-sm text-red-400">{formError}</p>
                  </div>
                )}

                <Button
                  type="submit"
                  className="w-full bg-amber-600 hover:bg-amber-500 text-white"
                  disabled={submitting}
                >
                  {submitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Создаём аккаунт…
                    </>
                  ) : (
                    'Принять приглашение'
                  )}
                </Button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-xs text-slate-600 mt-6">
          FlowOF © {new Date().getFullYear()}
        </p>
      </div>
    </div>
  )
}
