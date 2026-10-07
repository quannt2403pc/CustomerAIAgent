import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ActionResult, Conversation, ConversationList, CookieStatus } from '@/lib/types'

export const conversationKeys = {
  list: ['conversations'] as const,
  detail: (id: string) => ['conversations', id] as const,
  cookie: ['fb-cookie'] as const,
}

/** Khoảng poll khi đang chờ khách trả lời (ms). */
const POLL_WHILE_WAITING_MS = 5000

/**
 * Chi tiết một phiên hội thoại.
 *
 * `poll = true` khi đã kết nối Page: phản hồi của khách về qua webhook ở
 * **server**, nên trình duyệt không có cách nào biết ngoài việc hỏi lại. Dùng
 * poll thay vì WebSocket có chủ đích — 5 giây là đủ cho nhịp một cuộc trò
 * chuyện, và nó không thêm một kênh kết nối phải tự lo việc nối lại.
 *
 * Poll **dừng** khi phiên đã đóng: hội thoại đóng thì không còn tin nào tới, và
 * một tab bị bỏ quên sẽ gọi API mãi không lý do.
 */
export function useConversation(id: string | null, options?: { poll?: boolean }) {
  const poll = options?.poll ?? false
  return useQuery({
    queryKey: conversationKeys.detail(id ?? ''),
    queryFn: ({ signal }) => api.get<Conversation>(`/api/conversations/${id}`, undefined, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      if (!poll) return false
      return query.state.data?.status === 'active' ? POLL_WHILE_WAITING_MS : false
    },
  })
}

/**
 * Danh sách hội thoại.
 *
 * `poll` dùng khi webhook đang bật: một khách nhắn Page sẽ tạo hội thoại **mới**
 * mà trang này chưa biết. Không poll thì tin thật của họ nằm trong DB và người
 * vận hành không thấy cho tới khi tự tải lại trang.
 */
export function useConversations(options?: { poll?: boolean }) {
  return useQuery({
    queryKey: conversationKeys.list,
    queryFn: ({ signal }) => api.get<ConversationList>('/api/conversations', undefined, signal),
    refetchInterval: options?.poll ? POLL_WHILE_WAITING_MS : false,
  })
}

export function useStartConversation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (profileId: string) =>
      api.post<Conversation>('/api/conversations', { profile_id: profileId }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.list }),
  })
}

/** Thay cache bằng phiên vừa trả về — tránh một vòng refetch nhấp nháy. */
function useConversationMutation<TArgs>(
  fn: (id: string, args: TArgs) => Promise<Conversation>,
  id: string | null,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: TArgs) => fn(id ?? '', args),
    onSuccess: (data) => {
      queryClient.setQueryData(conversationKeys.detail(data.id), data)
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list })
    },
  })
}

/**
 * Ghi lại tin **bạn vừa tự gửi** ở Messenger.
 *
 * Tên `record-sent` mô tả việc đã xảy ra. Hệ thống không gửi gì (luật L3).
 */
export function useRecordSent(id: string | null) {
  return useConversationMutation<{
    text: string
    suggestion_id?: string | null
  }>(
    (conversationId, body) =>
      api.post<Conversation>(`/api/conversations/${conversationId}/record-sent`, body),
    id,
  )
}

/** Dán phản hồi của khách → backend ghi lại **và** sinh gợi ý lượt kế tiếp. */
export function useRecordReply(id: string | null) {
  return useConversationMutation<{ text: string }>(
    (conversationId, body) =>
      api.post<Conversation>(`/api/conversations/${conversationId}/reply`, body),
    id,
  )
}

export function useCloseConversation(id: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<ActionResult>(`/api/conversations/${id}/close`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: conversationKeys.detail(id ?? ''),
      })
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list })
    },
  })
}

// ---------------------------------------------------------------------------
// Cookie Facebook (task.md X.2)
// ---------------------------------------------------------------------------
export function useCookieStatus() {
  return useQuery({
    queryKey: conversationKeys.cookie,
    queryFn: ({ signal }) => api.get<CookieStatus>('/api/llm/fb-cookie', undefined, signal),
  })
}

export function useSaveCookie() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (cookie: string) => api.put<CookieStatus>('/api/llm/fb-cookie', { cookie }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.cookie }),
  })
}

export function useDeleteCookie() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.del<ActionResult>('/api/llm/fb-cookie'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: conversationKeys.cookie }),
  })
}
