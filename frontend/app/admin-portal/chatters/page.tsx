'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { Plus, X, Loader2, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Chatter {
  om_user_id: string
  display_name: string
  is_mapped: boolean
  last_ppv_open_rate: number | null
  last_apv: number | null
  last_total_chats: number | null
  has_open_case: boolean
  open_case_by_me: boolean
}

type MetricType = 'ppv_open_rate' | 'rpc' | 'apv' | 'total_chats' | 'revenue'
type Priority   = 'high' | 'normal' | 'low'

const METRIC_OPTIONS: { value: MetricType; label: string }[] = [
  { value: 'ppv_open_rate', label: 'PPV Open Rate (%)' },
  { value: 'rpc',           label: 'RPC (Revenue/Chat)' },
  { value: 'apv',           label: 'APV (Avg Purchase Value)' },
  { value: 'total_chats',   label: 'Total Chats' },
  { value: 'revenue',       label: 'Revenue' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtMetric(c: Chatter, metric: MetricType): string {
  if (metric === 'ppv_open_rate') return c.last_ppv_open_rate != null ? `${c.last_ppv_open_rate}%` : '—'
  if (metric === 'apv')           return c.last_apv           != null ? `$${c.last_apv}`           : '—'
  if (metric === 'total_chats')   return c.last_total_chats   != null ? String(c.last_total_chats) : '—'
  return '—'
}

// ── Create Case Modal ─────────────────────────────────────────────────────────

interface ModalProps {
  chatter: Chatter
  onClose: () => void
  onSuccess: (caseId: number) => void
}

function CreateCaseModal({ chatter, onClose, onSuccess }: ModalProps) {
  const [metric, setMetric]       = useState<MetricType>('ppv_open_rate')
  const [diagnosis, setDiagnosis] = useState('')
  const [plan, setPlan]           = useState('')
  const [priority, setPriority]   = useState<Priority>('normal')
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!diagnosis.trim()) { setError('Укажите диагноз'); return }
    setError(null)
    setLoading(true)
    try {
      const res = await api.post<{ id: number; baseline_value: number | null }>('/api/v1/admin-portal/cases', {
        om_user_id: chatter.om_user_id,
        chatter_display_name: chatter.display_name,
        metric_type: metric,
        diagnosis_text: diagnosis,
        action_plan: plan,
        priority,
      })
      onSuccess(res.data.id)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: string } } })?.response
      const detail  = status?.data?.detail ?? 'Ошибка создания кейса'
      if (status?.status === 409) setError('Уже открыт кейс по этой метрике у этого чаттера')
      else if (status?.status === 422) setError('Недостаточно данных для baseline у этого чаттера (нет данных за 7 дней)')
      else setError(detail)
    } finally {
      setLoading(false)
    }
  }

  const currentVal = fmtMetric(chatter, metric)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Открыть кейс</h2>
            <p className="text-xs text-slate-400 mt-0.5">{chatter.display_name} · {chatter.om_user_id}</p>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-4">
          {/* Metric */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Метрика</label>
            <div className="flex gap-2 items-center">
              <select
                value={metric}
                onChange={e => setMetric(e.target.value as MetricType)}
                className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500"
              >
                {METRIC_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              {currentVal !== '—' && (
                <span className="text-sm font-semibold text-amber-300 shrink-0">
                  Сейчас: {currentVal}
                </span>
              )}
            </div>
          </div>

          {/* Diagnosis */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              Диагноз <span className="text-red-400">*</span>
            </label>
            <textarea
              value={diagnosis}
              onChange={e => setDiagnosis(e.target.value)}
              rows={3}
              placeholder="Что видишь, почему это проблема..."
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
            />
          </div>

          {/* Action plan */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">
              План действий
            </label>
            <textarea
              value={plan}
              onChange={e => setPlan(e.target.value)}
              rows={3}
              placeholder="Что собираешься делать для исправления..."
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5">Приоритет</label>
            <div className="flex gap-2">
              {(['high', 'normal', 'low'] as Priority[]).map(p => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={cn(
                    'flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors',
                    priority === p
                      ? p === 'high'   ? 'bg-red-500/20 text-red-300 ring-1 ring-red-500/50'
                      : p === 'normal' ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/50'
                      :                  'bg-slate-600/40 text-slate-300 ring-1 ring-slate-500/50'
                      : 'bg-slate-800 text-slate-500 hover:text-slate-300',
                  )}
                >
                  {p === 'high' ? 'Высокий' : p === 'normal' ? 'Обычный' : 'Низкий'}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
              <AlertCircle className="h-4 w-4 text-red-400 shrink-0 mt-0.5" />
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Submit */}
          <div className="flex gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose} className="flex-1" disabled={loading}>
              Отмена
            </Button>
            <Button type="submit" className="flex-1 bg-amber-600 hover:bg-amber-500" disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Создать кейс'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ChattersPage() {
  const router = useRouter()
  const qc = useQueryClient()
  const [modalChatter, setModalChatter] = useState<Chatter | null>(null)
  const [successMsg, setSuccessMsg]     = useState<string | null>(null)

  const { data: chatters, isLoading } = useQuery<Chatter[]>({
    queryKey: ['admin-portal-chatters'],
    queryFn: () => api.get<Chatter[]>('/api/v1/admin-portal/chatters').then(r => r.data),
  })

  function handleSuccess(caseId: number) {
    setModalChatter(null)
    qc.invalidateQueries({ queryKey: ['admin-portal-chatters'] })
    qc.invalidateQueries({ queryKey: ['admin-portal-cases-active'] })
    router.push(`/admin-portal/cases/${caseId}`)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-100">Чаттеры</h1>
        <p className="text-sm text-slate-400 mt-0.5">Список чаттеров агентства с последними KPI-метриками</p>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-14 w-full rounded-lg" />)}
        </div>
      ) : !chatters?.length ? (
        <div className="text-center py-12 text-slate-500">
          <p>Нет данных о чаттерах. Настройте маппинг Onlymonster.</p>
        </div>
      ) : (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Чаттер</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Open Rate</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">APV</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Чатов</th>
                <th className="text-center px-4 py-3 text-xs font-medium text-slate-400 uppercase tracking-wide">Статус</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/30">
              {chatters.map(c => (
                <tr key={c.om_user_id} className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium text-slate-200">{c.display_name}</p>
                      <p className="text-xs text-slate-500 mt-0.5">ID: {c.om_user_id}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-300">
                    {c.last_ppv_open_rate != null ? `${c.last_ppv_open_rate}%` : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-300">
                    {c.last_apv != null ? `$${c.last_apv}` : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-slate-300">
                    {c.last_total_chats != null ? c.last_total_chats : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {c.open_case_by_me ? (
                      <span className="text-xs bg-amber-500/15 text-amber-300 px-2 py-0.5 rounded-full">У меня</span>
                    ) : c.has_open_case ? (
                      <span className="text-xs bg-blue-500/15 text-blue-300 px-2 py-0.5 rounded-full">У другого</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => !c.has_open_case && setModalChatter(c)}
                      disabled={c.has_open_case}
                      title={c.has_open_case ? 'Уже открыт кейс' : 'Открыть кейс'}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ml-auto',
                        c.has_open_case
                          ? 'bg-slate-700/40 text-slate-600 cursor-not-allowed'
                          : 'bg-amber-600/20 text-amber-300 hover:bg-amber-600/40',
                      )}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Кейс
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalChatter && (
        <CreateCaseModal
          chatter={modalChatter}
          onClose={() => setModalChatter(null)}
          onSuccess={handleSuccess}
        />
      )}
    </div>
  )
}
