import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { ChattersResponse } from '@/types'
import type { TeamScope } from '@/lib/hooks/useTeam'

export function useChatters(month: number, year: number, teamId: TeamScope = 'all') {
  const teamQs = teamId === 'all' ? '' : `&team_id=${teamId}`
  return useQuery<ChattersResponse>({
    queryKey: ['chatters', month, year, teamId],
    queryFn: () =>
      api.get<ChattersResponse>(`/api/v1/chatters?month=${month}&year=${year}${teamQs}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
