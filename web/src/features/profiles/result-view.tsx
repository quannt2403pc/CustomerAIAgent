import { useMutation } from '@tanstack/react-query'
import {
  AlertTriangle,
  Copy,
  Download,
  FileSearch,
  ImageOff,
  MessageSquare,
  MessagesSquare,
  Moon,
} from 'lucide-react'
import * as React from 'react'
import { useNavigate } from 'react-router-dom'

import { useToast } from '@/components/toast-context'
import { Badge, ProfileStatusBadge, SalesCheckBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { EvidenceField, ProfileDetail } from '@/lib/types'
import { useStartConversation } from '@/features/conversations/hooks'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/utils'

/** Nhãn tiếng Việt cho nguồn evidence — trụ truy vết của luật L1. */
const SOURCE_LABEL: Record<string, string> = {
  og_meta: 'Thẻ og: của trang',
  mbasic_html: 'Bản mbasic',
  playwright_dom: 'DOM đã render',
  vision_avatar: 'Mô tả ảnh (AI)',
  manual_paste: 'Người vận hành dán tay',
}

const FIELD_LABEL: Record<string, string> = {
  customer_name: 'Tên khách',
  bio: 'Giới thiệu',
  post_text: 'Nội dung bài viết',
  visual_context: 'Mô tả ảnh',
}

export function ResultView({ profile }: { profile: ProfileDetail }) {
  return (
    <div className="flex flex-col gap-4">
      <SummaryCard profile={profile} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <div className="flex min-w-0 flex-col gap-4">
          <MessagesCard profile={profile} />
          <EveningHookCard profile={profile} />
        </div>
        <EvidenceCard profile={profile} />
      </div>
    </div>
  )
}

function SummaryCard({ profile }: { profile: ProfileDetail }) {
  const demographics = profile.demographics as {
    gender?: string | null
    estimated_age_range?: string | null
    apparent_lifestyle?: string | null
    basis?: Record<string, string>
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>{profile.customer_name ?? 'Không đọc được tên'}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <ProfileStatusBadge status={profile.status} />
            {/*
              Badge "0% chào bán" **chỉ** hiện khi thật sự có nội dung.
              Đây là luật I-21 áp lại ở tầng hiển thị: xác nhận "0% chào bán"
              cho một chuỗi tin nhắn rỗng vừa vô nghĩa vừa làm người đọc tưởng
              nội dung đã được duyệt. Backend đã chặn ở `ValidatedSequence`,
              nhưng bản ghi cũ (chưa có `last_output`) vẫn dựng ra đúng cảnh đó.
            */}
            {profile.messages.length > 0 ? (
              <SalesCheckBadge value={profile.sales_mention_check} />
            ) : null}
            {profile.has_stored_output ? <DownloadJsonButton profileId={profile.id} /> : null}
            <StartConversationButton profileId={profile.id} />
          </div>
        </div>
        <p className="break-all text-sm text-muted-foreground">
          <a
            href={profile.facebook_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2"
          >
            {profile.facebook_url}
          </a>
          <span className="ml-2 tabular">· {formatDateTime(profile.created_at)}</span>
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {/*
          `error_note` là phần quan trọng nhất ở nhánh không đầy đủ: nó nói
          **đọc được tới đâu**. Để nó nhỏ như chú thích là giấu đi sự thật.
        */}
        {profile.error_note ? (
          <p className="flex items-start gap-2 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
            <span>{profile.error_note}</span>
          </p>
        ) : null}

        <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <Detail label="Mô tả ảnh (visual_context)">
            {profile.visual_context ?? <NotKnown reason="Không có ảnh đọc được, hoặc model không đọc được ảnh" />}
          </Detail>
          <Detail label="Góc thấu cảm">
            {profile.core_empathy_angle ?? <NotKnown />}
          </Detail>
          <Detail label="Giới tính (ước lượng)" basis={demographics.basis?.gender}>
            {demographics.gender ?? <NotKnown />}
          </Detail>
          <Detail label="Khoảng tuổi (ước lượng)" basis={demographics.basis?.estimated_age_range}>
            {demographics.estimated_age_range ?? <NotKnown />}
          </Detail>
          <Detail label="Lối sống (ước lượng)" basis={demographics.basis?.apparent_lifestyle}>
            {demographics.apparent_lifestyle ?? <NotKnown />}
          </Detail>
          <Detail label="Model đã dùng">
            <span className="font-mono text-xs">{profile.model ?? '—'}</span>
            {profile.latency_ms ? (
              <span className="tabular text-muted-foreground"> · {profile.latency_ms} ms</span>
            ) : null}
          </Detail>
        </dl>
      </CardContent>
    </Card>
  )
}

/**
 * `null` hiện thành "chưa biết" kèm lý do, **không** hiện ô trống.
 *
 * Luật L1: không có bằng chứng thì để trống — nhưng một ô trống trên UI trông
 * như lỗi hiển thị. Nói thẳng "không có bằng chứng" mới là trung thực.
 */
function NotKnown({ reason }: { reason?: string }) {
  return (
    <span className="text-muted-foreground" title={reason}>
      Không có bằng chứng → để trống
    </span>
  )
}

function Detail({
  label,
  children,
  basis,
}: {
  label: string
  children: React.ReactNode
  basis?: string
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
      {/* `basis` = model đã dựa vào đâu để đoán. Chỉ hiện trên UI, không vào output. */}
      {basis ? <dd className="mt-0.5 text-xs italic text-muted-foreground">Căn cứ: {basis}</dd> : null}
    </div>
  )
}

function DownloadJsonButton({ profileId }: { profileId: string }) {
  /*
   * Tải **tệp**, không in JSON ra console (luật L5, plan.md §7.3.7). Dùng thẻ
   * `<a download>` thường: trình duyệt tự tải, không cần đọc body vào JS.
   */
  return (
    <Button asChild variant="outline" size="sm">
      <a href={`/api/profiles/${profileId}/output.json`} download>
        <Download aria-hidden="true" />
        Tải output.json
      </a>
    </Button>
  )
}

function MessagesCard({ profile }: { profile: ProfileDetail }) {
  const toast = useToast()
  const copyAll = useMutation({
    mutationFn: async () => {
      await navigator.clipboard.writeText(profile.messages.join('\n\n'))
    },
    onSuccess: () => toast.success(`Đã chép ${profile.messages.length} tin nhắn.`),
    onError: () => toast.error('Trình duyệt không cho chép tự động. Hãy bôi đen rồi chép tay.'),
  })

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>
            <span className="flex items-center gap-2">
              <MessageSquare className="size-4" aria-hidden="true" />
              Chuỗi tin nhắn tâm sự ({profile.messages.length})
            </span>
          </CardTitle>
          {profile.messages.length > 0 ? (
            <Button
              variant="outline"
              size="sm"
              loading={copyAll.isPending}
              onClick={() => copyAll.mutate()}
            >
              <Copy aria-hidden="true" />
              Chép tất cả
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {profile.messages.length === 0 && !profile.has_stored_output ? (
          // Dữ liệu cũ ≠ nội dung bị loại. Nói nhầm là vu cho hệ thống một lỗi
          // nó không mắc, và giấu đi việc bản ghi này thật ra đã chạy xong.
          <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">
            Bản ghi này được tạo <strong>trước khi</strong> hệ thống lưu kèm bản JSON kết quả, nên
            không hiện lại được chuỗi tin nhắn. Bấm &quot;Phân tích lại&quot; để sinh bản mới.
          </p>
        ) : profile.messages.length === 0 ? (
          /*
            Ba lý do khác nhau cho cùng một "0 tin nhắn" — nói nhầm là vu cho hệ
            thống một lỗi nó không mắc (task.md I-47):
              · FAILED_VALIDATION → sinh rồi nhưng bị kiểm duyệt loại;
              · PARTIAL_OR_PRIVATE → **chưa sinh gì cả** vì không đủ bằng chứng;
              · ERROR → hỏng giữa chừng.
          */
          <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">
            {profile.status === 'FAILED_VALIDATION' ? (
              <>
                Không có tin nhắn nào. Nội dung sinh ra <strong>không qua được kiểm duyệt</strong>{' '}
                nên hệ thống cố ý không trả về — thà không có còn hơn đưa nội dung chưa duyệt để bạn
                gửi đi.
              </>
            ) : profile.status === 'ERROR' ? (
              <>Lần chạy này hỏng giữa chừng nên chưa sinh được tin nhắn nào. Hãy thử lại.</>
            ) : (
              <>
                Chưa sinh tin nhắn nào vì <strong>không đọc được dữ kiện nào</strong> về người này.
                Hệ thống không viết nội dung khi không có bằng chứng. Hãy dán nội dung trang ở ô
                &quot;Hoặc dán nội dung trang&quot; rồi phân tích lại.
              </>
            )}
          </p>
        ) : (
          <ol className="flex flex-col gap-2">
            {profile.messages.map((message, index) => (
              <li key={index} className="flex gap-2">
                <span className="tabular mt-1.5 w-6 shrink-0 text-right text-xs text-muted-foreground">
                  {index + 1}.
                </span>
                {/* Khung chat: nội dung là thứ người vận hành sẽ copy đi gửi tay. */}
                <p className="min-w-0 flex-1 rounded-lg rounded-tl-none border border-border bg-muted/40 px-3 py-2 text-sm">
                  {message}
                </p>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

function EveningHookCard({ profile }: { profile: ProfileDetail }) {
  const toast = useToast()
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2">
            <Moon className="size-4" aria-hidden="true" />
            Câu chuyện mồi {profile.trigger_time}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {profile.evening_hook_message ? (
          <>
            <p className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
              {profile.evening_hook_message}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => {
                void navigator.clipboard
                  .writeText(profile.evening_hook_message ?? '')
                  .then(() => toast.success('Đã chép câu mồi.'))
                  .catch(() => toast.error('Trình duyệt không cho chép tự động.'))
              }}
            >
              <Copy aria-hidden="true" />
              Chép
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            Chưa có câu mồi nào qua được kiểm duyệt cho profile này.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Lịch {profile.trigger_time} hằng ngày sẽ sinh câu mồi mới vào Outbox dạng nháp. Hệ thống
          không tự gửi — bạn chép rồi tự gửi.
        </p>
      </CardContent>
    </Card>
  )
}

function EvidenceCard({ profile }: { profile: ProfileDetail }) {
  const { evidence } = profile

  return (
    <Card className="xl:sticky xl:top-20 xl:self-start">
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2">
            <FileSearch className="size-4" aria-hidden="true" />
            Bằng chứng
          </span>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Mọi khẳng định ở trên phải truy vết được về một dòng dưới đây.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-1.5">
          {evidence.layers_used.length > 0 ? (
            evidence.layers_used.map((layer) => (
              <Badge key={layer} tone="info">
                {SOURCE_LABEL[layer] ?? layer}
              </Badge>
            ))
          ) : (
            <Badge tone="warning" icon={ImageOff}>
              Không lớp nào đọc được
            </Badge>
          )}
        </div>

        {evidence.blocked_reason ? (
          <p className="rounded border border-warning/40 bg-warning/10 p-2 text-xs">
            {evidence.blocked_reason}
          </p>
        ) : null}

        {evidence.fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">Chưa thu được dữ kiện nào.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {evidence.fields.map((field, index) => (
              <EvidenceRow key={`${field.key}-${index}`} field={field} />
            ))}
          </ul>
        )}

        {evidence.images.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            {evidence.images.length} ảnh đã tải và chuẩn hoá (tên tệp là sha256 của ảnh).
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function EvidenceRow({ field }: { field: EvidenceField }) {
  return (
    <li className="rounded border border-border p-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-xs font-medium">{FIELD_LABEL[field.key] ?? field.key}</span>
        <span className="text-xs text-muted-foreground">
          {SOURCE_LABEL[field.source] ?? field.source}
          {field.confidence !== null ? (
            <span className="tabular"> · độ tin {Math.round(field.confidence * 100)}%</span>
          ) : null}
        </span>
      </div>
      <p className="mt-1 break-words text-sm">{field.value}</p>
      {field.evidence ? (
        // Đoạn **nguyên văn** đã đọc được — thứ `GroundingValidator` đối chiếu.
        <p className="mt-1 break-all font-mono text-[11px] leading-snug text-muted-foreground">
          {field.evidence.length > 220 ? `${field.evidence.slice(0, 220)}…` : field.evidence}
        </p>
      ) : null}
    </li>
  )
}

/**
 * "Bắt đầu phiên làm việc" — lối vào vòng trò chuyện nhiều lượt (task.md X.3).
 *
 * Khác hẳn chuỗi 10 tin bên dưới: chuỗi đó sinh một lần rồi thôi. Phiên trò
 * chuyện đọc được phản hồi của khách và gợi ý lại theo từng lượt.
 *
 * Bấm xong **điều hướng ngay** sang phiên vừa tạo. Lượt gợi ý đầu đã được sinh
 * trong cùng request, nên để người dùng ở lại trang này là để họ nhìn một màn
 * hình không thay đổi gì trong khi việc đã xong ở nơi khác.
 */
function StartConversationButton({ profileId }: { profileId: string }) {
  const toast = useToast()
  const navigate = useNavigate()
  const start = useStartConversation()

  return (
    <Button
      variant="outline"
      size="sm"
      loading={start.isPending}
      onClick={() =>
        start.mutate(profileId, {
          onSuccess: (conversation) => navigate(`/hoi-thoai/${conversation.id}`),
          onError: (error) => toast.error(errorMessage(error)),
        })
      }
    >
      <MessagesSquare aria-hidden="true" />
      Bắt đầu phiên làm việc
    </Button>
  )
}
