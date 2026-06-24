'use client'

import { useQuery } from '@tanstack/react-query'
import { User, Building2, Mail } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import api from '@/lib/api'

interface Profile {
  email: string
  full_name: string
  chatter_name: string
  agency_name: string
  currency: string
}

export default function PortalProfilePage() {
  const { data, isLoading } = useQuery<Profile>({
    queryKey: ['portal-profile'],
    queryFn: () => api.get<Profile>('/api/v1/me/profile').then(r => r.data),
  })

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-4 border-b border-slate-700/50 bg-slate-900">
        <h1 className="text-lg font-semibold text-slate-100">Профиль</h1>
      </header>

      <div className="flex-1 p-6 space-y-4 overflow-y-auto max-w-lg">
        {isLoading ? (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-40" />
          </div>
        ) : data ? (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-violet-500/20 flex items-center justify-center">
                <User className="h-6 w-6 text-violet-400" />
              </div>
              <div>
                <p className="font-semibold text-slate-100">{data.full_name || data.chatter_name}</p>
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
        ) : null}
      </div>
    </div>
  )
}
