import axios from 'axios'

function apiBaseURL(): string {
  const fromEnv = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '')
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const isLocal =
      host === 'localhost' || host === '127.0.0.1' || host === '[::1]'
    if (isLocal) {
      return fromEnv || 'http://localhost:8000'
    }
    // Production: explicit backend URL, or same-origin + next.config rewrites
    if (fromEnv) return fromEnv
    return ''
  }
  return fromEnv || 'http://localhost:8000'
}

const api = axios.create({
  baseURL: apiBaseURL(),
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
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
