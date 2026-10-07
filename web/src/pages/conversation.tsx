import { CheckCheck, ExternalLink, Lightbulb, MessageSquarePlus, Send, X } from 'lucide-react'
import * as React from 'react'
import { useParams } from 'react-router-dom'

import { PageHeader } from '@/components/page-header'
import { useToast } from '@/components/toast-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Textarea } from '@/components/ui/field'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useCloseConversation,
  useConversation,
  useRecordReply,
  useRecordSent,
} from '@/features/conversations/hooks'
import { usePageStatus, useSendViaPage } from '@/features/messenger/hooks'
import { errorMessage } from '@/lib/api'
import type { Conversation, ConversationMessage } from '@/lib/types'
import { cn, formatDateTime } from '@/lib/utils'

export function ConversationPage() {
  const { conversationId } = useParams()
  const id = conversationId ?? null

  // Phan hoi cua khach ve qua webhook o **server**, nen trinh duyet chi biet
  // bang cach hoi lai. Chi bat poll khi webhook that su san sang - poll khi
  // khong co gi se toi chi la goi API vo ich.
  const page = usePageStatus()
  const autoReceive = Boolean(page.data?.is_set && page.data?.webhook_ready)
  const conversation = useConversation(id, { poll: autoReceive })

  return (
    <>
      <PageHeader
        title="Phiên trò chuyện"
        description={
          autoReceive
            ? 'AI gợi ý, bạn chọn và bấm Gửi — tin đi thẳng qua Page. Khách trả lời thì hội thoại tự cập nhật.'
            : 'AI gợi ý, bạn chọn và gửi, rồi dán phản hồi của khách vào để AI gợi ý tiếp.'
        }
      />

      {conversation.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : conversation.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {errorMessage(conversation.error)}
        </p>
      ) : conversation.data ? (
        <ConversationView conversation={conversation.data} autoReceive={autoReceive} />
      ) : null}
    </>
  )
}

