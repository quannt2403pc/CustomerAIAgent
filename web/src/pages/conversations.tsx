import { MessageCircle, MessagesSquare } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useConversations } from '@/features/conversations/hooks'
import { usePageStatus } from '@/features/messenger/hooks'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

/**
 * Danh sách phiên trò chuyện.
 *
 * Trang này quan trọng hơn vẻ ngoài của nó: khi đã kết nối Page, một người lạ
 * nhắn Page sẽ tạo ra hội thoại **ở đây** mà không ai bấm gì cả (task.md X.6).
 * Không có trang này thì tin thật của khách rơi vào DB và không ai thấy.
 *
 * Vì thế nó tự làm mới định kỳ khi webhook đang bật — và chỉ khi đó.
 */
export function ConversationsPage() {
  const page = usePageStatus()
  const autoReceive = Boolean(page.data?.is_set && page.data?.webhook_ready)
  const conversations = useConversations({ poll: autoReceive })

  return (
    <>
      <PageHeader
        title="Hội thoại"
        description={
          autoReceive
            ? 'Khách nhắn Page của bạn sẽ tự xuất hiện ở đây, kèm gợi ý trả lời.'
            : 'Các phiên trò chuyện đang mở. Bắt đầu một phiên từ trang Phân tích.'
        }
      />

      {conversations.isPending ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : conversations.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {errorMessage(conversations.error)}
        </p>
      ) : conversations.data && conversations.data.items.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {conversations.data.items.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">
                  {item.customer_name || 'Khách chưa gán profile'}
                </p>
                <p className="text-xs text-muted-foreground">
                  {item.message_count} tin ·{' '}
                  {item.last_message_at
                    ? `tin cuối ${formatDateTime(item.last_message_at)}`
                    : `mở ${formatDateTime(item.created_at)}`}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge tone={item.status === 'active' ? 'success' : 'neutral'}>
                  {item.status === 'active' ? 'Đang mở' : 'Đã đóng'}
                </Badge>
                <Button asChild variant="outline" size="sm">
                  <Link to={`/hoi-thoai/${item.id}`}>
                    <MessageCircle aria-hidden="true" />
                    Mở
                  </Link>
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState
          icon={MessagesSquare}
          title="Chưa có phiên trò chuyện nào"
          description={
            autoReceive
              ? 'Khi một khách nhắn Page của bạn, hội thoại sẽ tự xuất hiện ở đây. Bạn cũng có thể chủ động mở phiên từ một profile đã phân tích.'
              : 'Phân tích một profile Facebook rồi bấm "Bắt đầu phiên làm việc" để AI gợi ý tin nhắn mở đầu.'
          }
          action={
            <Button asChild variant="outline">
              <Link to="/phan-tich">Tới trang Phân tích</Link>
            </Button>
          }
        />
      )}
    </>
  )
}
