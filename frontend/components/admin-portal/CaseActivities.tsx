'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Loader2,
  MoreVertical,
  X,
  ImagePlus,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatApiError, resolveApiBaseURL } from '@/lib/api'
import { getToken } from '@/lib/auth'
import { cn } from '@/lib/utils'
import {
  type ActivityFiltersState,
  type ActivityItem,
  type ActivityType,
  useActivities,
  useCreateActivity,
  useDeleteActivity,
} from '@/lib/hooks/useCaseActivities'

// ── Config ────────────────────────────────────────────────────────────────────

const TYPE_OPTIONS: { value: ActivityType; label: string }[] = [
  { value: 'review', label: 'Разбор диалога' },
  { value: 'training', label: 'Обучение' },
  { value: 'meeting', label: 'Встреча' },
  { value: 'observation', label: 'Наблюдение' },
  { value: 'note', label: 'Заметка' },
  { value: 'other', label: 'Другое' },
]

const TYPE_LABEL: Record<ActivityType, string> = Object.fromEntries(
  TYPE_OPTIONS.map((o) => [o.value, o.label]),
) as Record<ActivityType, string>

const BADGE_CLASS: Record<ActivityType, string> = {
  review: 'bg-amber-100 text-amber-800',
  training: 'bg-emerald-100 text-emerald-800',
  meeting: 'bg-sky-100 text-sky-800',
  observation: 'bg-violet-100 text-violet-800',
  note: 'bg-slate-100 text-slate-700',
  other: 'bg-neutral-100 text-neutral-700',
}

const MAX_TEXT = 5000
const MAX_FILES = 5
const MAX_BYTES = 5 * 1024 * 1024
const PAGE_SIZE = 50
const DELETE_HOURS = 24

const ACCEPT_MIME = ['image/png', 'image/jpeg', 'image/webp']

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtActivityDate(iso: string): string {
  const d = new Date(iso)
  const date = d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return `${date}, ${time}`
}

