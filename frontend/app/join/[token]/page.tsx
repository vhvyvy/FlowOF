'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Loader2, UserCheck, AlertCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { resolveApiBaseURL } from '@/lib/api'

interface InviteInfo {
  chatter_name: string
  agency_name: string
}

type PageState = 'loading' | 'ready' | 'invalid' | 'success'

export default function JoinPage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()

  const [pageState, setPageState] = useState<PageState>('loading')
  const [info, setInfo] = useState<InviteInfo | null>(null)
  const [inviteError, setInviteError] = useState('')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  useEffect(() => {
    if (!token) return
    const base = resolveApiBaseURL()
    fetch(`${base}/api/v1/invites/info/${token}`)
      .then(async (res) => {
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          setInviteError(data.detail ?? 'Инвайт недействителен')
          setPageState('invalid')
          return
        }
        const data: InviteInfo = await res.json()
        setInfo(data)
        setPageState('ready')
      })
      .catch(() => {
        setInviteError('Ошибка сети — попробуйте позже')
        setPageState('invalid')
      })
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token) return
    setFormError('')
    setSubmitting(true)
    try {
      const base = resolveApiBaseURL()
      const res = await fetch(`${base}/api/v1/invites/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, email: email.trim(), password, full_name: fullName.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        setFormError(data.detail ?? 'Ошибка регистрации')
        return
      }
      // Сохраняем токен и редиректим в портал
      if (typeof window !== 'undefined') {
        const role = data.role ?? 'chatter'
        localStorage.setItem('token', data.access_token)
        localStorage.setItem('user_role', role)
        // Устанавливаем cookie для middleware
        const expires = new Date(Date.now() + 30 * 864e5).toUTCString()
        document.cookie = `user_role=${encodeURIComponent(role)}; path=/; expires=${expires}; SameSite=Lax`
      }
      router.replace('/portal')
    } catch {
      setFormError('Ошибка сети — попробуйте позже')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
      {/* Фоновый glow */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[500px] h-[500px] bg-violet-600/10 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-sm">
        {/* Логотип */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-violet-500 flex items-center justify-center mb-4 shadow-lg shadow-violet-500/25">
            <span className="text-white font-bold text-xl">F</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-100">FlowOF</h1>
          <p className="text-slate-400 text-sm mt-1">Личный кабинет чаттера</p>
        </div>

        <div className="bg-slate-800/60 backdrop-blur-xl border border-slate-700/50 rounded-2xl p-8 shadow-2xl">
          {/* Загрузка */}
          {pageState === 'loading' && (
            <div className="flex flex-col items-center gap-4 py-8">
              <Loader2 className="h-8 w-8 animate-spin text-violet-400" />
              <p className="text-slate-400 text-sm">Проверяем инвайт…</p>
            </div>
          )}

          {/* Ошибка инвайта */}
          {pageState === 'invalid' && (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <AlertCircle className="h-10 w-10 text-red-400" />
              <h2 className="text-lg font-semibold text-slate-100">Инвайт недействителен</h2>
              <p className="text-sm text-slate-400">{inviteError}</p>
              <p className="text-xs text-slate-500 mt-2">
                Попросите владельца агентства создать новую ссылку.
              </p>
            </div>
          )}

          {/* Форма регистрации */}
          {pageState === 'ready' && info && (
            <>
              {/* Шапка с приглашением */}
              <div className="flex items-start gap-3 mb-6 p-4 bg-violet-500/10 border border-violet-500/20 rounded-xl">
                <UserCheck className="h-5 w-5 text-violet-400 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-slate-100">
                    Вас приглашают в агентство
                  </p>
                  <p className="text-sm text-violet-300 font-medium mt-0.5">
                    {info.agency_name}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">
                    Ваш чаттер: <span className="text-slate-200 font-medium">{info.chatter_name}</span>
                  </p>
                </div>
              </div>

              <h2 className="text-base font-semibold text-slate-100 mb-5">Создайте аккаунт</h2>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1.5">
                    Ваше имя
                  </label>
                  <Input
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
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
                  <Input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Минимум 8 символов"
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                </div>

                {formError && (
                  <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
                    <p className="text-sm text-red-400">{formError}</p>
                  </div>
                )}

                <Button type="submit" className="w-full bg-violet-600 hover:bg-violet-500" disabled={submitting}>
                  {submitting ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      Создаём аккаунт…
                    </>
                  ) : (
                    'Войти в кабинет'
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
