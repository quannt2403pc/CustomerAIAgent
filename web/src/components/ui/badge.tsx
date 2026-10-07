import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  Eye,
  EyeOff,
  HelpCircle,
  Loader2,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

/**
 * Badge — **luôn** gồm icon SVG + chữ, không bao giờ chỉ màu (plan.md §6.2).
 *
 * Icon từ lucide (SVG), **không dùng emoji làm icon**: emoji phụ thuộc font hệ
 * điều hành, không điều khiển được bằng design token, và screen reader đọc ra
 * tên emoji giữa câu.
 */
const tones = {
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  danger: 'bg-destructive/10 text-destructive border-destructive/30',
  info: 'bg-primary/10 text-primary border-primary/30',
  neutral: 'bg-muted text-muted-foreground border-border',
} as const

export type BadgeTone = keyof typeof tones

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  icon?: LucideIcon
  /** Quay icon — dùng cho trạng thái "đang chạy". */
  spin?: boolean
}

export function Badge({
  className,
  tone = 'neutral',
  icon: Icon,
  spin,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium',
        tones[tone],
        className,
      )}
      {...props}
    >
      {Icon ? <Icon className={cn('size-3.5 shrink-0', spin && 'animate-spin')} aria-hidden="true" /> : null}
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Badge theo miền nghiệp vụ
// ---------------------------------------------------------------------------

/**
 * `PARTIAL_OR_PRIVATE` cố ý là **hổ phách, không đỏ**: đề bài §4 tính nó là
 * *kết quả đạt* — đọc không được thì báo thật. Tô đỏ sẽ dạy người vận hành coi
 * sự trung thực là lỗi.
 */
const PROFILE_STATUS: Record<string, { label: string; tone: BadgeTone; icon: LucideIcon }> = {
  SUCCESS: { label: 'Thành công', tone: 'success', icon: CheckCircle2 },
  PARTIAL_OR_PRIVATE: { label: 'Đọc được một phần', tone: 'warning', icon: AlertTriangle },
  FAILED_VALIDATION: { label: 'Không qua kiểm duyệt', tone: 'danger', icon: XCircle },
  ERROR: { label: 'Lỗi', tone: 'danger', icon: XCircle },
}

export function ProfileStatusBadge({ status }: { status: string }) {
  const meta = PROFILE_STATUS[status] ?? {
    label: status,
    tone: 'neutral' as BadgeTone,
    icon: HelpCircle,
  }
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  )
}

export function SalesCheckBadge({ value }: { value: string | null }) {
  if (!value) return null
  const confirmed = value === 'ZERO_SALES_CONFIRMED'
  return (
    <Badge
      tone={confirmed ? 'success' : 'danger'}
      icon={confirmed ? CheckCircle2 : XCircle}
      title={
        confirmed
          ? 'Đã qua cả 3 lớp kiểm duyệt chào bán'
          : 'Chưa xác nhận 0% chào bán — nội dung không được dùng'
      }
    >
      {confirmed ? '0% chào bán' : 'Chưa xác nhận'}
    </Badge>
  )
}

/**
 * Cờ vision ba trạng thái. `null` = **chưa biết** (cổng B không trả cờ này,
 * task.md I-06) — hiện "chưa rõ" chứ không đoán hộ, vì đoán `false` chặn oan
 * model đọc được ảnh còn đoán `true` làm bước vision chết giữa pipeline.
 */
export function VisionBadge({ supports }: { supports: boolean | null }) {
  if (supports === true) {
    return (
      <Badge tone="success" icon={Eye}>
        Đọc được ảnh
      </Badge>
    )
  }
  if (supports === false) {
    return (
      <Badge tone="neutral" icon={EyeOff}>
        Không đọc được ảnh
      </Badge>
    )
  }
  return (
    <Badge tone="warning" icon={HelpCircle} title="Cổng này không cho biết model có đọc được ảnh">
      Chưa rõ có đọc được ảnh
    </Badge>
  )
}

const OUTBOX_STATUS: Record<string, { label: string; tone: BadgeTone; icon: LucideIcon }> = {
  draft: { label: 'Nháp, chờ bạn gửi', tone: 'info', icon: CircleDashed },
  approved: { label: 'Đã duyệt', tone: 'info', icon: CheckCircle2 },
  sent_manually: { label: 'Bạn đã gửi tay', tone: 'success', icon: CheckCircle2 },
  discarded: { label: 'Đã bỏ', tone: 'neutral', icon: CircleSlash },
}

export function OutboxStatusBadge({ status }: { status: string }) {
  const meta = OUTBOX_STATUS[status] ?? {
    label: status,
    tone: 'neutral' as BadgeTone,
    icon: HelpCircle,
  }
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  )
}

export function ConnectionBadge({
  connected,
  reachable,
  account,
}: {
  connected: boolean
  reachable: boolean
  account: string | null
}) {
  if (connected) {
    return (
      <Badge tone="success" icon={CheckCircle2}>
        {account ? `Đã kết nối (${account})` : 'Đã kết nối'}
      </Badge>
    )
  }
  // "Cổng sống nhưng chưa đăng nhập" ≠ "cổng chết": hai việc cần làm khác nhau.
  if (reachable) {
    return (
      <Badge tone="warning" icon={AlertTriangle}>
        Chưa đăng nhập
      </Badge>
    )
  }
  return (
    <Badge tone="danger" icon={XCircle}>
      Không gọi được cổng
    </Badge>
  )
}

export function RunningBadge({ label = 'Đang chạy' }: { label?: string }) {
  return (
    <Badge tone="info" icon={Loader2} spin>
      {label}
    </Badge>
  )
}
