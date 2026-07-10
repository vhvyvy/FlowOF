import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface StageHistoryItem {
  id: number
  from_stage: string | null
  to_stage: string
  changed_at: string
  changed_by: string
  notes: string | null
}

export interface OwnerQualitativeCaseDetail {
  id: number
  om_user_id: string
  chatter_display_name: string
  category: string
  diagnosis_text: string
  action_plan: string
  priority: string
  stage: string
  result: string | null
  admin: { id: number; name: string }
  hold_start_date: string | null
  hold_end_date: string | null
  sent_for_review_at: string | null
  opened_at: string
  closed_at: string | null
  history: StageHistoryItem[]
  ledger_points: number | null
}

export function useOwnerQualitativeCase(caseId: number) {
  return useQuery({
    queryKey: ['owner-qualitative-case', caseId],
    queryFn: () =>
      api
        .get<OwnerQualitativeCaseDetail>(
          `/api/v1/dashboard/admins-review/cases/${caseId}`,
        )
        .then((r) => r.data),
    enabled: caseId > 0,
  })
}
