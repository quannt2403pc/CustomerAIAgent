import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ActionResult, Conversation, PageStatus } from '@/lib/types'
import { conversationKeys } from '@/features/conversations/hooks'

export const messengerKeys = {
  status: ['messenger-status'] as const,
}

export function usePageStatus() {
  return useQuery({
    queryKey: messengerKeys.status,
    queryFn: ({ signal }) => api.get<PageStatus>('/api/messenger/status', undefined, signal),
  })
}

export function useSavePageToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => api.put<PageStatus>('/api/messenger/page-token', { token }),
    onSuccess: (data) => {
      queryClient.setQueryData(messengerKeys.status, data)
      // Kết nối Page làm đổi `can_send` của **mọi** hội thoại, nên phải làm mới
      // cả danh sách lẫn chi tiết — nếu không, nút Gửi vẫn hiện trạng thái cũ.
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list })
    },
  })
}

export function useDeletePageToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.del<ActionResult>('/api/messenger/page-token'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: messengerKeys.status })
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list })
    },
  })
}

/**
 * **Gửi thật** một tin qua Facebook Page.
 *
 * Khác `useRecordSent` (chỉ ghi lại việc bạn đã tự gửi bên ngoài): hook này gọi
 * Send API. Backend từ chối với 409 `E-MSG-409-NOLINK` nếu người nhận chưa chủ
 * động nhắn Page — đó là điều kiện đồng ý, và nó được kiểm ở server chứ không
 * phải ở đây.
 */
export function useSendViaPage(id: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { text: string; suggestion_id?: string | null }) =>
      api.post<Conversation>(`/api/conversations/${id}/send`, body),
    onSuccess: (data) => {
      queryClient.setQueryData(conversationKeys.detail(data.id), data)
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list })
    },
  })
}
