import axios, { type AxiosError } from 'axios'

/** Call per request — avoids server bundle pinning baseURL to localhost before hydration. */
export function resolveApiBaseURL(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '')
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const isLocal =
      host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
    if (isLocal) {
      return fromEnv || 'http://localhost:8000'
    }
    if (fromEnv) return fromEnv
    return ''
  }
  return fromEnv || 'http://localhost:8000'
}

const api = axios.create({
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  config.baseURL = resolveApiBaseURL()
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && typeof window !== 'undefined') {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

/** Сообщение для UI из ответа FastAPI (detail: string | ValidationError[]) или сетевой ошибки. */
export function formatApiError(err: unknown): string {
  const ax = err as AxiosError<{ detail?: unknown }>
  const d = ax.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && d.length > 0) {
    const first = d[0] as { msg?: string }
    if (typeof first?.msg === 'string') return first.msg
  }
  const code = ax.code
  const msg = ax.message
  if (!ax.response && (code === 'ERR_NETWORK' || msg === 'Network Error')) {
    const base = typeof window !== 'undefined' ? resolveApiBaseURL() : ''
    if (!base && typeof window !== 'undefined') {
      const h = window.location.hostname
      if (h !== 'localhost' && h !== '127.0.0.1') {
        return 'Не задан NEXT_PUBLIC_API_URL на фронте — укажите URL бэкенда в переменных окружения.'
      }
    }
    return 'Нет связи с API. Запустите бэкенд (локально: http://localhost:8000) или проверьте NEXT_PUBLIC_API_URL.'
  }
  if (typeof msg === 'string' && msg) return msg
  return 'Не удалось выполнить запрос.'
}
