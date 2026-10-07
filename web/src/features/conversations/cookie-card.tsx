import { AlertTriangle, Cookie, Trash2 } from 'lucide-react'
import * as React from 'react'

import { useToast } from '@/components/toast-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Textarea } from '@/components/ui/field'
import { errorMessage } from '@/lib/api'

import { useCookieStatus, useDeleteCookie, useSaveCookie } from './hooks'

/**
 * Cookie Facebook của **chính người vận hành** (task.md X.2).
 *
 * Vì sao có: đo thật (I-31, I-33) cho thấy Facebook **che caption và nội dung
 * bài viết** với khách chưa đăng nhập — kể cả bài để Công khai. Không có cookie
 * thì hệ thống chỉ đọc được tên + ảnh, nên gợi ý tin nhắn mất hẳn một nguồn.
 *
 * Vì sao nguy hiểm, và vì sao cảnh báo đặt **trên** ô nhập: cookie cho hệ thống
 * đọc Facebook dưới danh nghĩa tài khoản của họ. Cảnh báo đặt dưới nút Lưu thì
 * người ta đã dán xong mới đọc.
 */
export function CookieCard() {
  const toast = useToast()
  const status = useCookieStatus()
  const save = useSaveCookie()
  const remove = useDeleteCookie()

  const [draft, setDraft] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)

  const info = status.data

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault()
    const value = draft.trim()
    if (!value) {
      setError('Hãy dán giá trị cookie bạn sao chép từ trình duyệt.')
      return
    }
    setError(null)
    save.mutate(value, {
      onSuccess: (saved) => {
        // Xoá bản nháp ngay — từ đây không còn cookie nào trong bộ nhớ trang.
        setDraft('')
        toast.success(
          saved.alive
            ? `Đã lưu cookie (${saved.masked_account}) và xác nhận còn đăng nhập được.`
            : `Đã lưu cookie (${saved.masked_account}), nhưng ping thử KHÔNG đăng nhập được — có thể đã hết hạn.`,
        )
      },
      onError: (apiError) => setError(errorMessage(apiError)),
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <span className="flex items-center gap-2">
            <Cookie className="size-4" aria-hidden="true" />
            Cookie Facebook (tuỳ chọn)
          </span>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          Không có cookie, Facebook <strong>che tiêu đề và nội dung bài viết</strong> với khách chưa
          đăng nhập — kể cả bài để chế độ Công khai. Có cookie thì gợi ý tin nhắn bám được vào nội
          dung bài đăng, không chỉ vào ảnh.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {/* Cảnh báo đặt TRƯỚC ô nhập, không phải sau. */}
        <p className="flex items-start gap-2 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <span>{info?.risk_warning ?? 'Đang tải cảnh báo rủi ro…'}</span>
        </p>

        {info?.is_set ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success" icon={Cookie}>
              Đã lưu cookie {info.masked_account}
            </Badge>
            {info.names.length > 0 ? <Badge tone="neutral">{info.names.join(', ')}</Badge> : null}
            <Button
              variant="outline"
              size="sm"
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(undefined, {
                  onSuccess: (data) => toast.success(data.message),
                  onError: (apiError) => toast.error(errorMessage(apiError)),
                })
              }
            >
              <Trash2 aria-hidden="true" />
              Xoá cookie
            </Button>
          </div>
        ) : null}

        <form className="flex flex-col gap-3" onSubmit={handleSave}>
          <Field
            id="fb-cookie"
            label={info?.is_set ? 'Thay bằng cookie mới' : 'Cookie của chính bạn'}
            error={error}
            hint="Mở facebook.com đã đăng nhập → DevTools → tab Network → chọn một request → sao chép toàn bộ giá trị của header Cookie. Bắt buộc có c_user và xs."
          >
            {(fieldProps) => (
              <Textarea
                {...fieldProps}
                rows={3}
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  if (error) setError(null)
                }}
                placeholder="datr=...; sb=...; c_user=...; xs=..."
                autoComplete="off"
                spellCheck={false}
                className="font-mono text-xs"
              />
            )}
          </Field>
          <Button type="submit" loading={save.isPending} className="self-start">
            <Cookie aria-hidden="true" />
            Kiểm tra &amp; lưu cookie
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
