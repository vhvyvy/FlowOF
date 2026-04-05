'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { isAuthenticated, fetchOnboardingStatus } from '@/lib/auth'
import { Sidebar } from '@/components/layout/Sidebar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace('/login')
      return
    }
    let cancelled = false
    fetchOnboardingStatus()
      .then((s) => {
        if (cancelled) return
        if (!s.onboarding_completed) {
          router.replace('/onboarding')
          return
        }
        setReady(true)
      })
      .catch(() => {
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [router])

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950">
        <p className="text-slate-500 text-sm">Загрузка…</p>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-slate-950">{children}</main>
    </div>
  )
}
