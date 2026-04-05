'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import api from '@/lib/api'
import { fetchOnboardingStatus } from '@/lib/auth'
import Step1Agency from './steps/Step1Agency'
import Step2Source from './steps/Step2Source'
import Step3Connect from './steps/Step3Connect'
import Step4Mapping from './steps/Step4Mapping'
import Step5Preview from './steps/Step5Preview'

const STEPS = [Step1Agency, Step2Source, Step3Connect, Step4Mapping, Step5Preview]

export default function OnboardingPage() {
  const router = useRouter()
  const [uiStep, setUiStep] = useState(1)
  const [data, setData] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchOnboardingStatus()
      .then((s) => {
        if (s.onboarding_completed) {
          router.replace('/dashboard')
          return
        }
        setUiStep(s.next_ui_step)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [router])

  const finishStep = useCallback(
    async (stepNumber: number, stepData: Record<string, unknown>) => {
      setData((prev) => ({ ...prev, ...stepData }))
      await api.post('/api/v1/onboarding/step', { step: stepNumber, data: stepData })
      if (stepNumber >= 5) {
        await api.post('/api/v1/onboarding/complete')
        router.push('/dashboard')
      } else {
        setUiStep(stepNumber + 1)
      }
    },
    [router]
  )

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <p className="text-slate-500 text-sm">Загрузка…</p>
      </div>
    )
  }

  const safeStep = Math.min(Math.max(uiStep, 1), 5)
  const Current = STEPS[safeStep - 1]

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="w-full max-w-xl">
        <div className="flex gap-2 mb-8">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-colors ${
                i < safeStep ? 'bg-indigo-500' : 'bg-slate-800'
              }`}
            />
          ))}
        </div>

        <Current onComplete={(d) => finishStep(safeStep, d)} data={data} />
      </div>
    </div>
  )
}
