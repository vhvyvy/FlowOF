import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface OwnerAdminBrief {
  id: number
  name: string
  shift_name: string | null
}

export interface StageHistoryItem {
  id: number
  from_stage: string | null
  to_stage: string
  changed_at: string
  changed_by: string
  notes: string | null
}

export interface LedgerItem {
  id: number
  event_type: string
  points: number
  notes: string | null
  created_at: string
}

export interface OwnerCaseDetail {
  id: number
  case_type: 'quantitative' | 'qualitative'
  tenant_id: number
  admin: OwnerAdminBrief
  om_user_id: string
  chatter_display_name: string
  category: string | null
  metric_type: string | null
  stage: string
  priority: string
  result: string | null
  opened_at: string
  closed_at: string | null
  review_date: string | null
  hold_days: number | null
  baseline_value: number | null
  result_value: number | null
  diagnosis_text: string
  action_plan: string
  history: StageHistoryItem[]
  ledger: LedgerItem[]
  activities_count: number
  sent_for_review_at: string | null
}

export function useOwnerCaseDetail(caseId: number) {
  return useQuery({
    queryKey: ['owner-case-detail', caseId],
    queryFn: () =>
      api
        .get<OwnerCaseDetail>(`/api/v1/dashboard/admins-review/cases/${caseId}`)
        .then((r) => r.data),
    enabled: caseId > 0,
  })
}
