import { Slot } from '@radix-ui/react-slot'
import { type VariantProps, cva } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Nút — theo checklist plan.md §6.2:
 *
 * - **Touch target ≥44×44px**: `min-h-11` (44px) cho `default`, `min-h-9` (36px)
 *   chỉ dùng cho nút phụ trong bảng dữ liệu dày, nơi chuột là thiết bị chính.
 * - **`cursor-pointer`** trên mọi thứ bấm được (Tailwind không tự thêm).
 * - **Nút async disable + spinner**, và spinner có `aria-hidden` vì trạng thái đã
 *   được thông báo qua `aria-busy` + text.
 * - **Focus ring** đến từ `:focus-visible` toàn cục (index.css) — không component
 *   nào được `outline-none` mà không thay thế.
 */
const buttonVariants = cva(
  cn(
    'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded font-medium',
    'cursor-pointer transition-colors duration-200',
    'disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed',
    '[&_svg]:size-4 [&_svg]:shrink-0',
  ),
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'bg-muted text-foreground hover:bg-muted/70',
        outline: 'border border-input-border bg-surface text-foreground hover:bg-muted/50',
        ghost: 'text-foreground hover:bg-muted/60',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
      },
      size: {
        default: 'min-h-11 px-4 py-2 text-sm',
        sm: 'min-h-9 px-3 text-sm',
        // Nút chỉ có icon: vẫn giữ 44×44 để không vi phạm touch target.
        icon: 'size-11',
        iconSm: 'size-9',
      },
    },
    defaultVariants: { variant: 'primary', size: 'default' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  /** Đang chạy tác vụ async → tự disable + hiện spinner. */
  loading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, loading = false, children, disabled, ...props },
  ref,
) {
  const classes = cn(buttonVariants({ variant, size }), className)

  /*
   * `asChild` đi một nhánh **riêng**, không dùng chung thân với nút thường
   * (task.md I-45).
   *
   * Radix `Slot` đòi **đúng một** phần tử con. Nhánh chung trước đây truyền hai
   * con — `{loading ? <Loader2/> : null}` và `{children}` — nên `Slot` ném
   * `React.Children.only` và **cả trang trắng**. Lỗi chỉ nổ khi một `asChild`
   * thật sự được render, nên nó sống sót qua build, qua lint, và chỉ lộ ra lúc
   * chạy đúng nhánh đó.
   *
   * `loading`/`disabled` cũng không áp vào đây: `asChild` dùng để bọc `<a>`/
   * `<Link>`, mà thẻ neo không có thuộc tính `disabled` — React sẽ ghi một
   * attribute vô nghĩa ra DOM.
   */
  if (asChild) {
    return (
      <Slot ref={ref} className={classes} {...props}>
        {children}
      </Slot>
    )
  }

  return (
    <button
      ref={ref}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? <Loader2 className="animate-spin" aria-hidden="true" /> : null}
      {children}
    </button>
  )
})
