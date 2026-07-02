'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Header } from '@/components/layout/Header'
import { Button } from '@/components/ui/button'
import {
  Brain,
  Save,
  Loader2,
  ChevronDown,
  ChevronRight,
  Info,
  CheckCircle,
} from 'lucide-react'
import api from '@/lib/api'

// ── Types ──────────────────────────────────────────────────────────────────

interface AgencyProfile {
  tenant_id: number
  rpc_critical: number
  rpc_working_low: number
  rpc_strong: number
  open_rate_critical: number
  open_rate_working: number
  open_rate_strong: number
  priorities: string | null
  glossary: string | null
  target_notes: string | null
  auto_context: string | null
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
      {children}
    </h3>
  )
}

function FieldRow({
  label,
  hint,
  value,
  onChange,
  prefix = '',
  suffix = '',
  step = '0.01',
}: {
  label: string
  hint: string
  value: number | string
  onChange: (v: string) => void
  prefix?: string
  suffix?: string
  step?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-300 mb-1">{label}</label>
      <p className="text-xs text-slate-500 mb-2">{hint}</p>
      <div className="relative flex items-center">
        {prefix && (
          <span className="absolute left-3 text-slate-400 text-sm select-none">{prefix}</span>
        )}
        <input
          type="number"
          step={step}
          min={0}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full h-9 rounded-lg border border-slate-600 bg-slate-800 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
            prefix ? 'pl-7 pr-4' : 'px-4'
          } ${suffix ? 'pr-10' : ''}`}
        />
        {suffix && (
          <span className="absolute right-3 text-slate-400 text-sm select-none">{suffix}</span>
        )}
      </div>
    </div>
  )
}

function TextAreaRow({
  label,
  hint,
  value,
  onChange,
  placeholder,
}: {
  label: string
  hint: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-300 mb-1">{label}</label>
      <p className="text-xs text-slate-500 mb-2">{hint}</p>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={3}
        className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
      />
    </div>
  )
}

// ── Auto context block ─────────────────────────────────────────────────────

function AutoContextBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const lines = text.split('\n').filter(Boolean)

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Info className="h-4 w-4 text-indigo-400 shrink-0" />
          <span className="text-sm font-medium text-slate-300">
            Что мозг знает автоматически
          </span>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-slate-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-slate-700/50 pt-3">
          <div className="space-y-1.5">
            {lines.map((line, i) => (
              <p key={i} className={`text-xs ${i === 0 ? 'text-slate-400 font-semibold' : 'text-slate-500'}`}>
                {line}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function AgencyProfilePage() {
  const [profile, setProfile] = useState<AgencyProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Form state
  const [rpcCritical, setRpcCritical]     = useState('0.15')
  const [rpcWorking, setRpcWorking]       = useState('0.25')
  const [rpcStrong, setRpcStrong]         = useState('0.50')
  const [orCritical, setOrCritical]       = useState('20')
  const [orWorking, setOrWorking]         = useState('25')
  const [orStrong, setOrStrong]           = useState('35')
  const [priorities, setPriorities]       = useState('')
  const [glossary, setGlossary]           = useState('')
  const [targetNotes, setTargetNotes]     = useState('')

  useEffect(() => {
    api.get<AgencyProfile>('/api/v1/agency-profile').then((r) => {
      const p = r.data
      setProfile(p)
      setRpcCritical(String(p.rpc_critical))
      setRpcWorking(String(p.rpc_working_low))
      setRpcStrong(String(p.rpc_strong))
      setOrCritical(String(p.open_rate_critical))
      setOrWorking(String(p.open_rate_working))
      setOrStrong(String(p.open_rate_strong))
      setPriorities(p.priorities ?? '')
      setGlossary(p.glossary ?? '')
      setTargetNotes(p.target_notes ?? '')
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    try {
      await api.put('/api/v1/agency-profile', {
        rpc_critical:       parseFloat(rpcCritical) || 0.15,
        rpc_working_low:    parseFloat(rpcWorking)  || 0.25,
        rpc_strong:         parseFloat(rpcStrong)   || 0.50,
        open_rate_critical: parseFloat(orCritical)  || 20,
        open_rate_working:  parseFloat(orWorking)   || 25,
        open_rate_strong:   parseFloat(orStrong)    || 35,
        priorities:   priorities.trim() || null,
        glossary:     glossary.trim()   || null,
        target_notes: targetNotes.trim()|| null,
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { /* ignore */ } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Настройки мозга" />

      {/* Sub-nav */}
      <div className="flex gap-1 px-6 pt-3 pb-0 border-b border-slate-700/50">
        <Link
          href="/dashboard/ai"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          Чат
        </Link>
        <Link
          href="/dashboard/ai/events"
          className="px-3 py-1.5 text-sm font-medium text-slate-400 hover:text-slate-200 -mb-px transition-colors"
        >
          События
        </Link>
        <span className="px-3 py-1.5 text-sm font-medium text-indigo-300 border-b-2 border-indigo-400 -mb-px">
          Настройки
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading ? (
          <div className="flex items-center gap-2 text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="text-sm">Загрузка…</span>
          </div>
        ) : (
          <div className="max-w-2xl space-y-8">

            {/* Auto context (collapsed by default) */}
            {profile?.auto_context && (
              <AutoContextBlock text={profile.auto_context} />
            )}

            {/* RPC thresholds */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
              <SectionTitle>
                <Brain className="h-3.5 w-3.5 text-indigo-400" />
                Пороги RPC (Revenue per Chat)
              </SectionTitle>
              <p className="text-xs text-slate-500 -mt-2">
                Мозг использует эти значения при оценке эффективности чаттеров.
              </p>
              <div className="grid grid-cols-3 gap-4">
                <FieldRow
                  label="Критично"
                  hint="Ниже этого — тревога"
                  prefix="$"
                  value={rpcCritical}
                  onChange={setRpcCritical}
                />
                <FieldRow
                  label="Рабочий уровень"
                  hint="Норм, но можно лучше"
                  prefix="$"
                  value={rpcWorking}
                  onChange={setRpcWorking}
                />
                <FieldRow
                  label="Сильный"
                  hint="Хорошо — выше этого"
                  prefix="$"
                  value={rpcStrong}
                  onChange={setRpcStrong}
                />
              </div>
            </div>

            {/* Open Rate thresholds */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-4">
              <SectionTitle>
                <Brain className="h-3.5 w-3.5 text-indigo-400" />
                Пороги Open Rate (PPV открываемость)
              </SectionTitle>
              <p className="text-xs text-slate-500 -mt-2">
                Процент подписчиков, открывших PPV-сообщение.
              </p>
              <div className="grid grid-cols-3 gap-4">
                <FieldRow
                  label="Критично"
                  hint="Ниже — тревога"
                  suffix="%"
                  step="1"
                  value={orCritical}
                  onChange={setOrCritical}
                />
                <FieldRow
                  label="Рабочий уровень"
                  hint="Норм, но можно лучше"
                  suffix="%"
                  step="1"
                  value={orWorking}
                  onChange={setOrWorking}
                />
                <FieldRow
                  label="Сильный"
                  hint="Хорошо — выше этого"
                  suffix="%"
                  step="1"
                  value={orStrong}
                  onChange={setOrStrong}
                />
              </div>
            </div>

            {/* Priorities, glossary, goals */}
            <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5 space-y-5">
              <SectionTitle>
                <Brain className="h-3.5 w-3.5 text-indigo-400" />
                Контекст для мозга
              </SectionTitle>

              <TextAreaRow
                label="Приоритеты агентства"
                hint="Мозг будет учитывать их при рекомендациях"
                value={priorities}
                onChange={setPriorities}
                placeholder="Напр.: «Фокус на удержании платников, а не на объёме чатов. Важен RPC, а не число транзакций»"
              />

              <TextAreaRow
                label="Заметки / глоссарий для мозга"
                hint="Что мозгу полезно знать про твоё агентство, внутренние термины"
                value={glossary}
                onChange={setGlossary}
                placeholder="Напр.: «VIP = платники с MRR > $50. Пик — вечерняя смена 20:00–01:00»"
              />

              <TextAreaRow
                label="Цели"
                hint="Что для тебя «хорошо»: цели на месяц/квартал, к чему стремиться"
                value={targetNotes}
                onChange={setTargetNotes}
                placeholder="Напр.: «Вырасти до $30k/мес к Q4. Добавить 2 новых модели. Удержать RPC > $0.40»"
              />
            </div>

            {/* Save button */}
            <div className="flex items-center gap-3">
              <Button onClick={handleSave} disabled={saving} className="gap-2">
                {saving ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : saved ? (
                  <CheckCircle className="h-4 w-4 text-emerald-400" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                {saving ? 'Сохраняю…' : saved ? 'Сохранено!' : 'Сохранить'}
              </Button>
              {saved && (
                <p className="text-sm text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle className="h-3.5 w-3.5" />
                  Паспорт агентства обновлён — мозг уже учитывает изменения
                </p>
              )}
            </div>

          </div>
        )}
      </div>
    </div>
  )
}
