import * as React from 'react'

/**
 * Context + hook của toast nằm **tách khỏi** component.
 *
 * Lý do thực dụng: React Fast Refresh chỉ hoạt động khi một file chỉ export
 * component. Gộp `useToast` vào `toast.tsx` làm mọi lần sửa toast phải reload
 * cả trang trong lúc dev.
 */
export type ToastTone = 'success' | 'error' | 'info'

export interface ToastApi {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
}

export const ToastContext = React.createContext<ToastApi | null>(null)

/**
 * Chỉ nhận **chuỗi đã sẵn sàng hiển thị** (luật L5). Bên gọi dùng
 * `errorMessage(err)` để chuyển lỗi thành câu tiếng Việt + mã ngắn trước khi
 * truyền vào — nhờ vậy không có đường nào để một payload API lọt vào DOM.
 */
export function useToast(): ToastApi {
  const context = React.useContext(ToastContext)
  if (!context) throw new Error('useToast phải nằm trong <ToastProvider>')
  return context
}
