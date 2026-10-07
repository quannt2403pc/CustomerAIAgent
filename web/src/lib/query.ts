import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './api'

/**
 * Cấu hình TanStack Query cho một app vận hành.
 *
 * `retry` có điều kiện: thử lại một 409 "chưa chọn cổng model" là vô nghĩa (trạng
 * thái chỉ đổi khi người dùng đi cấu hình), còn thử lại 401/403 ở tầng FE thì
 * nhân thêm số lần sai key — mà sai 5 lần là CLIProxy ban IP 30 phút (bẫy B3).
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        retry: (failureCount, error) => {
          if (error instanceof ApiError) {
            // 4xx là lỗi của yêu cầu — thử lại không đổi kết quả.
            if (error.httpStatus >= 400 && error.httpStatus < 500) return false
          }
          return failureCount < 2
        },
        refetchOnWindowFocus: false,
      },
      mutations: {
        // Mutation **không** tự retry: `POST /api/profiles` tốn 7–14 lượt gọi
        // model, và `mark-sent` lặp lại sẽ trả 409.
        retry: false,
      },
    },
  })
}
