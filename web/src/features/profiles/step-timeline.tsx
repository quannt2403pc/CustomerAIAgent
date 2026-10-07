import { AlertTriangle, Check, Circle, Loader2, MinusCircle, XCircle } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import type { Job, Step } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Timeline 6 bước (plan.md §6.3, task.md I-38).
 *
 * Mỗi trạng thái có **icon + chữ riêng**, không chỉ màu (plan.md §6.2).
 * `skipped` cố ý **không** phải màu đỏ: trang không có ảnh thì bước Ảnh không có
 * gì để làm — đó là kết quả đúng, báo đỏ sẽ dạy người vận hành sợ sự trung thực.
 */
const STATE_META: Record<string, { icon: LucideIcon; label: string; cls: string; spin?: boolean }> =
  {
    pending: { icon: Circle, label: 'Chưa tới', cls: 'text-muted-foreground' },
    running: { icon: Loader2, label: 'Đang chạy', cls: 'text-primary', spin: true },
    done: { icon: Check, label: 'Xong', cls: 'text-success' },
    skipped: { icon: MinusCircle, label: 'Bỏ qua', cls: 'text-muted-foreground' },
    failed: { icon: XCircle, label: 'Lỗi', cls: 'text-destructive' },
  }

export function StepTimeline({ job, loading }: { job: Job | null | undefined; loading?: boolean }) {
  if (loading && !job) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-9 w-full" />
        ))}
      </div>
    )
  }
  if (!job) return null

  const running = job.ok === null

  return (
    <div className="flex flex-col gap-3">
      {/*
        `aria-live="polite"`: tiến trình đổi trong hàng chục giây, screen reader
        cần nghe mà không bị giật focus.
      */}
      <ol className="flex flex-col gap-1" aria-live="polite" aria-busy={running}>
        {job.steps.map((step) => (
          <StepRow key={step.step} step={step} />
        ))}
      </ol>

      {job.error ? (
        <p role="alert" className="rounded border border-destructive/40 bg-destructive/10 p-3 text-sm">
          {job.error}
        </p>
      ) : null}
    </div>
  )
}

function StepRow({ step }: { step: Step }) {
  const meta = STATE_META[step.state] ?? {
    icon: AlertTriangle,
    label: step.state,
    cls: 'text-muted-foreground',
  }
  const Icon = meta.icon

  return (
    <li className="flex items-start gap-3 rounded px-2 py-1.5">
      <Icon
        className={cn('mt-0.5 size-4 shrink-0', meta.cls, meta.spin && 'animate-spin')}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium">{step.label}</span>
          {/* Chữ trạng thái đi kèm icon — không truyền tin chỉ bằng màu. */}
          <span className={cn('text-xs', meta.cls)}>{meta.label}</span>
        </div>
        {step.note ? (
          <p className="truncate text-xs text-muted-foreground" title={step.note}>
            {step.note}
          </p>
        ) : null}
      </div>
    </li>
  )
}
