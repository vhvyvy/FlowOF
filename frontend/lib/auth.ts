import api from './api'
import type {
  LoginRequest,
  TokenResponse,
  TenantOut,
  RegisterResponse,
  OnboardingStatus,
} from '@/types'

export async function login(data: LoginRequest): Promise<TokenResponse> {
  const res = await api.post<TokenResponse>('/auth/login', data)
  if (typeof window !== 'undefined') {
    localStorage.setItem('token', res.data.access_token)
  }
  return res.data
}

export async function register(data: {
  email: string
  password: string
  agency_name: string
}): Promise<RegisterResponse> {
  const res = await api.post<RegisterResponse>('/auth/register', data)
  if (typeof window !== 'undefined') {
    localStorage.setItem('token', res.data.access_token)
  }
  return res.data
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await api.get<OnboardingStatus>('/api/v1/onboarding/status')
  return res.data
}

export function logout(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('token')
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
