import api from './api'
import type {
  LoginRequest,
  TokenResponse,
  TenantOut,
  RegisterResponse,
  OnboardingStatus,
} from '@/types'

function setCookie(name: string, value: string, days = 30) {
  if (typeof document === 'undefined') return
  const expires = new Date(Date.now() + days * 864e5).toUTCString()
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; expires=${expires}; SameSite=Lax`
}

function deleteCookie(name: string) {
  if (typeof document === 'undefined') return
  document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`
}

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/login', data)
  if (typeof window !== 'undefined') {
    localStorage.setItem('token', res.data.access_token)
    const role = res.data.role ?? 'owner'
    localStorage.setItem('user_role', role)
    setCookie('user_role', role)
    const isAdmin = Boolean(res.data.is_admin)
    localStorage.setItem('is_admin', isAdmin ? '1' : '0')
    setCookie('is_admin', isAdmin ? '1' : '0')
  }
  return res.data
}

export function getUserRole(): string | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('token')
  if (!token) return null
  // Попробуем сначала из localStorage (быстро)
  const cached = localStorage.getItem('user_role')
  if (cached) return cached
  // Иначе декодируем JWT
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.role ?? null
  } catch {
    return null
  }
}

export async function register(data: {
  email: string
  password: string
  agency_name: string
}): Promise<RegisterResponse> {
  const res = await api.post<RegisterResponse>('/auth/register', data)
  if (typeof window !== 'undefined') {
    localStorage.setItem('token', res.data.access_token)
    const role = res.data.role ?? 'owner'
    localStorage.setItem('user_role', role)
    setCookie('user_role', role)
  }
  return res.data
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await api.get<OnboardingStatus>('/api/v1/onboarding/status')
  return res.data
}

export function getUserIsAdmin(): boolean {
  if (typeof window === 'undefined') return false
  return localStorage.getItem('is_admin') === '1'
}

/** user_id из JWT (новый формат токена). */
export function getUserIdFromToken(): number | null {
  if (typeof window === 'undefined') return null
  const token = localStorage.getItem('token')
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split('.')[1])) as { user_id?: number }
    return payload.user_id != null ? Number(payload.user_id) : null
  } catch {
    return null
  }
}

export function logout(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('token')
    localStorage.removeItem('user_role')
    localStorage.removeItem('is_admin')
    deleteCookie('user_role')
    deleteCookie('is_admin')
    window.location.href = '/login'
  }
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('token')
}

export function isAuthenticated(): boolean {
  return getToken() !== null
}

export async function getMe(): Promise<TenantOut> {
  const res = await api.get<TenantOut>('/auth/me')
  return res.data
}
