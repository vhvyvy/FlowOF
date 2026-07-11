import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { AdminKpiSummary } from '@/lib/hooks/useAdminsReview'

export interface AdminDetailAdmin {
  id: number
  name: string | null
  email: string
  admin_shift_id: number | null
  shift_name: string | null
}

export interface AdminDetailResponse {
  admin: AdminDetailAdmin
  current_kpi: AdminKpiSummary
  is_calibration: boolean
  open_cases_count: number
  detect_result_ratio_threshold: number
}

export interface AdminCaseOut {
  id: number
  admin_id: number
  case_type: 'quantitative' | 'qualitative'
  category: string | null
  om_user_id: string
  metric_type: string | null
  chatter_display_name: string | null
  stage: string
  priority: string
  result: string | null
  opened_at: string
  closed_at: string | null
  review_date: string | null
  hold_days: number | null
  baseline_value: number | null
  result_value: number | null
  baseline_version?: string
  is_early_month?: boolean
  is_new_chatter?: boolean
  notes: string | null
}

export interface AdminLedgerEntry {
  id: number
  case_id: number | null
  event_type: string
  points: number
  notes: string | null
  created_at: string
}

export interface KpiSnapshotHistoryItem {
  period_year: number
  period_month: number
  cases_opened: number
  cases_closed_success: number
  cases_closed_failed: number
  cases_cancelled: number
  guardrail_hits: number
  total_points: number
  detect_result_ratio: number | null
  is_calibration: boolean
}

export function useAdminDetail(adminId: number) {
  return useQuery({
    queryKey: ['admin-detail', adminId],
    queryFn: async () => {
      const res = await api.get<AdminDetailResponse>(
        `/api/v1/dashboard/admins-review/admins/${adminId}`,
      )
      return res.data
    },
    enabled: adminId > 0,
    staleTime: 60_000,
  })
}

export function useAdminCases(adminId: number) {
  return useQuery({
    queryKey: ['admin-cases', adminId],
    queryFn: async () => {
      const res = await api.get<AdminCaseOut[]>(
        `/api/v1/dashboard/admins-review/admins/${adminId}/cases`,
        { params: { include_closed: true } },
      )
      return res.data
    },
    enabled: adminId > 0,
    staleTime: 60_000,
  })
}

export function useAdminLedger(adminId: number, year: number, month: number) {
  return useQuery({
    queryKey: ['admin-ledger', adminId, year, month],
    queryFn: async () => {
      const res = await api.get<AdminLedgerEntry[]>(
        `/api/v1/dashboard/admins-review/admins/${adminId}/ledger`,
        { params: { year, month } },
      )
      return res.data
    },
    enabled: adminId > 0,
    staleTime: 60_000,
  })
}

export function useAdminKpiHistory(adminId: number) {
  return useQuery({
    queryKey: ['admin-kpi-history', adminId],
    queryFn: async () => {
      const res = await api.get<KpiSnapshotHistoryItem[]>(
        `/api/v1/dashboard/admins-review/admins/${adminId}/kpi-history`,
      )
      return res.data
    },
    enabled: adminId > 0,
    staleTime: 120_000,
  })
}
