'use client'

import { useQuery } from '@tanstack/react-query'
import { getMe, isAuthenticated } from '@/lib/auth'
import type { TenantOut } from '@/types'

export function useTenant() {
  return useQuery<TenantOut>({
    queryKey: ['me'],
    queryFn: getMe,
    enabled: isAuthenticated(),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
}
