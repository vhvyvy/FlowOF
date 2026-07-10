import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface PendingQualitativeAdmin {
  id: number
  name: string
}

export interface PendingQualitativeItem {
  id: number
  om_user_id: string
  chatter_display_name: string
  category: string
  diagnosis_text: string
  action_plan: string
  priority: string
  admin: PendingQualitativeAdmin
  hold_start_date: string | null
  hold_end_date: string | null
  sent_for_review_at: string
  activities_count: number
}

export interface PendingQualitativeList {
  items: PendingQualitativeItem[]
  total: number
}

const PENDING_URL = '/api/v1/dashboard/admins-review/pending-qualitative'

export function usePendingQualitativeList() {
  return useQuery({
    queryKey: ['pending-qualitative-list'],
    queryFn: () =>
      api
        .get<PendingQualitativeList>(PENDING_URL, { params: { limit: 50, offset: 0 } })
        .then((r) => r.data),
    refetchInterval: 60_000,
  })
}

export function usePendingQualitativeCount() {
  return useQuery({
    queryKey: ['pending-qualitative-count'],
    queryFn: () =>
      api
        .get<PendingQualitativeList>(PENDING_URL, { params: { limit: 1, offset: 0 } })
        .then((r) => r.data.total),
    refetchInterval: 60_000,
  })
}
