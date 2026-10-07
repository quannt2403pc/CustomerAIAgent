import type { LucideIcon } from 'lucide-react'
import * as React from 'react'

/**
 * Empty state có **hướng dẫn việc cần làm**, không chỉ "Không có dữ liệu"
 * (plan.md §6.2 / ui-ux-pro-max `empty-states`).
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description: React.ReactNode
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <Icon className="size-8 text-muted-foreground" aria-hidden="true" />
      <div>
        <p className="font-medium">{title}</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}
