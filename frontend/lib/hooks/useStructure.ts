import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { StructureResponse } from '@/types'

export function useStructure(month: number, year: number) {
  return useQuery<StructureResponse>({
    queryKey: ['structure', month, year],
    queryFn: () =>
      api.get<StructureResponse>(`/api/v1/structure?month=${month}&year=${year}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
