import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

import { ToastContext, type ToastApi, type ToastTone } from './toast-context'

/**
 * Toast — thay cho việc đổ JSON ra console (luật L5, plan.md §7.3.5).
 *
 * Hợp đồng: `toast()` chỉ nhận **chuỗi đã sẵn sàng hiển thị**. Không nhận
 * `unknown`/`Error`/response object, nên không có đường nào để một payload lọt
 * vào DOM. Bên gọi dùng `errorMessage(err)` để chuyển lỗi thành câu tiếng Việt +
 * mã ngắn trước khi truyền vào đây.
 *
 * A11y: vùng chứa là `aria-live="polite"` + `role="status"` — thông báo được đọc
 * **mà không** giật focus khỏi chỗ người dùng đang làm (WCAG; ui-ux-pro-max
 * `toast-accessibility`).
 */
interface ToastItem {
  id: number
  tone: ToastTone
  message: string
}

/** Tự biến mất sau 3–5s (plan.md §6.2); lỗi để lâu hơn vì cần đọc kịp. */
const DISMISS_MS: Record<ToastTone, number> = { success: 3500, info: 4000, error: 7000 }

const TONE_STYLE: Record<ToastTone, { cls: string; Icon: typeof Info; label: string }> = {
  success: {
    cls: 'border-success/40 bg-surface text-foreground',
    Icon: CheckCircle2,
    label: 'Thành công',
  },
  error: {
    cls: 'border-destructive/40 bg-surface text-foreground',
    Icon: XCircle,
    label: 'Lỗi',
  },
  info: { cls: 'border-primary/40 bg-surface text-foreground', Icon: Info, label: 'Thông tin' },
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([])
  const nextId = React.useRef(1)

  const remove = React.useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id))
  }, [])

  const push = React.useCallback(
    (tone: ToastTone, message: string) => {
      const id = nextId.current++
      setItems((current) => [...current, { id, tone, message }])
      window.setTimeout(() => remove(id), DISMISS_MS[tone])
    },
    [remove],
  )

  const api = React.useMemo<ToastApi>(
    () => ({
      success: (message) => push('success', message),
      error: (message) => push('error', message),
      info: (message) => push('info', message),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-center gap-2 sm:inset-x-auto sm:right-4 sm:items-end"
      >
        {items.map((item) => {
          const { cls, Icon, label } = TONE_STYLE[item.tone]
          return (
            <div
              key={item.id}
              className={cn(
                'pointer-events-auto flex w-full max-w-md items-start gap-2 rounded-lg border p-3 shadow-lg',
                cls,
              )}
            >
              <Icon
                className={cn(
                  'mt-0.5 size-4 shrink-0',
                  item.tone === 'success' && 'text-success',
                  item.tone === 'error' && 'text-destructive',
                  item.tone === 'info' && 'text-primary',
                )}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1 text-sm">
                <span className="sr-only">{label}: </span>
                {/* `break-words`: mã lỗi dài không được đẩy toast tràn ngang. */}
                <span className="break-words">{item.message}</span>
              </div>
              <button
                type="button"
                onClick={() => remove(item.id)}
                aria-label="Đóng thông báo"
                className="-m-1 cursor-pointer rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}
