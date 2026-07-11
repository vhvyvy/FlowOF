import { useMutation, useQueryClient } from '@tanstack/react-query'
import api, { formatApiError } from '@/lib/api'

export interface CreateChatterMappingPayload {
  om_user_id: string
  display_name: string
}

export interface CreateChatterMappingResponse {
  om_user_id: string
  display_name: string
}

export function useCreateChatterMapping() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: CreateChatterMappingPayload) => {
      const res = await api.post<CreateChatterMappingResponse>(
        '/api/v1/admin-portal/chatters/mappings',
        body,
      )
      return res.data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-portal-chatters'] })
    },
    throwOnError: false,
  })
}

export function mappingErrorMessage(err: unknown): string | null {
  const status = (err as { response?: { status?: number; data?: { detail?: string } } })
    ?.response?.status
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (status === 409 || status === 422) {
    return typeof detail === 'string' ? detail : formatApiError(err)
  }
  return null
}
