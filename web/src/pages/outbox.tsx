import { Check, Copy, Inbox, PlayCircle, Trash2 } from 'lucide-react'
import * as React from 'react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { useToast } from '@/components/toast-context'
import { OutboxStatusBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Field, Select } from '@/components/ui/field'
import { Skeleton } from '@/components/ui/skeleton'
import { useDiscard, useMarkSent, useOutbox, useRunEveningNow } from '@/features/profiles/hooks'
import { errorMessage } from '@/lib/api'
import type { OutboxItem } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'

const FILTERS = [
  { value: '', label: 'Tất cả' },
  { value: 'draft', label: 'Nháp, chờ bạn gửi' },
  { value: 'sent_manually', label: 'Bạn đã gửi tay' },
  { value: 'discarded', label: 'Đã bỏ' },
]

/**
 * Trang Outbox — luật thép L3 hiện diện ngay trên giao diện.
 *
 * **Không có nút "Gửi"**. Chỉ có "Chép" (để bạn tự dán vào Messenger) và "Đã gửi
 * tay" (ghi lại việc bạn đã làm ở nơi khác). Một nút tên "Gửi" ở đây là lời mời
 * hiện thực việc gửi — và đó là điều hệ thống cam kết không làm.
 */
export function OutboxPage() {
  const toast = useToast()
  const [filter, setFilter] = React.useState('')
  const list = useOutbox(filter || undefined)
  const runNow = useRunEveningNow()

  return (
    <>
      <PageHeader
        title="Outbox"
        description="Nháp câu chuyện mồi 20h. Hệ thống không gửi gì — bạn chép rồi tự gửi, sau đó đánh dấu lại."
        actions={
          <Button
            variant="outline"
            loading={runNow.isPending}
            onClick={() =>
              runNow.mutate(undefined, {
                onSuccess: (data) => toast.success(data.message),
                onError: (error) => toast.error(errorMessage(error)),
              })
            }
          >
            <PlayCircle aria-hidden="true" />
            Chạy lượt 20h ngay
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <Field id="outbox-filter" label="Lọc theo trạng thái" className="max-w-xs">
          {(fieldProps) => (
            <Select
              {...fieldProps}
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              {FILTERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </Field>

        {list.isPending ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 3 }, (_, index) => (
              <Skeleton key={index} className="h-28" />
            ))}
          </div>
        ) : list.isError ? (
          <p role="alert" className="text-sm font-medium text-destructive">
            {errorMessage(list.error)}
          </p>
        ) : list.data && list.data.items.length > 0 ? (
          <ul className="flex flex-col gap-3">
            {list.data.items.map((item) => (
              <OutboxCard key={item.id} item={item} />
            ))}
          </ul>
        ) : (
          <EmptyState
            icon={Inbox}
            title="Chưa có nháp nào"
            description='Lịch 20h hằng ngày sẽ tự sinh câu mồi cho các profile đã phân tích. Bấm "Chạy lượt 20h ngay" nếu bạn muốn sinh luôn.'
          />
        )}
      </div>
    </>
  )
}

function OutboxCard({ item }: { item: OutboxItem }) {
  const toast = useToast()
  const markSent = useMarkSent()
  const discard = useDiscard()
  const open = item.status === 'draft' || item.status === 'approved'

  const copy = () => {
    void navigator.clipboard
      .writeText(item.message ?? '')
      .then(() => toast.success('Đã chép câu mồi. Dán vào Messenger rồi bấm "Đã gửi tay".'))
      .catch(() => toast.error('Trình duyệt không cho chép tự động. Hãy bôi đen rồi chép tay.'))
  }

  return (
    <li>
      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              {/*
                `inline-block py-1` không phải để cho đẹp: đo thật bằng
                Playwright, link này cao **19px** — dưới ngưỡng 24px của WCAG
                2.5.8. Nó là tiêu đề đứng riêng trong một `div`, nên **không**
                được hưởng ngoại lệ "liên kết trong câu văn" như các link trong
                đoạn chữ. Thêm 4px đệm trên/dưới đưa vùng bấm lên 27px mà chữ
                vẫn y nguyên.
              */}
              <Link
                to={`/phan-tich/${item.profile_id}`}
                className="inline-block py-1 font-medium text-primary underline-offset-2 hover:underline"
              >
                {item.customer_name ?? 'Không đọc được tên'}
              </Link>
              <span className="tabular block text-xs text-muted-foreground">
                Mốc {formatDateTime(item.scheduled_for)}
                {item.acted_at ? ` · bạn xử lý lúc ${formatDateTime(item.acted_at)}` : ''}
              </span>
            </div>
            <OutboxStatusBadge status={item.status} />
          </div>

          {item.message ? (
            <p className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
              {item.message}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nháp này không còn nội dung (câu mồi đã bị xoá).
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {item.message ? (
              <Button variant="outline" size="sm" onClick={copy}>
                <Copy aria-hidden="true" />
                Chép
              </Button>
            ) : null}

            {/*
              "Đã gửi tay" — **ghi lại** việc con người đã làm, không gửi gì.
              Nhãn nói đúng hành động để không ai hiểu nhầm là hệ thống gửi hộ.
            */}
            {open ? (
              <>
                <Button
                  size="sm"
                  loading={markSent.isPending}
                  onClick={() =>
                    markSent.mutate(item.id, {
                      onSuccess: (data) => toast.success(data.message),
                      onError: (error) => toast.error(errorMessage(error)),
                    })
                  }
                >
                  <Check aria-hidden="true" />
                  Tôi đã gửi tay
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  loading={discard.isPending}
                  onClick={() =>
                    discard.mutate(item.id, {
                      onSuccess: (data) => toast.info(data.message),
                      onError: (error) => toast.error(errorMessage(error)),
                    })
                  }
                >
                  <Trash2 aria-hidden="true" />
                  Bỏ nháp
                </Button>
              </>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </li>
  )
}
