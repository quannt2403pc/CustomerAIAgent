import * as React from 'react'

import { cn } from '@/lib/utils'

import { Label } from './label'

/**
 * Ô nhập + select — ranh giới control dùng `input-border` (≥3:1), không dùng
 * `border` trang trí (1.22:1, task.md I-42).
 */
const controlClass = cn(
  'w-full rounded border border-input-border bg-surface px-3 text-sm text-foreground',
  // 44px: cùng chuẩn touch target với nút.
  'min-h-11',
  'placeholder:text-muted-foreground',
  'disabled:cursor-not-allowed disabled:opacity-60',
  'aria-[invalid=true]:border-destructive aria-[invalid=true]:border-2',
)

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(controlClass, className)} {...props} />
  },
)

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(controlClass, 'py-2 leading-relaxed', className)} {...props} />
})

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, ...props }, ref) {
  /*
   * `<select>` **gốc**, không phải listbox tự dựng.
   *
   * Lý do có chủ đích: dropdown model là chỗ người vận hành phải chọn đúng giữa
   * 14–44 lựa chọn (task.md I-10), và `<select>` gốc cho sẵn điều hướng bàn
   * phím, tìm theo chữ, cuộn, và hành vi quen thuộc trên mọi thiết bị. Một
   * listbox tự dựng phải hiện thực lại tất cả — và thường bỏ sót phần bàn phím.
   * Thông tin phong phú (badge vision, giới hạn token) hiện ở panel **bên dưới**
   * select, nơi nó đọc được bằng screen reader thay vì nhồi vào `<option>`.
   */
  return <select ref={ref} className={cn(controlClass, 'cursor-pointer pr-8', className)} {...props} />
})

interface FieldProps {
  id: string
  label: string
  /** Lỗi hiện **cạnh field**, không dồn lên đầu trang (plan.md §6.2). */
  error?: string | null
  /** Giải thích luôn hiện, không phải placeholder biến mất khi gõ. */
  hint?: React.ReactNode
  required?: boolean
  children: (props: { id: string; 'aria-invalid'?: true; 'aria-describedby'?: string }) => React.ReactNode
  className?: string
}

/**
 * Bọc một control với label + hint + lỗi, nối đúng `aria-describedby`.
 *
 * Gom vào một chỗ vì đây là phần dễ làm sai nhất và sai thì không ai thấy: thiếu
 * `aria-describedby` thì screen reader đọc ô nhập mà **không** đọc câu lỗi, nên
 * người dùng chỉ nghe "ô trống" mà không biết vì sao bị từ chối.
 */
export function Field({
  id,
  label,
  error,
  hint,
  required,
  children,
  className,
}: FieldProps) {
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={id} required={required}>
        {label}
      </Label>
      {children({
        id,
        'aria-invalid': error ? true : undefined,
        'aria-describedby': describedBy,
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        // `role="alert"` để screen reader đọc ngay khi lỗi xuất hiện.
        <p id={errorId} role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
