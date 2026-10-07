import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  Facebook,
  Trash2,
} from 'lucide-react'
import * as React from 'react'

import { useToast } from '@/components/toast-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/field'
import { errorMessage } from '@/lib/api'

import { PageGuide } from './page-guide'
import { useDeletePageToken, usePageStatus, useSavePageToken } from './hooks'

/**
 * Kết nối Facebook Page để gửi/nhận tin **tự động** (task.md X.6 + X.7).
 *
 * Thẻ này có ba trạng thái rõ rệt, và việc tách chúng là phần quan trọng nhất
 * (bài học I-46/I-47 — gộp các nguyên nhân khác nhau vào một thông điệp làm
 * người vận hành đi sửa sai chỗ):
 *
 * 1. Chưa có token → hiện hướng dẫn **mở sẵn**, vì chắc chắn họ cần nó.
 * 2. Có token nhưng Facebook không nhận → nói rõ nghi vấn (hết hạn / dán token
 *    User thay vì Page), giữ hướng dẫn mở.
 * 3. Token tốt nhưng chưa đủ webhook → gửi được, **chưa** nhận tự động được.
 *    Đây là trạng thái dễ bị tưởng là "xong" nhất, nên nó phải tự nói ra.
 */
export function PageCard() {
  const toast = useToast()
  const status = usePageStatus()
  const save = useSavePageToken()
  const remove = useDeletePageToken()

  const [draft, setDraft] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [guideOpen, setGuideOpen] = React.useState<boolean | null>(null)

  const info = status.data
  const ready = Boolean(info?.is_set && info?.page_name && info?.webhook_ready)
  // Mặc định: mở hướng dẫn khi chưa sẵn sàng. `null` = người dùng chưa tự bấm,
  // nên tôn trọng lựa chọn của họ ngay khi họ bấm lần đầu.
  const showGuide = guideOpen ?? !ready

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault()
    const value = draft.trim()
    if (!value) {
      setError('Hãy dán Page Access Token lấy ở bước 4.')
      return
    }
    setError(null)
    save.mutate(value, {
      onSuccess: (saved) => {
        // Xoá nháp ngay — từ đây không còn token nào nằm trong bộ nhớ trang.
        setDraft('')
        toast.success(
          saved.webhook_ready
            ? `Đã kết nối Page “${saved.page_name}”. Gửi và nhận tự động đều đã bật.`
            : `Đã kết nối Page “${saved.page_name}”. Gửi được rồi; còn thiếu cấu hình webhook để nhận phản hồi tự động.`,
        )
      },
      onError: (apiError) => setError(errorMessage(apiError)),
    })
  }

  const handleRemove = () => {
    remove.mutate(undefined, {
      onSuccess: (result) => toast.success(result.message),
      onError: (apiError) => toast.error(errorMessage(apiError)),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2">
            <Facebook className="size-4 text-secondary" aria-hidden="true" />
            Kết nối Facebook Page
          </span>
        </CardTitle>
        {info ? (
          <Badge
            tone={ready ? 'success' : info.is_set ? 'warning' : 'neutral'}
            icon={ready ? CheckCircle2 : info.is_set ? AlertTriangle : CircleDashed}
          >
            {ready ? 'Gửi & nhận tự động' : info.is_set ? 'Chưa hoàn tất' : 'Chưa kết nối'}
          </Badge>
        ) : null}
      </CardHeader>

      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Kết nối Page để bấm <strong>Gửi</strong> là tin đi thẳng, và khi khách trả lời thì hội
          thoại tự cập nhật — không phải copy tay.
        </p>

        {info?.page_name ? (
          <p className="text-sm text-foreground">
            Page đang kết nối: <strong>{info.page_name}</strong>
            {info.hint ? <span className="text-muted-foreground"> · token {info.hint}</span> : null}
          </p>
        ) : null}

        {info?.blocker ? (
          <p className="rounded border border-warning/40 bg-warning/5 px-3 py-2 text-sm text-foreground">
            {info.blocker}
          </p>
        ) : null}

        {ready ? (
          <p className="rounded border border-success/40 bg-success/5 px-3 py-2 text-sm text-foreground">
            Đã sẵn sàng. Nhắc lại giới hạn của Facebook: chỉ gửi được cho người đã chủ động nhắn
            Page, trong 7 ngày kể từ tin cuối của họ.
          </p>
        ) : null}

        <form onSubmit={handleSave} className="space-y-3">
          <Field
            id="page-token"
            label={info?.is_set ? 'Thay bằng Page Access Token mới' : 'Page Access Token'}
            error={error}
            hint="Lấy ở bước 4 bên dưới. Lưu mã hoá at-rest; hệ thống không bao giờ hiện lại giá trị."
          >
            {(fieldProps) => (
              <Input
                {...fieldProps}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  if (error) setError(null)
                }}
                placeholder={info?.is_set ? 'Dán token mới để thay thế' : 'EAAG…'}
              />
            )}
          </Field>

          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={save.isPending}>
              {info?.is_set ? 'Thay token' : 'Kết nối Page'}
            </Button>
            {info?.is_set ? (
              <Button
                type="button"
                variant="outline"
                onClick={handleRemove}
                loading={remove.isPending}
              >
                <Trash2 aria-hidden="true" />
                Ngắt kết nối
              </Button>
            ) : null}
          </div>
        </form>

        <div className="border-t border-border pt-3">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={showGuide}
            aria-controls="page-guide"
            onClick={() => setGuideOpen(!showGuide)}
          >
            {showGuide ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
            {showGuide ? 'Ẩn hướng dẫn' : 'Chưa có Page? Xem hướng dẫn từng bước'}
          </Button>

          {showGuide ? (
            <div id="page-guide" className="mt-4">
              <PageGuide webhookUrl={info?.webhook_url ?? ''} />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
