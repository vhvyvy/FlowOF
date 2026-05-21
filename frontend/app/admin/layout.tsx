'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useTenant } from '@/lib/hooks/useTenant'
import { isAuthenticated } from '@/lib/auth'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { data: tenant, isLoading } = useTenant()

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login')
      return
    }
    if (!isLoading && tenant && !tenant.is_admin) {
      router.replace('/dashboard')
    }
  }, [tenant, isLoading, router])

  if (isLoading || !tenant) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!tenant.is_admin) return null

  return <>{children}</>
}