function ConversationView({
  conversation,
  autoReceive,
}: {
  conversation: Conversation
  autoReceive: boolean
}) {
  const toast = useToast()
  const [draft, setDraft] = React.useState('')
  const [chosenId, setChosenId] = React.useState<string | null>(null)
  const [reply, setReply] = React.useState('')

  const sendViaPage = useSendViaPage(conversation.id)
  const recordSent = useRecordSent(conversation.id)
  const recordReply = useRecordReply(conversation.id)
  const close = useCloseConversation(conversation.id)

  const closed = conversation.status !== 'active'
  /**
   * `can_send` do **backend** quyết, không phải FE tự suy.
   *
   * Nó đúng khi và chỉ khi hội thoại có `psid` — tức người này đã chủ động nhắn
   * Page trước, điều kiện duy nhất Facebook cho phép gửi. FE tự đoán từ "có
   * có link mở Facebook không" sẽ sai: link đó dựng được từ bất kỳ URL hợp
   * lệ nào, còn quyền gửi thì không.
   */
  const autoSend = conversation.can_send
  const sending = autoSend ? sendViaPage.isPending : recordSent.isPending

  /**
   * Nút **Gửi** — hai đường, chọn theo `can_send`.
   *
   * Đường tự động (`can_send`): gọi Send API, tin đi thẳng. Dùng được vì người
   * nhận đã chủ động nhắn Page — Facebook chỉ cho gửi trong trường hợp đó.
   *
   * Đường thủ công: chép nội dung + mở cuộc trò chuyện, bạn Ctrl+V rồi Enter.
   * Giữ lại vì nó là thứ duy nhất dùng được khi chưa kết nối Page, hoặc khi
   * người này chưa từng nhắn Page.
   */
  const handleSend = () => {
    const text = draft.trim()
    if (!text) return

    if (autoSend) {
      sendViaPage.mutate(
        { text, suggestion_id: chosenId },
        {
          onSuccess: () => {
            setDraft('')
            setChosenId(null)
            toast.success('Đã gửi. Khách trả lời thì hội thoại tự cập nhật.')
          },
          onError: (error) => toast.error(errorMessage(error)),
        },
      )
      return
    }

    /*
     * Thứ tự ở đây **quan trọng** và không được đảo.
     *
     * Cả `window.open` lẫn `navigator.clipboard.writeText` đều đòi "transient
     * user activation" — quyền tạm thời chỉ có ngay sau một cú bấm thật. Bản
     * đầu `await` clipboard **trước** rồi mới `window.open`: sau `await`,
     * activation có thể đã hết và trình duyệt **chặn popup**. Nên cả hai được
     * gọi **đồng bộ ngay trong handler**, không `await` trước chúng; kết quả
     * clipboard xử lý sau bằng `.then`.
     */
    /*
     * Đích mở là **trang cá nhân**, không phải một URL khung chat (task.md I-60).
     *
     * Đã thử ba dạng URL khung chat, đo thật trên phiên đã đăng nhập, cả ba đều
     * hỏng — kể cả `facebook.com/messages/t/<ID số>`. Facebook không còn phơi
     * URL điều hướng được tới chat cá nhân: bấm "Nhắn tin" trên trang profile
     * mở khung chat **ngay trong trang**, URL không đổi.
     */
    const openTarget = conversation.profile_url
    if (openTarget) {
      window.open(openTarget, '_blank', 'noopener,noreferrer')
    }

    void navigator.clipboard
      .writeText(text)
      .then(() => {
        toast.success(
          openTarget
            ? 'Đã chép tin và mở trang cá nhân. Bấm "Nhắn tin", dán (Ctrl+V) rồi Enter.'
            : 'Đã chép tin. Hãy tự mở cuộc trò chuyện rồi dán (Ctrl+V).',
        )
      })
      .catch(() => {
        // Nội dung **không mất**: nó đã nằm trong lịch sử hội thoại bên trên,
        // nên vẫn chép tay được. Nói rõ chỗ lấy lại thay vì chỉ báo lỗi.
        toast.info('Trình duyệt không cho chép tự động — hãy chép tin ở phần lịch sử bên trên.')
      })

    recordSent.mutate(
      { text, suggestion_id: chosenId },
      {
        onSuccess: () => {
          setDraft('')
          setChosenId(null)
        },
        onError: (error) => toast.error(errorMessage(error)),
      },
    )
  }

  const handleReply = () => {
    const text = reply.trim()
    if (!text) return
    recordReply.mutate(
      { text },
      {
        onSuccess: () => {
          setReply('')
          toast.success('Đã ghi phản hồi. AI đang gợi ý tin tiếp theo dựa trên câu đó.')
        },
        onError: (error) => toast.error(errorMessage(error)),
      },
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
      <div className="flex min-w-0 flex-col gap-4">
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              {/*
                `||` chứ không `??`: backend trả chuỗi **rỗng** khi chưa biết
                tên, không trả `null`, nên `??` sẽ để lọt một tiêu đề trắng.
                Và hai nguyên nhân "không có tên" cần hai câu khác nhau — gộp
                lại thì người vận hành không biết nên đi phân tích profile hay
                đi sửa kết nối Page.
              */}
              <CardTitle>
                {conversation.customer_name ||
                  (conversation.profile_id
                    ? 'Không đọc được tên'
                    : 'Khách từ Messenger (chưa gán profile)')}
              </CardTitle>
              <div className="flex items-center gap-2">
                <Badge tone={closed ? 'neutral' : 'success'}>
                  {closed ? 'Đã đóng' : 'Đang mở'}
                </Badge>
                {!closed ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={close.isPending}
                    onClick={() =>
                      close.mutate(undefined, {
                        onSuccess: (data) => toast.info(data.message),
                        onError: (error) => toast.error(errorMessage(error)),
                      })
                    }
                  >
                    <X aria-hidden="true" />
                    Đóng phiên
                  </Button>
                ) : null}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Bắt đầu {formatDateTime(conversation.created_at)}
            </p>
          </CardHeader>
          <CardContent>
            <Transcript messages={conversation.messages} />
          </CardContent>
        </Card>

        {!closed ? (
          <Card>
            <CardHeader>
              <CardTitle>Soạn tin gửi đi</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Field
                id="compose"
                label="Nội dung sẽ gửi"
                hint="Bấm một gợi ý bên phải để điền sẵn, rồi sửa tuỳ ý trước khi gửi."
              >
                {(fieldProps) => (
                  <Textarea
                    {...fieldProps}
                    rows={3}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder="Chọn một gợi ý hoặc tự viết…"
                  />
                )}
              </Field>

              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={handleSend} loading={sending} disabled={!draft.trim()}>
                  <Send aria-hidden="true" />
                  {autoSend ? 'Gửi' : 'Gửi qua Messenger'}
                </Button>
                {/*
                  Hai đường khác nhau, nhãn cũng phải khác nhau (task.md I-58):
                  "Mở khung chat" vào thẳng cuộc trò chuyện; "Mở trang cá nhân"
                  thì người vận hành còn phải bấm "Nhắn tin" một lần nữa. Dùng
                  chung một nhãn thì lần thứ hai họ sẽ tưởng hệ thống hỏng.
                */}
                {!autoSend && conversation.profile_url ? (
                  <Button asChild variant="outline" size="sm">
                    <a href={conversation.profile_url} target="_blank" rel="noopener noreferrer">
                      <ExternalLink aria-hidden="true" />
                      Mở trang cá nhân
                    </a>
                  </Button>
                ) : null}
              </div>

              {/*
                Nói **thẳng** cơ chế đang dùng. Để người dùng tưởng hệ thống tự
                gửi trong khi nó không, hay ngược lại, đều là hiểu nhầm nguy
                hiểm nhất của cả sản phẩm.
              */}
              {autoSend ? (
                <p className="text-xs text-muted-foreground">
                  Bấm &quot;Gửi&quot; là tin <strong>đi thẳng</strong> qua Page của bạn. Gửi được vì
                  người này đã chủ động nhắn Page trước.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Người này <strong>chưa nhắn Page của bạn</strong>, nên Facebook không cho gửi tự
                  động. Bấm &quot;Gửi&quot; sẽ <strong>chép nội dung</strong> và mở Facebook ở tab
                  mới — bạn dán (Ctrl+V) rồi Enter.
                  {conversation.profile_url ? (
                    <>
                      {' '}
                      Hệ thống mở <strong>trang cá nhân</strong> của họ — bạn bấm{' '}
                      <strong>Nhắn tin</strong> ở đó. Facebook không còn cho mở thẳng khung chat
                      bằng một đường link.
                    </>
                  ) : (
                    <> Không dựng được link nào từ URL này, nên bạn cần tự mở cuộc trò chuyện.</>
                  )}
                </p>
              )}
            </CardContent>
          </Card>
        ) : null}

        {!closed ? (
          <Card>
            <CardHeader>
              <CardTitle>Phản hồi của khách</CardTitle>
              {autoReceive ? (
                <Badge tone="success" icon={CheckCheck}>
                  Tự nhận qua Page
                </Badge>
              ) : null}
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Field
                id="reply"
                label="Dán câu trả lời của họ"
                hint={
                  autoReceive
                    ? 'Thường không cần: phản hồi của khách tự về qua Page. Ô này để dành cho tin bạn nhận ở nơi khác.'
                    : 'Chép nguyên văn từ Messenger. AI sẽ đọc câu này để gợi ý tin tiếp theo.'
                }
              >
                {(fieldProps) => (
                  <Textarea
                    {...fieldProps}
                    rows={2}
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    placeholder="Họ vừa trả lời gì?"
                  />
                )}
              </Field>
              <Button
                variant="outline"
                onClick={handleReply}
                loading={recordReply.isPending}
                disabled={!reply.trim()}
                className="self-start"
              >
                <MessageSquarePlus aria-hidden="true" />
                Ghi phản hồi &amp; gợi ý tiếp
              </Button>
            </CardContent>
          </Card>
        ) : null}
      </div>

      <SuggestionPanel
        conversation={conversation}
        busy={recordReply.isPending}
        onPick={(text, id) => {
          setDraft(text)
          setChosenId(id)
        }}
      />
    </div>
  )
}

