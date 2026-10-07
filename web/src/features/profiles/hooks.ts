import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  ActionResult,
  AnalyzeAccepted,
  AnalyzeRequest,
  DashboardStats,
  Job,
  OutboxList,
  ProfileDetail,
  ProfileList,
} from '@/lib/types'

export const profileKeys = {
  list: ['profiles'] as const,
  detail: (id: string) => ['profiles', id] as const,
  job: (id: string) => ['jobs', id] as const,
  stats: ['stats'] as const,
  outbox: ['outbox'] as const,
}

export function useCreateAnalysis() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AnalyzeRequest) => api.post<AnalyzeAccepted>('/api/profiles', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.list })
      void queryClient.invalidateQueries({ queryKey: profileKeys.stats })
    },
  })
}

/**
 * Poll tiến trình job.
 *
 * `refetchInterval` trả **`false` khi job đã xong** (`ok !== null`): poll tiếp
 * một job đã kết thúc là gọi API mãi mãi cho một kết quả không bao giờ đổi.
 * 1,5 giây đủ mượt cho timeline 6 bước mà không nện vào DB.
 */
export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: profileKeys.job(jobId ?? ''),
    queryFn: ({ signal }) => api.get<Job>(`/api/jobs/${jobId}`, undefined, signal),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data?.ok === null ? 1500 : false),
  })
}

export function useProfile(profileId: string | null) {
  return useQuery({
    queryKey: profileKeys.detail(profileId ?? ''),
    queryFn: ({ signal }) => api.get<ProfileDetail>(`/api/profiles/${profileId}`, undefined, signal),
    enabled: Boolean(profileId),
  })
}

export function useProfiles(limit = 20, offset = 0) {
  return useQuery({
    queryKey: [...profileKeys.list, limit, offset],
    queryFn: ({ signal }) => api.get<ProfileList>('/api/profiles', { limit, offset }, signal),
  })
}

export function useStats() {
  return useQuery({
    queryKey: profileKeys.stats,
    queryFn: ({ signal }) => api.get<DashboardStats>('/api/stats', undefined, signal),
  })
}

export function useOutbox(status?: string) {
  return useQuery({
    queryKey: [...profileKeys.outbox, status ?? 'all'],
    queryFn: ({ signal }) => api.get<OutboxList>('/api/outbox', { status }, signal),
  })
}

function useOutboxAction(path: (id: string) => string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<ActionResult>(path(id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.outbox })
      void queryClient.invalidateQueries({ queryKey: profileKeys.stats })
    },
  })
}

/** Ghi lại việc **con người** đã tự gửi. Không gửi gì cả (luật L3). */
export function useMarkSent() {
  return useOutboxAction((id) => `/api/outbox/${id}/mark-sent`)
}

export function useDiscard() {
  return useOutboxAction((id) => `/api/outbox/${id}/discard`)
}

export function useRunEveningNow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<ActionResult>('/api/outbox/run-now'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: profileKeys.outbox })
      void queryClient.invalidateQueries({ queryKey: profileKeys.stats })
    },
  })
}
