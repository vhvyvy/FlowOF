import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { OverviewResponse } from '@/types'
import type { TeamScope } from '@/lib/hooks/useTeam'

export function useOverview(month: number, year: number, teamId: TeamScope = 'all') {
  const teamQs =
    teamId === 'all' ? '' : `&team_id=${teamId}`
  return useQuery<OverviewResponse>({
    queryKey: ['overview', month, year, teamId],
    queryFn: () =>
      api
        .get<OverviewResponse>(`/api/v1/overview?month=${month}&year=${year}${teamQs}`)
        .then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
