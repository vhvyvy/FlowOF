'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AdminTenant } from '@/types'
import {
  Shield, Users, RefreshCw, CheckCircle2, XCircle,
  Crown, ChevronDown, Trash2, AlertCircle,
} from 'lucide-react'

function formatDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('ru', { day: '2-digit', month: 'short', year: 'numeric' })
}

function PlanBadge({ plan }: { plan: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold ${
      plan === 'pro'
        ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/30'
        : 'bg-slate-700/60 text-slate-400 border border-slate-600/40'
    }`}>
      {plan === 'pro' && <Crown className="h-3 w-3 mr-1" />}
      {plan.toUpperCase()}
    </span>
  )
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${active ? 'text-emerald-400' : 'text-slate-500'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-emerald-400' : 'bg-slate-500'}`} />
      {active ? 'Активен' : 'Отключён'}
    </span>
  )
}

interface PlanSelectProps {
  tenantId: number
  current: string
  onUpdate: (id: number, patch: { plan?: string; active?: boolean }) => void
  loading: boolean
}

function PlanSelect({ tenantId, current, onUpdate, loading }: PlanSelectProps) {
  return (
    <div className="relative inline-flex items-center">
      <select
        value={current}
        onChange={(e) => onUpdate(tenantId, { plan: e.target.value })}
        disabled={loading}
        className="appearance-none bg-slate-800 border border-slate-700 text-slate-300 text-xs rounded-lg pl-2.5 pr-7 py-1.5 focus:outline-none focus:border-indigo-500 disabled:opacity-50 cursor-pointer"
      >
        <option value="basic">Basic</option>
        <option value="pro">Pro</option>
      </select>
      <ChevronDown className="absolute right-2 h-3 w-3 text-slate-500 pointer-events-none" />
    </div>
  )
}

