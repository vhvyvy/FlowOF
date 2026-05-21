import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { TeamScope } from '@/lib/hooks/useTeam'

export interface MonthSummary {
  year: number
  month: number
  revenue: number
  transactions_count: number
}

interface MonthsSummaryResponse {
  months: MonthSummary[]
}

export function useMonthsSummary(teamId: TeamScope = 'all') {
  const teamQs = teamId === 'all' ? '' : `?team_id=${teamId}`
  return useQuery<MonthsSummaryResponse>({
    queryKey: ['months-summary', teamId],
    queryFn: () =>
      api.get<MonthsSummaryResponse>(`/api/v1/overview/months-summary${teamQs}`).then((r) => r.data),
    // Сводка меняется только после импорта/синка — кешируем агрессивно.
    staleTime: 60_000,
  })
}
