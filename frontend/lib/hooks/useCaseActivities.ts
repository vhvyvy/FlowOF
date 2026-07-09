import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api, { formatApiError } from '@/lib/api'

export type ActivityType =
  | 'review'
  | 'training'
  | 'meeting'
  | 'observation'
  | 'note'
  | 'other'

export interface ActivityFile {
  id: number
  file_path: string
  original_name: string | null
  size_bytes: number | null
  mime_type: string | null
  download_url: string
}

export interface ActivityItem {
  id: number
  activity_type: ActivityType
  text: string
  created_at: string
  updated_at: string
  admin: { id: number; name: string }
  files: ActivityFile[]
}

export interface ActivityListResponse {
  items: ActivityItem[]
  total: number
}

export interface ActivityFiltersState {
  activity_type?: string[]
  date_from?: string
  date_to?: string
  has_files?: boolean
  text_search?: string
  limit: number
  offset: number
}

function buildParams(filters: ActivityFiltersState): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    limit: filters.limit,
    offset: filters.offset,
  }
  if (filters.date_from) params.date_from = filters.date_from
  if (filters.date_to) params.date_to = filters.date_to
  if (filters.has_files === true) params.has_files = true
  if (filters.text_search?.trim()) params.text_search = filters.text_search.trim()
  return params
}

function appendArrayParams(
  base: URLSearchParams,
  filters: ActivityFiltersState,
): URLSearchParams {
  const params = new URLSearchParams(base)
  filters.activity_type?.forEach((t) => params.append('activity_type', t))
  return params
}

export function fetchActivities(caseId: number, filters: ActivityFiltersState) {
  const params = appendArrayParams(
    new URLSearchParams(
      Object.entries(buildParams(filters)).map(([k, v]) => [k, String(v)]),
    ),
    filters,
  )
  const qs = params.toString()
  const url = `/api/v1/admin-portal/cases/${caseId}/activities${qs ? `?${qs}` : ''}`
  return api.get<ActivityListResponse>(url).then((r) => r.data)
}

export function useActivities(caseId: number, filters: ActivityFiltersState) {
  return useQuery({
    queryKey: ['case-activities', caseId, filters],
    queryFn: () => fetchActivities(caseId, filters),
    staleTime: 0,
    enabled: caseId > 0,
  })
}

export function useCreateActivity(caseId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: {
      activity_type: ActivityType
      text: string
      files: File[]
    }) => {
      const form = new FormData()
      form.append('activity_type', payload.activity_type)
      form.append('text', payload.text)
      payload.files.forEach((f) => form.append('files', f))
      const res = await api.post(
        `/api/v1/admin-portal/cases/${caseId}/activities`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      return res.data as { activity_id: number; created_at: string; files_count: number }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['case-activities', caseId] })
    },
    meta: { formatError: formatApiError },
  })
}

export function useDeleteActivity(caseId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (activityId: number) => {
      await api.delete(
        `/api/v1/admin-portal/cases/${caseId}/activities/${activityId}`,
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['case-activities', caseId] })
    },
  })
}