function canDeleteActivity(activity: ActivityItem, currentAdminId: number): boolean {
  if (activity.admin.id !== currentAdminId) return false
  const ageMs = Date.now() - new Date(activity.created_at).getTime()
  return ageMs < DELETE_HOURS * 60 * 60 * 1000
}

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({
  message,
  variant = 'info',
  onClose,
}: {
  message: string
  variant?: 'info' | 'error' | 'success'
  onClose?: () => void
}) {
  const styles =
    variant === 'error'
      ? 'bg-red-500/10 border-red-500/30 text-red-300'
      : variant === 'success'
        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
        : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
  return (
    <div className={cn('flex items-start gap-2 border rounded-lg px-3 py-2 text-sm', styles)}>
      {variant === 'error' && <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />}
      {variant === 'success' && <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />}
      <p className="flex-1">{message}</p>
      {onClose && (
        <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}

// ── Auth image thumb ──────────────────────────────────────────────────────────

function ActivityThumb({
  downloadUrl,
  alt,
  onOpen,
}: {
  downloadUrl: string
  alt: string
  onOpen: (blobUrl: string) => void
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    let url: string | null = null
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(false)
      try {
        const base = resolveApiBaseURL()
        const token = getToken()
        const res = await fetch(`${base}${downloadUrl}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!res.ok) throw new Error('fetch failed')
        const blob = await res.blob()
        if (cancelled) return
        url = URL.createObjectURL(blob)
        setBlobUrl(url)
      } catch {
        if (!cancelled) setError(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [downloadUrl])

  return (
    <button
      type="button"
      onClick={() => blobUrl && onOpen(blobUrl)}
      disabled={!blobUrl}
      className="group relative aspect-square rounded-lg overflow-hidden border border-slate-600/60 bg-slate-800/60 hover:border-amber-500/40 transition-colors"
    >
      {loading && <Skeleton className="absolute inset-0 rounded-none" />}
      {error && (
        <span className="absolute inset-0 flex items-center justify-center text-xs text-slate-500">
          Ошибка
        </span>
      )}
      {blobUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={blobUrl} alt={alt} className="w-full h-full object-cover" />
      )}
    </button>
  )
}

// ── Lightbox ──────────────────────────────────────────────────────────────────

function Lightbox({ src, onClose }: { src: string; onClose: () => void }) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
      role="presentation"
    >
      <button
        type="button"
        className="absolute top-4 right-4 text-slate-300 hover:text-white"
        onClick={onClose}
      >
        <X className="h-8 w-8" />
      </button>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  )
}

// ── Activity card ───────────────────────────────────────────────────────────

function ActivityCard({
  activity,
  currentAdminId,
  onDelete,
  readOnly = false,
}: {
  activity: ActivityItem
  currentAdminId: number
  onDelete: (id: number) => void
  readOnly?: boolean
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const showMenu = !readOnly && canDeleteActivity(activity, currentAdminId)

  useEffect(() => {
    if (!menuOpen) return
    function close(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  const type = activity.activity_type as ActivityType

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 mt-3">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'text-xs font-medium px-2 py-0.5 rounded-full',
                BADGE_CLASS[type] ?? BADGE_CLASS.other,
              )}
            >
              {TYPE_LABEL[type] ?? activity.activity_type}
            </span>
            <span className="text-xs text-slate-500 ml-auto">
              {fmtActivityDate(activity.created_at)}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-1">{activity.admin.name}</p>
        </div>
        {showMenu && (
          <div className="relative shrink-0" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
              aria-label="Меню"
            >
              <MoreVertical className="h-4 w-4" />
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-full mt-1 z-20 min-w-[140px] rounded-lg border border-slate-600 bg-slate-900 shadow-xl py-1">
                <button
                  type="button"
                  className="w-full text-left px-3 py-2 text-sm text-red-400 hover:bg-slate-800"
                  onClick={() => {
                    setMenuOpen(false)
                    setConfirmOpen(true)
                  }}
                >
                  Удалить
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      <p className="text-sm text-slate-200 mt-3 whitespace-pre-wrap">{activity.text}</p>

      {activity.files.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
          {activity.files.map((f) => (
            <div key={f.id} className="min-w-0">
              <ActivityThumb
                downloadUrl={f.download_url}
                alt={f.original_name ?? 'screenshot'}
                onOpen={setLightboxSrc}
              />
              <p className="text-[10px] text-slate-500 mt-1 truncate" title={f.original_name ?? ''}>
                {f.original_name ?? 'file'}
              </p>
            </div>
          ))}
        </div>
      )}

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl p-5 max-w-sm w-full shadow-2xl">
            <p className="text-sm text-slate-200">Удалить эту активность? Действие необратимо.</p>
            <div className="flex gap-2 mt-4 justify-end">
              <Button variant="outline" size="sm" onClick={() => setConfirmOpen(false)}>
                Отмена
              </Button>
              <Button
                size="sm"
                className="bg-red-700 hover:bg-red-600"
                onClick={() => {
                  setConfirmOpen(false)
                  onDelete(activity.id)
                }}
              >
                Удалить
              </Button>
            </div>
          </div>
        </div>
      )}

      {lightboxSrc && <Lightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />}
    </div>
  )
}

// ── Create form ───────────────────────────────────────────────────────────────

interface PendingFile {
  file: File
  preview: string
}

function CreateActivityForm({
  caseId,
  onSuccess,
  onToast,
}: {
  caseId: number
  onSuccess: () => void
  onToast: (msg: string, variant?: 'info' | 'error' | 'success') => void
}) {
  const [activityType, setActivityType] = useState<ActivityType>('note')
  const [text, setText] = useState('')
  const [pending, setPending] = useState<PendingFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const createMut = useCreateActivity(caseId)

  const trimmed = text.trim()
  const textOk = trimmed.length >= 1 && trimmed.length <= MAX_TEXT

  const validateFile = useCallback((file: File): string | null => {
    if (!file.type.startsWith('image/') || !ACCEPT_MIME.includes(file.type)) {
      return `«${file.name}»: допустимы только PNG, JPEG, WebP`
    }
    if (file.size > MAX_BYTES) {
      return `«${file.name}»: размер превышает 5 МБ`
    }
    if (file.size === 0) {
      return `«${file.name}»: пустой файл`
    }
    return null
  }, [])

  function addFiles(fileList: FileList | null) {
    if (!fileList?.length) return
    const incoming = Array.from(fileList)
    if (pending.length + incoming.length > MAX_FILES) {
      onToast('Не более 5 файлов', 'error')
      return
    }
    for (const f of incoming) {
      const err = validateFile(f)
      if (err) {
        onToast(err, 'error')
        return
      }
    }
    const next = incoming.map((file) => ({
      file,
      preview: URL.createObjectURL(file),
    }))
    setPending((prev) => [...prev, ...next])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removePending(idx: number) {
    setPending((prev) => {
      const copy = [...prev]
      URL.revokeObjectURL(copy[idx].preview)
      copy.splice(idx, 1)
      return copy
    })
  }

  useEffect(() => {
    return () => {
      pending.forEach((p) => URL.revokeObjectURL(p.preview))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!textOk || createMut.isPending) return
    try {
      await createMut.mutateAsync({
        activity_type: activityType,
        text: trimmed,
        files: pending.map((p) => p.file),
      })
      setText('')
      setActivityType('note')
      pending.forEach((p) => URL.revokeObjectURL(p.preview))
      setPending([])
      onToast('Активность добавлена', 'success')
      onSuccess()
    } catch (err: unknown) {
      const ax = err as { response?: { status?: number; data?: { detail?: string } } }
      const status = ax.response?.status
      const detail = ax.response?.data?.detail
      if (status === 422 && typeof detail === 'string') onToast(detail, 'error')
      else if (status === 403) onToast('Нет прав', 'error')
      else onToast('Что-то пошло не так, попробуйте ещё раз', 'error')
    }
  }

  const disabled = !textOk || createMut.isPending

  return (
    <form onSubmit={submit} className="space-y-3 border border-slate-700/40 rounded-xl p-4 bg-slate-800/20">
      <div>
        <label className="text-xs text-slate-400 block mb-1">Тип активности</label>
        <select
          value={activityType}
          onChange={(e) => setActivityType(e.target.value as ActivityType)}
          disabled={createMut.isPending}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-amber-500"
        >
          {TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="relative">
        <label className="text-xs text-slate-400 block mb-1">Описание</label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="Что произошло?"
          disabled={createMut.isPending}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-none"
        />
        <span className="absolute bottom-2 right-2 text-xs text-slate-500">
          {trimmed.length} / {MAX_TEXT}
        </span>
      </div>

      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          className="hidden"
          disabled={createMut.isPending}
          onChange={(e) => addFiles(e.target.files)}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={createMut.isPending || pending.length >= MAX_FILES}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-amber-400 transition-colors disabled:opacity-50"
        >
          <ImagePlus className="h-4 w-4" />
          Прикрепить скриншоты ({pending.length}/{MAX_FILES})
        </button>
        {pending.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {pending.map((p, i) => (
              <div key={p.preview} className="relative w-16 h-16 rounded-lg overflow-hidden border border-slate-600">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.preview} alt="" className="w-full h-full object-cover" />
                <button
                  type="button"
                  onClick={() => removePending(i)}
                  className="absolute top-0.5 right-0.5 bg-black/60 rounded-full p-0.5 text-white hover:bg-black/80"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <Button
        type="submit"
        disabled={disabled}
        className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50"
      >
        {createMut.isPending ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            Сохранение…
          </>
        ) : (
          'Добавить активность'
        )}
      </Button>
    </form>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export interface CaseActivitiesProps {
  caseId: number
  currentAdminId: number
  caseOwnerAdminId: number
  readOnly?: boolean
  apiMode?: 'admin' | 'owner'
}

export default function CaseActivities({
  caseId,
  currentAdminId,
  caseOwnerAdminId,
  readOnly = false,
  apiMode = 'admin',
}: CaseActivitiesProps) {
  const isOwner = !readOnly && currentAdminId === caseOwnerAdminId

  const [selectedTypes, setSelectedTypes] = useState<ActivityType[]>([])
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [onlyWithScreens, setOnlyWithScreens] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebounce(searchInput, 400)

  const [offset, setOffset] = useState(0)
  const [accumulated, setAccumulated] = useState<ActivityItem[]>([])
  const [total, setTotal] = useState(0)

  const [toast, setToast] = useState<{ msg: string; variant: 'info' | 'error' | 'success' } | null>(null)

  const filterKey = useMemo(
    () =>
      JSON.stringify({
        selectedTypes,
        dateFrom,
        dateTo,
        onlyWithScreens,
        debouncedSearch,
      }),
    [selectedTypes, dateFrom, dateTo, onlyWithScreens, debouncedSearch],
  )

  useEffect(() => {
    setOffset(0)
    setAccumulated([])
  }, [filterKey, caseId])

  const queryFilters: ActivityFiltersState = useMemo(
    () => ({
      activity_type: selectedTypes.length ? selectedTypes : undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      has_files: onlyWithScreens ? true : undefined,
      text_search: debouncedSearch || undefined,
      limit: PAGE_SIZE,
      offset,
    }),
    [selectedTypes, dateFrom, dateTo, onlyWithScreens, debouncedSearch, offset],
  )

  const { data, isLoading, isFetching, refetch } = useActivities(caseId, queryFilters, apiMode)
  const deleteMut = useDeleteActivity(caseId)

  useEffect(() => {
    if (!data) return
    setTotal(data.total)
    if (offset === 0) setAccumulated(data.items)
    else setAccumulated((prev) => [...prev, ...data.items])
  }, [data, offset])

  function toggleType(t: ActivityType) {
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    )
  }

  async function handleDelete(activityId: number) {
    try {
      await deleteMut.mutateAsync(activityId)
      setToast({ msg: 'Активность удалена', variant: 'success' })
      setOffset(0)
      refetch()
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        setToast({ msg: 'Срок для удаления истёк', variant: 'error' })
      } else {
        setToast({ msg: formatApiError(err), variant: 'error' })
      }
    }
  }

  const hasMore = accumulated.length < total
  const filtersActive =
    selectedTypes.length > 0 || dateFrom || dateTo || onlyWithScreens || debouncedSearch

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5 space-y-4">
      <div>
        <h3 className="text-base font-semibold text-slate-100">Активности</h3>
        <p className="text-xs text-slate-500 mt-0.5">
          {isLoading && offset === 0 ? 'Загрузка…' : `${total} активностей`}
        </p>
        {readOnly && (
          <p className="text-xs text-slate-500 mt-1">Только просмотр</p>
        )}
      </div>

      {toast && (
        <Toast
          message={toast.msg}
          variant={toast.variant}
          onClose={() => setToast(null)}
        />
      )}

      {isOwner ? (
        <CreateActivityForm
          caseId={caseId}
          onSuccess={() => {
            setOffset(0)
            refetch()
          }}
          onToast={(msg, variant) => setToast({ msg, variant: variant ?? 'info' })}
        />
      ) : (
        <div className="text-xs text-slate-400 bg-slate-800/50 border border-slate-700/40 rounded-lg px-3 py-2">
          Только автор кейса может добавлять активности
        </div>
      )}

      {/* Filters */}
      <div className="space-y-3 pt-1">
        <div className="flex flex-wrap gap-2 items-center">
          {TYPE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => toggleType(o.value)}
              className={cn(
                'text-xs px-2.5 py-1 rounded-full border transition-colors',
                selectedTypes.includes(o.value)
                  ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                  : 'border-slate-600 text-slate-400 hover:border-slate-500',
              )}
            >
              {o.label}
            </button>
          ))}
          {filtersActive && (
            <button
              type="button"
              onClick={() => {
                setSelectedTypes([])
                setDateFrom('')
                setDateTo('')
                setOnlyWithScreens(false)
                setSearchInput('')
              }}
              className="text-xs text-slate-500 hover:text-amber-400 underline"
            >
              Сбросить
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-[10px] text-slate-500 block">С</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-200"
            />
          </div>
          <div>
            <label className="text-[10px] text-slate-500 block">По</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-slate-200"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={onlyWithScreens}
              onChange={(e) => setOnlyWithScreens(e.target.checked)}
              className="rounded border-slate-600"
            />
            Только со скринами
          </label>
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Поиск по тексту…"
            className="flex-1 min-w-[160px] bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-500"
          />
        </div>
      </div>

      {/* Feed */}
      {isLoading && offset === 0 ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
        </div>
      ) : accumulated.length === 0 ? (
        <p className="text-sm text-slate-500 text-center py-8">
          Пока нет активностей по этому кейсу
        </p>
      ) : (
        <>
          {accumulated.map((a) => (
            <ActivityCard
              key={a.id}
              activity={a}
              currentAdminId={currentAdminId}
              onDelete={handleDelete}
              readOnly={readOnly}
            />
          ))}
          {hasMore && (
            <div className="pt-2 text-center">
              <Button
                variant="outline"
                size="sm"
                disabled={isFetching}
                onClick={() => setOffset(accumulated.length)}
                className="text-slate-300"
              >
                {isFetching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  'Показать ещё'
                )}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
