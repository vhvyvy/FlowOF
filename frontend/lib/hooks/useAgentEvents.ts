import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export interface AgentEvent {
  id: number
  title: string
  description: string | null
  entity_type: string | null
  entity_ref: string | null
  trigger_metric: string | null
  trigger_value_before: number | null
  status: string
  source: string
  created_by: string
  priority: string
  created_at: string
  review_date: string | null
  closed_at: string | null
  outcome: string | null
  outcome_value_after: number | null
  related_chat_id: string | null
}

export interface ProposedEvent {
  title: string
  description?: string | null
  entity_type?: string | null
  entity_ref?: string | null
  trigger_metric?: string | null
  trigger_value_before?: number | null
  suggested_review_days?: number | null
  priority?: string
}

export interface CreateEventPayload {
  title: string
  description?: string | null
  entity_type?: string | null
  entity_ref?: string | null
  trigger_metric?: string | null
  trigger_value_before?: number | null
  review_in_days?: number | null
  source: 'user' | 'chat' | 'watcher'
  priority?: string
}

export interface PatchEventPayload {
  status?: string
  note?: string
  outcome?: string
  outcome_value_after?: number | null
  review_date?: string | null
}

export function useAgentEvents(options?: {
  status?: string
  entity?: string
  include_closed?: boolean
}) {
  const params = new URLSearchParams()
  if (options?.status) params.set('status', options.status)
  if (options?.entity) params.set('entity', options.entity)
  if (options?.include_closed) params.set('include_closed', 'true')

  return useQuery<AgentEvent[]>({
    queryKey: ['agent-events', options],
    queryFn: () =>
      api
        .get<AgentEvent[]>(`/api/v1/agent-events?${params.toString()}`)
        .then((r) => r.data),
  })
}

export function useAgentInsights(limit = 3) {
  return useQuery<AgentEvent[]>({
    queryKey: ['agent-events-insights', limit],
    queryFn: () =>
      api
        .get<AgentEvent[]>(`/api/v1/agent-events/insights?limit=${limit}`)
        .then((r) => r.data),
    staleTime: 60_000,
  })
}

export function useCreateAgentEvent() {
  const qc = useQueryClient()
  return useMutation<AgentEvent, Error, CreateEventPayload>({
    mutationFn: (payload) =>
      api.post<AgentEvent>('/api/v1/agent-events', payload).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-events'] })
      qc.invalidateQueries({ queryKey: ['agent-events-insights'] })
    },
  })
}

export function usePatchAgentEvent() {
  const qc = useQueryClient()
  return useMutation<AgentEvent, Error, { id: number; payload: PatchEventPayload }>({
    mutationFn: ({ id, payload }) =>
      api.patch<AgentEvent>(`/api/v1/agent-events/${id}`, payload).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent-events'] })
      qc.invalidateQueries({ queryKey: ['agent-events-insights'] })
    },
  })
}
