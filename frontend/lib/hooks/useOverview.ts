import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { OverviewResponse } from '@/types'

export function useOverview(month: number, year: number) {
  return useQuery<OverviewResponse>({
    queryKey: ['overview', month, year],
    queryFn: () =>
      api.get<OverviewResponse>(`/api/v1/overview?month=${month}&year=${year}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
