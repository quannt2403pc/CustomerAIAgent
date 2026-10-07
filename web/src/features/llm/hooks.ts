import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  ActionResult,
  CredentialInfo,
  GatewayTest,
  LlmStatus,
  ModelList,
  OAuthStart,
  OAuthStatus,
  ProviderName,
} from '@/lib/types'

export const llmKeys = {
  status: ['llm', 'status'] as const,
  models: ['llm', 'models'] as const,
  apiKey: ['llm', 'api-key'] as const,
}

export function useLlmStatus() {
  return useQuery({
    queryKey: llmKeys.status,
    queryFn: ({ signal }) => api.get<LlmStatus>('/api/llm/status', undefined, signal),
  })
}

/**
 * Danh mục model của cổng **đang chọn**.
 *
 * `enabled` theo `provider`: chưa chọn cổng thì gọi `/api/llm/models` chắc chắn
 * trả 409 — hiện một toast đỏ ngay khi mở trang Cài đặt là đổ lỗi cho người dùng
 * vì chưa làm việc họ vừa mới vào đây để làm.
 */
export function useModels(provider: string | null | undefined) {
  return useQuery({
    queryKey: [...llmKeys.models, provider],
    queryFn: ({ signal }) => api.get<ModelList>('/api/llm/models', undefined, signal),
    enabled: Boolean(provider),
  })
}

export function useRefreshModels() {
  const queryClient = useQueryClient()
  return useMutation({
    // `refresh=true` bỏ qua cache 10 phút phía server (task.md I-24): đổi API key
    // hay nhà cung cấp đổi modality thì cờ vision có thể cũ tới 10 phút.
    mutationFn: () => api.get<ModelList>('/api/llm/models', { refresh: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: llmKeys.models }),
  })
}

/** Mọi thao tác đổi cấu hình đều làm mới **cả** status lẫn danh mục model. */
function useLlmMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: llmKeys.status })
      void queryClient.invalidateQueries({ queryKey: llmKeys.models })
    },
  })
}

export function useSetProvider() {
  return useLlmMutation((provider: ProviderName) =>
    api.put<LlmStatus>('/api/llm/provider', { provider }),
  )
}

export function useSetModel() {
  return useLlmMutation((model: string) => api.put<LlmStatus>('/api/llm/model', { model }))
}

export function useSaveApiKey() {
  return useLlmMutation((apiKey: string) =>
    // Key đi trong **thân** request, không phải query string: query string lọt
    // vào access log của mọi proxy trên đường đi.
    api.put<CredentialInfo>('/api/llm/api-key', { api_key: apiKey }),
  )
}

export function useDeleteApiKey() {
  return useLlmMutation(() => api.del<ActionResult>('/api/llm/api-key'))
}

export function useDisconnect() {
  return useLlmMutation(() => api.post<ActionResult>('/api/llm/disconnect'))
}

export function useTestGateway() {
  return useMutation({ mutationFn: () => api.post<GatewayTest>('/api/llm/test') })
}

// ---------------------------------------------------------------------------
// OAuth
// ---------------------------------------------------------------------------
export function useStartOAuth() {
  return useMutation({ mutationFn: () => api.post<OAuthStart>('/api/llm/oauth/start') })
}

export function useOAuthStatus(state: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ['llm', 'oauth', state],
    queryFn: ({ signal }) =>
      api.get<OAuthStatus>('/api/llm/oauth/status', { state: state ?? '' }, signal),
    enabled: Boolean(state) && enabled,
    // Poll 2s theo plan.md §5.1.2. Nhanh hơn chỉ làm CLIProxy bận mà người dùng
    // vẫn đang ở tab Google.
    refetchInterval: 2000,
    // Không retry: `state` hết hạn (CLIProxy giữ 5 phút) thì thử lại vô ích.
    retry: false,
    gcTime: 0,
  })
}

export function useCancelOAuth() {
  return useMutation({
    mutationFn: (state: string) => api.del<ActionResult>('/api/llm/oauth/session', { state }),
  })
}

export function useSubmitCallback() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (args: { state: string; url: string }) =>
      api.post<ActionResult>('/api/llm/oauth/callback', args),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: llmKeys.status })
    },
  })
}
