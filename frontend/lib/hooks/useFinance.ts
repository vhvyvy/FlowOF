import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { FinanceResponse } from '@/types'

export function useFinance(month: number, year: number) {
  return useQuery<FinanceResponse>({
    queryKey: ['finance', month, year],
    queryFn: () =>
      api.get<FinanceResponse>(`/api/v1/finance?month=${month}&year=${year}`).then((r) => r.data),
    enabled: month > 0 && year > 0,
  })
}
