import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { StructureResponse } from '@/types'
import type { TeamScope } from '@/lib/hooks/useTeam'

export function useStructure(month: number, year: number, teamId: TeamScope = 'all') {
  const teamParam = typeof teamId === 'number' ? `&team_id=${teamId}` : ''
  return useQuery<StructureResponse>({
    queryKey: ['structure', month, year, teamId],
    queryFn: () =>
      api.get<StructureResponse>(`/api/v1/structure?month=${month}&year=${year}${teamParam}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