export default function AdminPage() {
  const qc = useQueryClient()
  const [confirmDeactivate, setConfirmDeactivate] = useState<number | null>(null)
  const [opError, setOpError] = useState<string | null>(null)

  const { data: tenants, isLoading, error } = useQuery<AdminTenant[]>({
    queryKey: ['admin-tenants'],
    queryFn: () => api.get<AdminTenant[]>('/api/v1/admin/tenants').then((r) => r.data),
    staleTime: 30_000,
  })

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: { plan?: string; active?: boolean } }) =>
      api.patch(`/api/v1/admin/tenants/${id}`, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-tenants'] })
      setOpError(null)
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setOpError(ax.response?.data?.detail ?? ax.message ?? 'Ошибка')
    },
  })

  const deactivateMut = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/admin/tenants/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-tenants'] })
      setConfirmDeactivate(null)
      setOpError(null)
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setOpError(ax.response?.data?.detail ?? ax.message ?? 'Ошибка деактивации')
      setConfirmDeactivate(null)
    },
  })

  const handleUpdate = (id: number, patch: { plan?: string; active?: boolean }) => {
    updateMut.mutate({ id, patch })
  }

  const stats = tenants
    ? {
        total: tenants.length,
        active: tenants.filter((t) => t.active).length,
        pro: tenants.filter((t) => t.plan === 'pro').length,
        onboarded: tenants.filter((t) => t.onboarding_completed).length,
      }
    : null

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Header */}
      <div className="border-b border-slate-800/60 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center">
              <Shield className="h-4 w-4 text-indigo-400" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-white">Admin Panel</h1>
              <p className="text-xs text-slate-500">FlowOF Developer Console</p>
            </div>
          </div>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['admin-tenants'] })}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Обновить
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
        {/* Stats row */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: 'Всего агентств', value: stats.total, icon: Users, color: 'text-slate-300' },
              { label: 'Активных', value: stats.active, icon: CheckCircle2, color: 'text-emerald-400' },
              { label: 'Pro планов', value: stats.pro, icon: Crown, color: 'text-indigo-400' },
              { label: 'Прошли онбординг', value: stats.onboarded, icon: Shield, color: 'text-violet-400' },
            ].map(({ label, value, icon: Icon, color }) => (
              <div key={label} className="bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-4">
                <div className="flex items-center gap-2 mb-1">
                  <Icon className={`h-3.5 w-3.5 ${color}`} />
                  <p className="text-xs text-slate-500">{label}</p>
                </div>
                <p className="text-2xl font-bold text-white">{value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {opError && (
          <div className="flex items-center gap-2 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {opError}
          </div>
        )}

        {/* Table */}
        <div className="bg-slate-900/60 border border-slate-700/40 rounded-2xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800/60 flex items-center justify-between">
            <p className="text-sm font-medium text-slate-200">Все агентства</p>
            {isLoading && <RefreshCw className="h-3.5 w-3.5 text-slate-500 animate-spin" />}
          </div>

          {error && (
            <div className="px-5 py-8 text-center text-sm text-red-400">
              Ошибка загрузки. Убедись, что у тебя is_admin = true.
            </div>
          )}

          {!isLoading && !error && tenants && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800/60">
                    {['ID', 'Агентство', 'Email', 'План', 'Статус', 'Онбординг', 'Регистрация', 'Последний синк', 'Действия'].map((h) => (
                      <th key={h} className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase tracking-wide whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((t) => (
                    <tr key={t.id} className={`border-b border-slate-800/30 transition-colors ${!t.active ? 'opacity-50' : 'hover:bg-slate-800/20'}`}>
                      <td className="px-4 py-3 text-slate-500 font-mono text-xs">{t.id}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {t.is_admin && (
                            <span title="Администратор">
                              <Shield className="h-3 w-3 text-indigo-400 shrink-0" />
                            </span>
                          )}
                          <span className="font-medium text-slate-200 whitespace-nowrap">
                            {t.agency_name ?? '—'}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-400 font-mono text-xs">{t.email}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <PlanBadge plan={t.plan} />
                          <PlanSelect
                            tenantId={t.id}
                            current={t.plan}
                            onUpdate={handleUpdate}
                            loading={updateMut.isPending}
                          />
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusDot active={t.active} />
                      </td>
                      <td className="px-4 py-3">
                        {t.onboarding_completed
                          ? <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                          : <XCircle className="h-4 w-4 text-slate-600" />}
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{formatDate(t.created_at)}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{formatDate(t.last_sync_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {/* Toggle active */}
                          <button
                            onClick={() => handleUpdate(t.id, { active: !t.active })}
                            disabled={updateMut.isPending}
                            title={t.active ? 'Деактивировать' : 'Активировать'}
                            className={`px-2.5 py-1.5 text-xs rounded-lg border transition-colors disabled:opacity-50 ${
                              t.active
                                ? 'border-slate-600 text-slate-400 hover:border-amber-500/50 hover:text-amber-400'
                                : 'border-slate-700 text-slate-500 hover:border-emerald-500/50 hover:text-emerald-400'
                            }`}
                          >
                            {t.active ? 'Откл' : 'Вкл'}
                          </button>

                          {/* Deactivate confirm */}
                          {confirmDeactivate === t.id ? (
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => deactivateMut.mutate(t.id)}
                                disabled={deactivateMut.isPending}
                                className="px-2 py-1.5 text-xs bg-red-500/20 border border-red-500/40 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors disabled:opacity-50"
                              >
                                Да
                              </button>
                              <button
                                onClick={() => setConfirmDeactivate(null)}
                                className="px-2 py-1.5 text-xs border border-slate-700 text-slate-500 rounded-lg hover:text-slate-300 transition-colors"
                              >
                                Нет
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => setConfirmDeactivate(t.id)}
                              title="Удалить (деактивировать)"
                              className="p-1.5 rounded-lg border border-slate-700 text-slate-500 hover:border-red-500/40 hover:text-red-400 transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {tenants.length === 0 && (
                <p className="text-center text-slate-500 text-sm py-10">Нет агентств.</p>
              )}
            </div>
          )}
        </div>

        <p className="text-xs text-slate-600 text-center">
          Изменения применяются мгновенно. Деактивированные аккаунты теряют доступ к API.
        </p>

        {/* ── Notion ↔ DB diff ── */}
        <NotionDiff />
      </div>
    </div>
  )
}

// ─── Notion ↔ DB diff ────────────────────────────────────────────────────────

interface DiffTotals {
  notion_sum: number; db_sum: number; diff: number
  notion_count: number; db_count: number
}
interface MismatchRow {
  notion_id: string; date: string; model: string; shift: string
  notion_amount: number; db_amount: number; diff: number
}
interface SimpleRow {
  notion_id?: string; id?: number; date: string; model: string; shift?: string; amount: number
}
interface DiffResult {
  matched_ok: number
  amount_mismatch: MismatchRow[]
  notion_only: SimpleRow[]
  db_only: SimpleRow[]
  totals: DiffTotals
}

function fmt$(v: number) { return `$${v.toFixed(2)}` }
function fmtDiff(v: number) {
  const s = v.toFixed(2)
  return v > 0 ? <span className="text-red-400">+{s}</span>
       : v < 0 ? <span className="text-emerald-400">{s}</span>
       : <span className="text-slate-500">0</span>
}

function NotionDiff() {
  const now = new Date()
  const [tenantId, setTenantId] = useState('')
  const [chatter,  setChatter]  = useState('')
  const [year,     setYear]     = useState(String(now.getFullYear()))
  const [month,    setMonth]    = useState(String(now.getMonth() + 1))
  const [loading,  setLoading]  = useState(false)
  const [result,   setResult]   = useState<DiffResult | null>(null)
  const [error,    setError]    = useState<string | null>(null)
  const [showNotionOnly, setShowNotionOnly] = useState(false)
  const [showDbOnly,     setShowDbOnly]     = useState(false)

  async function run() {
    setLoading(true); setError(null); setResult(null)
    try {
      const res = await api.get<DiffResult>('/api/v1/admin/notion-diff', {
        params: { tenant_id: tenantId, chatter, year, month },
      })
      setResult(res.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Ошибка запроса')
    } finally {
      setLoading(false)
    }
  }

  const t = result?.totals

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-2xl p-6 space-y-5">
      <div className="flex items-center gap-2">
        <span className="text-base font-semibold text-slate-200">Сверка Notion ↔ База</span>
        <span className="text-xs text-slate-500 bg-slate-700/60 px-2 py-0.5 rounded-full">read-only</span>
      </div>

      {/* Form */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Tenant ID', val: tenantId, set: setTenantId, ph: '1' },
          { label: 'Чаттер',   val: chatter,  set: setChatter,  ph: 'Baby_W0rker' },
          { label: 'Год',      val: year,      set: setYear,     ph: '2026' },
          { label: 'Месяц',    val: month,     set: setMonth,    ph: '6' },
        ].map(({ label, val, set, ph }) => (
          <div key={label}>
            <p className="text-xs text-slate-500 mb-1">{label}</p>
            <input
              value={val}
              onChange={e => set(e.target.value)}
              placeholder={ph}
              className="w-full text-sm bg-slate-700/60 border border-slate-600/40 rounded-lg px-3 py-1.5 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50"
            />
          </div>
        ))}
      </div>

      <button
        onClick={run}
        disabled={loading || !tenantId || !chatter || !year || !month}
        className="px-4 py-2 bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/40 text-indigo-300 text-sm font-medium rounded-xl transition-colors disabled:opacity-40"
      >
        {loading ? 'Сверяю…' : 'Сверить'}
      </button>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {result && t && (
        <div className="space-y-4">
          {/* Totals */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: 'Notion сумма',  val: fmt$(t.notion_sum),    color: 'text-slate-200' },
              { label: 'БД сумма',      val: fmt$(t.db_sum),        color: 'text-slate-200' },
              { label: 'Разница',       val: fmt$(t.diff),          color: t.diff === 0 ? 'text-emerald-400' : 'text-red-400' },
              { label: 'Записей Notion',val: String(t.notion_count), color: 'text-slate-200' },
              { label: 'Записей БД',    val: String(t.db_count),    color: 'text-slate-200' },
            ].map(({ label, val, color }) => (
              <div key={label} className="bg-slate-700/40 border border-slate-600/30 rounded-xl p-3">
                <p className="text-xs text-slate-500">{label}</p>
                <p className={`text-lg font-bold mt-0.5 ${color}`}>{val}</p>
              </div>
            ))}
          </div>

          {/* Matched ok */}
          <p className="text-xs text-emerald-400/80">
            ✓ Совпало без расхождений: <span className="font-semibold">{result.matched_ok}</span>
          </p>

          {/* Amount mismatch — main table */}
          {result.amount_mismatch.length > 0 ? (
            <div>
              <p className="text-sm font-semibold text-red-400 mb-2">
                Расхождение сумм ({result.amount_mismatch.length})
              </p>
              <div className="overflow-x-auto rounded-xl border border-red-500/20">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-red-500/10 text-slate-400 text-xs uppercase tracking-wide">
                      {['Дата','Модель','Смена','Notion $','БД $','Разница'].map(h => (
                        <th key={h} className="text-left px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30">
                    {result.amount_mismatch.map((r, i) => (
                      <tr key={i} className="hover:bg-slate-700/20">
                        <td className="px-3 py-2 text-slate-300">{r.date}</td>
                        <td className="px-3 py-2 text-slate-300">{r.model || '—'}</td>
                        <td className="px-3 py-2 text-slate-400">{r.shift || '—'}</td>
                        <td className="px-3 py-2 text-violet-300">{fmt$(r.notion_amount)}</td>
                        <td className="px-3 py-2 text-blue-300">{fmt$(r.db_amount)}</td>
                        <td className="px-3 py-2 font-mono">{fmtDiff(r.diff)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="text-xs text-emerald-400/80">✓ Расхождений сумм нет</p>
          )}

          {/* Notion-only */}
          <div>
            <button
              onClick={() => setShowNotionOnly(o => !o)}
              className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              <span className={`transition-transform ${showNotionOnly ? 'rotate-90' : ''}`}>▶</span>
              Только в Notion ({result.notion_only.length})
              {result.notion_only.length > 0 && <span className="text-amber-400">⚠</span>}
            </button>
            {showNotionOnly && result.notion_only.length > 0 && (
              <div className="mt-2 overflow-x-auto rounded-xl border border-amber-500/20">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-amber-500/10 text-slate-400 text-xs uppercase tracking-wide">
                      {['Дата','Модель','Смена','Сумма','Notion ID'].map(h => (
                        <th key={h} className="text-left px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30">
                    {result.notion_only.map((r, i) => (
                      <tr key={i} className="hover:bg-slate-700/20">
                        <td className="px-3 py-2 text-slate-300">{r.date}</td>
                        <td className="px-3 py-2 text-slate-300">{r.model || '—'}</td>
                        <td className="px-3 py-2 text-slate-400">{r.shift || '—'}</td>
                        <td className="px-3 py-2 text-violet-300">{fmt$(r.amount)}</td>
                        <td className="px-3 py-2 text-slate-600 font-mono text-xs">{(r.notion_id || '').slice(0,8)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* DB-only */}
          <div>
            <button
              onClick={() => setShowDbOnly(o => !o)}
              className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
            >
              <span className={`transition-transform ${showDbOnly ? 'rotate-90' : ''}`}>▶</span>
              Только в БД ({result.db_only.length})
              {result.db_only.length > 0 && <span className="text-amber-400">⚠</span>}
            </button>
            {showDbOnly && result.db_only.length > 0 && (
              <div className="mt-2 overflow-x-auto rounded-xl border border-slate-600/40">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-700/30 text-slate-400 text-xs uppercase tracking-wide">
                      {['Дата','Модель','Сумма','DB ID','Notion ID'].map(h => (
                        <th key={h} className="text-left px-3 py-2">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30">
                    {result.db_only.map((r, i) => (
                      <tr key={i} className="hover:bg-slate-700/20">
                        <td className="px-3 py-2 text-slate-300">{r.date}</td>
                        <td className="px-3 py-2 text-slate-300">{r.model || '—'}</td>
                        <td className="px-3 py-2 text-blue-300">{fmt$(r.amount)}</td>
                        <td className="px-3 py-2 text-slate-500 font-mono text-xs">{r.id}</td>
                        <td className="px-3 py-2 text-slate-600 font-mono text-xs">
                          {r.notion_id ? `${r.notion_id.slice(0,8)}…` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
