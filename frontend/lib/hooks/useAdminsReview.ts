import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface AdminKpiSummary {
  cases_opened: number
  cases_closed_success: number
  cases_closed_failed: number
  cases_cancelled: number
  guardrail_hits: number
  total_points: number
  detect_result_ratio: number | null
  is_calibration: boolean
}

export interface AdminListItem {
  id: number
  name: string | null
  email: string
  admin_shift_id: number | null
  shift_name: string | null
  current_month_kpi: AdminKpiSummary
  open_cases_count: number
}

export interface AdminsReviewResponse {
  admins: AdminListItem[]
  detect_result_ratio_threshold: number
}

export interface RecalcSnapshotsResponse {
  recalculated: number
  admins: Array<{
    id: number
    name: string
    total_points: number
    cases_opened: number
  }>
  cached_at: string
}

export function useAdminsReview() {
  return useQuery({
    queryKey: ['admins-review'],
    queryFn: async () => {
      const res = await api.get<AdminsReviewResponse>(
        '/api/v1/dashboard/admins-review/admins',
      )
      return res.data
    },
    staleTime: 60_000,
  })
}

export function useRecalcSnapshots() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const res = await api.post<RecalcSnapshotsResponse>(
        '/api/v1/dashboard/admins-review/recalc-snapshots',
      )
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admins-review'] })
      qc.invalidateQueries({ queryKey: ['admins-list'] })
    },
  })
}
