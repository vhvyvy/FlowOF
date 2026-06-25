'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, Search, Folder, FolderOpen, FileText,
  Copy, Edit2, Trash2, MoreHorizontal, X, Check,
  ArrowDownUp,
} from 'lucide-react'
import api from '@/lib/api'

// ─── Types ───────────────────────────────────────────────────────────────────

interface ScriptFolder {
  id: number
  name: string
  sort_order: number
  script_count: number
}

interface Script {
  id: number
  folder_id: number | null
  folder_name: string | null
  title: string
  content: string
  tags: string | null
  copy_count: number
  created_at: string
}

// ─── Small helpers ────────────────────────────────────────────────────────────

function TagPill({ tag }: { tag: string }) {
  return (
    <span className="inline-block px-1.5 py-0.5 text-[10px] bg-violet-500/15 text-violet-300 rounded">
      {tag.trim()}
    </span>
  )
}

// ─── Script Card ─────────────────────────────────────────────────────────────

function ScriptCard({
  script,
  onOpen,
}: {
  script: Script
  onOpen: (s: Script) => void
}) {
  const tags = (script.tags || '').split(',').filter(Boolean)
  return (
    <div
      onClick={() => onOpen(script)}
      className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 cursor-pointer hover:border-violet-500/40 hover:bg-slate-800/80 transition-all group"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm font-semibold text-slate-100 line-clamp-1">{script.title}</p>
        <FileText className="h-3.5 w-3.5 text-slate-500 shrink-0 mt-0.5" />
      </div>
      <p className="text-xs text-slate-400 line-clamp-3 leading-relaxed mb-3">
        {script.content.slice(0, 120)}{script.content.length > 120 ? '…' : ''}
      </p>
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {tags.slice(0, 3).map((t, i) => <TagPill key={i} tag={t} />)}
        </div>
        {script.copy_count > 0 && (
          <span className="text-[10px] text-slate-500 shrink-0 flex items-center gap-0.5">
            <Copy className="h-2.5 w-2.5" />{script.copy_count}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Script Modal ─────────────────────────────────────────────────────────────

function ScriptModal({
  script,
  onClose,
  onEdit,
  onDelete,
}: {
  script: Script
  onClose: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const qc = useQueryClient()
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(script.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      await api.post(`/api/v1/me/scripts/${script.id}/copy`)
      qc.invalidateQueries({ queryKey: ['scripts'] })
    } catch { /* ignore */ }
  }

  const tags = (script.tags || '').split(',').filter(Boolean)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="w-full max-w-lg bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-slate-700/50">
          <div className="flex-1 min-w-0">
            <p className="text-base font-semibold text-slate-100 break-words">{script.title}</p>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {tags.map((t, i) => <TagPill key={i} tag={t} />)}
              </div>
            )}
          </div>
          <button onClick={onClose} className="ml-3 text-slate-500 hover:text-slate-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <pre className="text-sm text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">
            {script.content}
          </pre>
        </div>

        {/* Actions */}
        <div className="px-5 py-4 border-t border-slate-700/50 flex gap-2">
          <button
            onClick={handleCopy}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-sm font-semibold rounded-xl transition-colors"
          >
            {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            {copied ? 'Скопировано!' : 'Копировать'}
          </button>
          <button
            onClick={onEdit}
            className="px-4 py-2.5 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/40 text-slate-300 text-sm rounded-xl transition-colors"
          >
            <Edit2 className="h-4 w-4" />
          </button>
          <button
            onClick={onDelete}
            className="px-4 py-2.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400 text-sm rounded-xl transition-colors"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Script Form Modal ────────────────────────────────────────────────────────

function ScriptFormModal({
  initial,
  folders,
  defaultFolderId,
  onClose,
  onSave,
}: {
  initial?: Script
  folders: ScriptFolder[]
  defaultFolderId: number | null
  onClose: () => void
  onSave: (data: { folder_id: number | null; title: string; content: string; tags: string }) => void
}) {
  const [title,    setTitle]    = useState(initial?.title    || '')
  const [content,  setContent]  = useState(initial?.content  || '')
  const [tags,     setTags]     = useState(initial?.tags     || '')
  const [folderId, setFolderId] = useState<number | null>(
    initial ? initial.folder_id : defaultFolderId
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="w-full max-w-lg bg-slate-800 border border-slate-700/60 rounded-2xl shadow-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <p className="text-base font-semibold text-slate-100">
            {initial ? 'Редактировать скрипт' : 'Новый скрипт'}
          </p>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Название</label>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="Название скрипта"
              className="w-full text-sm bg-slate-700/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Папка</label>
            <select
              value={folderId ?? ''}
              onChange={e => setFolderId(e.target.value === '' ? null : parseInt(e.target.value))}
              className="w-full text-sm bg-slate-700/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-violet-500/50"
            >
              <option value="">Без папки</option>
              {folders.map(f => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Текст скрипта</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
              placeholder="Текст скрипта…"
              className="w-full text-sm bg-slate-700/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50 resize-none font-mono leading-relaxed"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">Теги (через запятую)</label>
            <input
              value={tags}
              onChange={e => setTags(e.target.value)}
              placeholder="привет, отказ, ppv"
              className="w-full text-sm bg-slate-700/60 border border-slate-600/40 rounded-lg px-3 py-2 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50"
            />
          </div>
        </div>

        <div className="px-5 py-4 border-t border-slate-700/50 flex gap-2">
          <button
            onClick={() => onSave({ folder_id: folderId, title: title.trim(), content, tags })}
            disabled={!title.trim() || !content.trim()}
            className="flex-1 py-2.5 bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-sm font-semibold rounded-xl transition-colors disabled:opacity-40"
          >
            Сохранить
          </button>
          <button
            onClick={onClose}
            className="px-5 py-2.5 bg-slate-700/40 hover:bg-slate-700 border border-slate-600/30 text-slate-400 text-sm rounded-xl transition-colors"
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type FolderFilter = number | 'all' | 'none'

export default function ScriptsPage() {
  const qc = useQueryClient()
  const [selectedFolder, setSelectedFolder] = useState<FolderFilter>('all')
  const [search,         setSearch]          = useState('')
  const [sort,           setSort]            = useState<'date' | 'popular'>('date')
  const [openScript,     setOpenScript]      = useState<Script | null>(null)
  const [editScript,     setEditScript]      = useState<Script | null>(null)
  const [showNewScript,  setShowNewScript]   = useState(false)
  const [editFolderRow,  setEditFolderRow]   = useState<number | null>(null)
  const [newFolderName,  setNewFolderName]   = useState('')
  const [showNewFolder,  setShowNewFolder]   = useState(false)
  const [folderMenu,     setFolderMenu]      = useState<number | null>(null)
  const [toast,          setToast]           = useState<string | null>(null)
  const folderMenuRef = useRef<HTMLDivElement>(null)

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2000)
  }

  // Close folder menu on outside click
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (folderMenuRef.current && !folderMenuRef.current.contains(e.target as Node)) {
        setFolderMenu(null)
      }
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  // ── Queries ────────────────────────────────────────────────────────────────

  const { data: foldersData } = useQuery<{ folders: ScriptFolder[] }>({
    queryKey: ['script-folders'],
    queryFn: () => api.get('/api/v1/me/scripts/folders').then(r => r.data),
  })
  const folders = foldersData?.folders ?? []

  const queryParams = new URLSearchParams()
  if (selectedFolder === 'none') queryParams.set('folder_id', '0')
  else if (typeof selectedFolder === 'number') queryParams.set('folder_id', String(selectedFolder))
  if (search) queryParams.set('search', search)
  queryParams.set('sort', sort)

  const { data: scriptsData, isLoading: loadingScripts } = useQuery<{ scripts: Script[] }>({
    queryKey: ['scripts', selectedFolder, search, sort],
    queryFn: () => api.get(`/api/v1/me/scripts?${queryParams}`).then(r => r.data),
  })
  const scripts = scriptsData?.scripts ?? []

  // ── Mutations ──────────────────────────────────────────────────────────────

  const createFolder = useMutation({
    mutationFn: (name: string) => api.post('/api/v1/me/scripts/folders', { name }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['script-folders'] }); setShowNewFolder(false); setNewFolderName('') },
  })

  const renameFolder = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) =>
      api.put(`/api/v1/me/scripts/folders/${id}`, { name }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['script-folders'] }); setEditFolderRow(null) },
  })

  const deleteFolder = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/me/scripts/folders/${id}`).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['script-folders'] })
      qc.invalidateQueries({ queryKey: ['scripts'] })
      if (selectedFolder === folderMenu) setSelectedFolder('all')
      setFolderMenu(null)
    },
  })

  const createScript = useMutation({
    mutationFn: (data: object) => api.post('/api/v1/me/scripts', data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['scripts'] }); setShowNewScript(false); showToast('Скрипт создан') },
  })

  const updateScript = useMutation({
    mutationFn: ({ id, ...data }: { id: number } & object) =>
      api.put(`/api/v1/me/scripts/${id}`, data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['scripts'] }); setEditScript(null); setOpenScript(null); showToast('Сохранено') },
  })

  const deleteScript = useMutation({
    mutationFn: (id: number) => api.delete(`/api/v1/me/scripts/${id}`).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['scripts'] }); setOpenScript(null); showToast('Удалено') },
  })

  // ── Render ─────────────────────────────────────────────────────────────────

  const defaultFolderId = typeof selectedFolder === 'number' ? selectedFolder : null

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900 flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-slate-100 shrink-0">Скрипты</h1>
        {/* Search */}
        <div className="flex-1 max-w-sm relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск по всем скриптам…"
            className="w-full pl-8 pr-3 py-1.5 text-sm bg-slate-800 border border-slate-700/50 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500/50"
          />
        </div>
        {/* Sort */}
        <button
          onClick={() => setSort(s => s === 'date' ? 'popular' : 'date')}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors shrink-0"
        >
          <ArrowDownUp className="h-3.5 w-3.5" />
          {sort === 'date' ? 'По дате' : 'По попул.'}
        </button>
      </header>

      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-700 border border-slate-600 text-slate-100 text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* ── Left: Folders ── */}
        <aside className="w-56 shrink-0 border-r border-slate-700/50 bg-slate-900 flex flex-col overflow-y-auto">
          <div className="px-3 py-3 space-y-0.5">
            {/* All */}
            {[
              { key: 'all' as FolderFilter, label: 'Все скрипты', count: null },
              { key: 'none' as FolderFilter, label: 'Без папки',   count: null },
            ].map(({ key, label }) => (
              <button
                key={String(key)}
                onClick={() => setSelectedFolder(key)}
                className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
                  selectedFolder === key
                    ? 'bg-violet-500/15 text-violet-300'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {selectedFolder === key
                  ? <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                  : <Folder className="h-3.5 w-3.5 shrink-0" />
                }
                <span className="flex-1 truncate">{label}</span>
              </button>
            ))}

            {/* Divider */}
            {folders.length > 0 && <div className="border-t border-slate-700/40 my-1.5" />}

            {/* Folder list */}
            {folders.map(f => (
              <div key={f.id} className="relative group">
                {editFolderRow === f.id ? (
                  <form
                    onSubmit={e => { e.preventDefault(); renameFolder.mutate({ id: f.id, name: newFolderName }) }}
                    className="flex gap-1 px-1"
                  >
                    <input
                      autoFocus
                      value={newFolderName}
                      onChange={e => setNewFolderName(e.target.value)}
                      className="flex-1 text-xs bg-slate-700 border border-violet-500/40 rounded px-2 py-1 text-slate-200 focus:outline-none"
                    />
                    <button type="submit" className="text-emerald-400 hover:text-emerald-300"><Check className="h-3.5 w-3.5" /></button>
                    <button type="button" onClick={() => setEditFolderRow(null)} className="text-slate-500 hover:text-slate-300"><X className="h-3.5 w-3.5" /></button>
                  </form>
                ) : (
                  <button
                    onClick={() => setSelectedFolder(f.id)}
                    className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
                      selectedFolder === f.id
                        ? 'bg-violet-500/15 text-violet-300'
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                    }`}
                  >
                    {selectedFolder === f.id
                      ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-violet-400" />
                      : <Folder className="h-3.5 w-3.5 shrink-0" />
                    }
                    <span className="flex-1 truncate">{f.name}</span>
                    <span className="text-[10px] text-slate-600">{f.script_count}</span>
                    <button
                      onClick={e => { e.stopPropagation(); setFolderMenu(folderMenu === f.id ? null : f.id) }}
                      className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-500 hover:text-slate-300"
                    >
                      <MoreHorizontal className="h-3.5 w-3.5" />
                    </button>
                  </button>
                )}
                {/* Folder context menu */}
                {folderMenu === f.id && (
                  <div
                    ref={folderMenuRef}
                    className="absolute right-0 top-8 z-20 w-36 bg-slate-800 border border-slate-700/60 rounded-lg shadow-xl py-1"
                  >
                    <button
                      onClick={() => { setEditFolderRow(f.id); setNewFolderName(f.name); setFolderMenu(null) }}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700/60"
                    >
                      <Edit2 className="h-3 w-3" />Переименовать
                    </button>
                    <button
                      onClick={() => { if (confirm(`Удалить папку "${f.name}"?`)) deleteFolder.mutate(f.id) }}
                      className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-400 hover:bg-slate-700/60"
                    >
                      <Trash2 className="h-3 w-3" />Удалить
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* New folder */}
          <div className="px-3 pb-3 mt-auto">
            {showNewFolder ? (
              <form
                onSubmit={e => { e.preventDefault(); if (newFolderName.trim()) createFolder.mutate(newFolderName.trim()) }}
                className="flex gap-1"
              >
                <input
                  autoFocus
                  value={newFolderName}
                  onChange={e => setNewFolderName(e.target.value)}
                  placeholder="Имя папки"
                  className="flex-1 text-xs bg-slate-700 border border-violet-500/40 rounded px-2 py-1.5 text-slate-200 placeholder-slate-500 focus:outline-none"
                />
                <button type="submit" className="text-emerald-400 hover:text-emerald-300"><Check className="h-4 w-4" /></button>
                <button type="button" onClick={() => { setShowNewFolder(false); setNewFolderName('') }} className="text-slate-500"><X className="h-4 w-4" /></button>
              </form>
            ) : (
              <button
                onClick={() => setShowNewFolder(true)}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />Папка
              </button>
            )}
          </div>
        </aside>

        {/* ── Right: Scripts ── */}
        <main className="flex-1 overflow-y-auto p-5">
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-slate-400">
              {scripts.length} скриптов
            </p>
            <button
              onClick={() => setShowNewScript(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-sm rounded-lg transition-colors"
            >
              <Plus className="h-4 w-4" />
              Новый скрипт
            </button>
          </div>

          {loadingScripts ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="bg-slate-800/40 border border-slate-700/30 rounded-xl p-4 h-32 animate-pulse" />
              ))}
            </div>
          ) : scripts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <FileText className="h-10 w-10 text-slate-700 mb-3" />
              <p className="text-slate-500 text-sm">
                {search ? 'Ничего не найдено' : 'Скриптов пока нет'}
              </p>
              {!search && (
                <button
                  onClick={() => setShowNewScript(true)}
                  className="mt-3 text-xs text-violet-400 hover:text-violet-300"
                >
                  + Создать первый скрипт
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {scripts.map(s => (
                <ScriptCard key={s.id} script={s} onOpen={setOpenScript} />
              ))}
            </div>
          )}
        </main>
      </div>

      {/* ── Script View Modal ── */}
      {openScript && !editScript && (
        <ScriptModal
          script={openScript}
          onClose={() => setOpenScript(null)}
          onEdit={() => setEditScript(openScript)}
          onDelete={() => { if (confirm('Удалить скрипт?')) deleteScript.mutate(openScript.id) }}
        />
      )}

      {/* ── Script Form Modal (create) ── */}
      {showNewScript && (
        <ScriptFormModal
          folders={folders}
          defaultFolderId={defaultFolderId}
          onClose={() => setShowNewScript(false)}
          onSave={data => createScript.mutate(data)}
        />
      )}

      {/* ── Script Form Modal (edit) ── */}
      {editScript && (
        <ScriptFormModal
          initial={editScript}
          folders={folders}
          defaultFolderId={editScript.folder_id}
          onClose={() => setEditScript(null)}
          onSave={data => updateScript.mutate({ id: editScript.id, ...data })}
        />
      )}
    </div>
  )
}
