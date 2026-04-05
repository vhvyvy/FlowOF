import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { FinanceResponse } from '@/types'
import type { TeamScope } from '@/lib/hooks/useTeam'

export function useFinance(month: number, year: number, teamId: TeamScope = 'all') {
  const teamQs = teamId === 'all' ? '' : `&team_id=${teamId}`
  return useQuery<FinanceResponse>({
    queryKey: ['finance', month, year, teamId],
    queryFn: () =>
      api.get<FinanceResponse>(`/api/v1/finance?month=${month}&year=${year}${teamQs}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
