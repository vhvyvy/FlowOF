import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export type BaselineMetricType =
  | 'ppv_open_rate'
  | 'rpc'
  | 'apv'
  | 'total_chats'
  | 'revenue'

export interface BaselinePreview {
  available: boolean
  lookback_days: number
  value?: number
  snapshot_date?: string
  days_ago?: number
}

export function useBaselinePreview(
  omUserId: string | null | undefined,
  metricType: BaselineMetricType,
  enabled: boolean,
) {
  return useQuery<BaselinePreview>({
    queryKey: ['baseline-preview', omUserId, metricType],
    queryFn: () =>
      api
        .get<BaselinePreview>(
          `/api/v1/admin-portal/chatters/${omUserId}/baseline-preview`,
          { params: { metric_type: metricType } },
        )
        .then(r => r.data),
    enabled: enabled && !!omUserId,
    staleTime: Infinity,
  })
}
