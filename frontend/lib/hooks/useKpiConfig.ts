import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface KpiConfigRow {
  id: number
  metric_type: string
  noise_threshold_pct: number
  guardrail_metrics: string[]
  hold_days: number
  detect_to_result_ratio_min: number
  calibration_days: number
}

export interface KpiConfigUpdatePayload {
  noise_threshold_pct: number
  guardrail_metrics: string[]
  hold_days: number
  detect_to_result_ratio_min: number
  calibration_days: number
}

export function useKpiConfig() {
  return useQuery({
    queryKey: ['kpi-config'],
    queryFn: async () => {
      const res = await api.get<KpiConfigRow[]>(
        '/api/v1/dashboard/admins-review/kpi-config',
      )
      return res.data
    },
    staleTime: 60_000,
  })
}

export function useUpdateKpiConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      metricType,
      body,
    }: {
      metricType: string
      body: KpiConfigUpdatePayload
    }) => {
      const res = await api.put<KpiConfigRow>(
        `/api/v1/dashboard/admins-review/kpi-config/${metricType}`,
        body,
      )
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kpi-config'] })
      qc.invalidateQueries({ queryKey: ['admins-review'] })
    },
  })
}