function Transcript({ messages }: { messages: ConversationMessage[] }) {
  if (messages.length === 0) {
    return (
      <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">
        Chưa có lượt nào. Chọn một gợi ý, gửi đi, rồi dán phản hồi của họ vào.
      </p>
    )
  }

  return (
    <ol className="flex flex-col gap-2">
      {messages.map((message) => {
        const mine = message.role === 'operator'
        return (
          <li key={message.id} className={cn('flex', mine ? 'justify-end' : 'justify-start')}>
            <div
              className={cn(
                'max-w-[85%] rounded-lg px-3 py-2 text-sm',
                mine
                  ? 'rounded-br-none bg-primary/10 text-foreground'
                  : 'rounded-bl-none border border-border bg-muted/40',
              )}
            >
              {/* Nhãn vai bằng chữ, không chỉ bằng vị trí/màu (plan.md §6.2). */}
              <span className="mb-0.5 block text-[11px] font-medium text-muted-foreground">
                {mine ? 'Bạn đã gửi' : 'Khách trả lời'} · {formatDateTime(message.created_at)}
              </span>
              {message.text}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function SuggestionPanel({
  conversation,
  busy,
  onPick,
}: {
  conversation: Conversation
  busy: boolean
  onPick: (text: string, id: string) => void
}) {
  return (
    <Card className="xl:sticky xl:top-20 xl:self-start">
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2">
            <Lightbulb className="size-4" aria-hidden="true" />
            Gợi ý lượt {conversation.suggestion_round}
          </span>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Bấm một câu để điền vào ô soạn. Mọi gợi ý đã qua kiểm duyệt 0% chào bán và kiểm chứng bằng
          chứng.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {busy ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : conversation.suggestions.length === 0 ? (
          <p className="rounded border border-dashed border-border p-3 text-sm text-muted-foreground">
            {conversation.suggestion_note || 'Chưa có gợi ý nào cho lượt này.'}
          </p>
        ) : (
          conversation.suggestions.map((suggestion) => (
            <button
              key={suggestion.id}
              type="button"
              onClick={() => onPick(suggestion.text, suggestion.id)}
              className={cn(
                'cursor-pointer rounded-lg border p-3 text-left text-sm transition-colors',
                'hover:border-primary hover:bg-primary/5',
                suggestion.chosen ? 'border-success/50 bg-success/5' : 'border-border',
              )}
            >
              {suggestion.text}
              {suggestion.chosen ? (
                <span className="mt-1.5 flex items-center gap-1 text-xs text-success">
                  <CheckCheck className="size-3.5" aria-hidden="true" />
                  Đã dùng câu này
                </span>
              ) : null}
            </button>
          ))
        )}
      </CardContent>
    </Card>
  )
}
