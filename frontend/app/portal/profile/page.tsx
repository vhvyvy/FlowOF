'use client'

import { useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { User, Building2, Mail, Camera, Trash2 } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'

interface Profile {
  email: string
  full_name: string
  chatter_name: string
  agency_name: string
  currency: string
  avatar_base64: string | null
}

function initials(name: string) {
  return (name || '?').slice(0, 1).toUpperCase()
}

async function compressToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const size = 256
      const canvas = document.createElement('canvas')
      canvas.width = size
      canvas.height = size
      const ctx = canvas.getContext('2d')!
      // cover-crop to square
      const ratio = Math.min(img.width, img.height)
      const sx = (img.width  - ratio) / 2
      const sy = (img.height - ratio) / 2
      ctx.drawImage(img, sx, sy, ratio, ratio, 0, 0, size, size)
      resolve(canvas.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = reject
    img.src = URL.createObjectURL(file)
  })
}

export default function PortalProfilePage() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview]   = useState<string | null>(null)
  const [saving,  setSaving]    = useState(false)
  const [toast,   setToast]     = useState<string | null>(null)

  const { data, isLoading } = useQuery<Profile>({
    queryKey: ['portal-profile'],
    queryFn: () => api.get<Profile>('/api/v1/me/profile').then(r => r.data),
  })

  const avatarMut = useMutation({
    mutationFn: (b64: string | null) =>
      api.put('/api/v1/me/avatar', { avatar_base64: b64 }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['portal-profile'] })
      setPreview(null)
      setSaving(false)
      showToast(preview ? 'Аватар сохранён' : 'Аватар удалён')
    },
    onError: () => {
      setSaving(false)
      showToast('Ошибка сохранения')
    },
  })

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const b64 = await compressToBase64(file)
      setPreview(b64)
    } catch {
      showToast('Не удалось прочитать файл')
    }
    e.target.value = ''
  }

  async function handleSave() {
    if (!preview) return
    setSaving(true)
    avatarMut.mutate(preview)
  }

  async function handleDelete() {
    setSaving(true)
    avatarMut.mutate(null)
  }

  const displayAvatar = preview || data?.avatar_base64
  const displayName   = data?.full_name || data?.chatter_name || '?'

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900">
        <h1 className="text-lg font-semibold text-slate-100">Профиль</h1>
      </header>

      <div className="flex-1 p-6 space-y-4 overflow-y-auto max-w-lg">
        {/* Toast */}
        {toast && (
          <div className="fixed top-4 right-4 z-50 bg-slate-700 border border-slate-600 text-slate-100 text-sm px-4 py-2 rounded-lg shadow-lg">
            {toast}
          </div>
        )}

        {isLoading ? (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-40" />
          </div>
        ) : data ? (
          <>
            {/* Avatar section */}
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6">
              <p className="text-xs font-medium text-slate-400 uppercase tracking-wide mb-4">Аватарка</p>

              <div className="flex items-center gap-5">
                {/* Avatar circle */}
                <div className="relative">
                  {displayAvatar ? (
                    <img
                      src={displayAvatar}
                      alt="avatar"
                      className="w-20 h-20 rounded-full object-cover ring-2 ring-violet-500/30"
                    />
                  ) : (
                    <div className="w-20 h-20 rounded-full bg-violet-500/20 flex items-center justify-center ring-2 ring-violet-500/20">
                      <span className="text-3xl font-bold text-violet-400">{initials(displayName)}</span>
                    </div>
                  )}
                  {/* Camera overlay */}
                  <button
                    onClick={() => fileRef.current?.click()}
                    className="absolute bottom-0 right-0 w-7 h-7 rounded-full bg-slate-700 border border-slate-600 flex items-center justify-center hover:bg-slate-600 transition-colors"
                  >
                    <Camera className="h-3.5 w-3.5 text-slate-300" />
                  </button>
                </div>

                <div className="flex-1 space-y-2">
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={handleFile}
                  />

                  {preview ? (
                    <div className="flex gap-2">
                      <button
                        onClick={handleSave}
                        disabled={saving}
                        className="flex-1 text-sm py-1.5 bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 rounded-lg transition-colors disabled:opacity-50"
                      >
                        {saving ? 'Сохраняю…' : 'Сохранить'}
                      </button>
                      <button
                        onClick={() => setPreview(null)}
                        disabled={saving}
                        className="text-sm py-1.5 px-3 bg-slate-700/40 hover:bg-slate-700 border border-slate-600/40 text-slate-400 rounded-lg transition-colors"
                      >
                        Отмена
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => fileRef.current?.click()}
                      className="text-sm py-1.5 px-4 bg-slate-700/60 hover:bg-slate-700 border border-slate-600/50 text-slate-300 rounded-lg transition-colors"
                    >
                      Загрузить фото
                    </button>
                  )}

                  {!preview && data.avatar_base64 && (
                    <button
                      onClick={handleDelete}
                      disabled={saving}
                      className="flex items-center gap-1.5 text-xs text-red-400/70 hover:text-red-400 transition-colors disabled:opacity-50"
                    >
                      <Trash2 className="h-3 w-3" />
                      Удалить аватар
                    </button>
                  )}
                  <p className="text-xs text-slate-600">Рекомендуем квадратное фото ≤ 500 КБ</p>
                </div>
              </div>
            </div>

            {/* Info section */}
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-violet-500/20 flex items-center justify-center">
                  <User className="h-5 w-5 text-violet-400" />
                </div>
                <div>
                  <p className="font-semibold text-slate-100">{displayName}</p>
                  <p className="text-xs text-slate-400">Чаттер</p>
                </div>
              </div>
              <div className="pt-2 space-y-3 border-t border-slate-700/40">
                <div className="flex items-center gap-3">
                  <Mail className="h-4 w-4 text-slate-500 shrink-0" />
                  <p className="text-sm text-slate-300">{data.email}</p>
                </div>
                <div className="flex items-center gap-3">
                  <Building2 className="h-4 w-4 text-slate-500 shrink-0" />
                  <p className="text-sm text-slate-300">{data.agency_name}</p>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
