import { cn } from '@/lib/utils'

/**
 * Skeleton cho tác vụ >1s (plan.md §6.2). `prefers-reduced-motion` đã tắt
 * animation ở tầng global nên không cần xử lý riêng ở đây.
 *
 * `aria-hidden`: skeleton là chỗ giữ layout, không phải nội dung — để screen
 * reader đọc nó là đọc ra tiếng ồn. Trạng thái "đang tải" được thông báo bằng
 * `aria-busy` trên vùng chứa.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded bg-muted', className)}
      {...props}
    />
  )
}
