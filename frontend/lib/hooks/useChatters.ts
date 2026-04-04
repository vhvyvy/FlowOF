import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { ChattersResponse } from '@/types'

export function useChatters(month: number, year: number) {
  return useQuery<ChattersResponse>({
    queryKey: ['chatters', month, year],
    queryFn: () =>
      api.get<ChattersResponse>(`/api/v1/chatters?month=${month}&year=${year}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
