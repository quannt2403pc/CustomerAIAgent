import { Eye, EyeOff, KeyRound, Trash2 } from 'lucide-react'
import * as React from 'react'

import { useToast } from '@/components/toast-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/field'
import { errorMessage } from '@/lib/api'
import type { LlmStatus } from '@/lib/types'

import { useDeleteApiKey, useSaveApiKey } from './hooks'

/**
 * Cổng B — Google API Key.
 *
 * Quy tắc về key, không thương lượng (plan.md §5.1.3):
 *
 * - Key **chỉ** nằm trong `useState` của form, và bị **xoá ngay** sau khi lưu
 *   thành công. Sau đó không còn bản sao nào trong DOM — thứ duy nhất hiển thị
 *   là `hint` (4 ký tự cuối) do **backend** trả về.
 * - Không `defaultValue`/`value` nào được nạp lại key đã lưu: API không có
 *   đường trả key về, và FE cũng không được giữ hộ.
 * - `autoComplete="off"` + `spellCheck={false}`: không để trình duyệt lưu vào
 *   kho autofill hay gửi đi kiểm tra chính tả.
 */
export function ApiKeyCard({ status }: { status: LlmStatus | undefined }) {
  const toast = useToast()
  const [draft, setDraft] = React.useState('')
  const [revealed, setRevealed] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const save = useSaveApiKey()
  const remove = useDeleteApiKey()
  const info = status?.api_key

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault()
    const value = draft.trim()
    if (value.length < 8) {
      setError('Key quá ngắn. Hãy dán đủ key bạn lấy từ Google AI Studio.')
      return
    }
    setError(null)
    save.mutate(value, {
      onSuccess: (saved) => {
        // Xoá bản nháp ngay: từ đây trở đi không còn key nào trong bộ nhớ trang.
        setDraft('')
        setRevealed(false)
        toast.success(`Đã lưu và xác thực API key (${saved.hint}).`)
      },
      onError: (apiError) => setError(errorMessage(apiError)),
    })
  }

  return (
    <div className="flex flex-col gap-3">
      {info?.is_set ? (
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="success" icon={KeyRound}>
            Đã lưu key {info.hint}
          </Badge>
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
            Xoá key
          </Button>
        </div>
      ) : null}

      <form className="flex flex-col gap-3" onSubmit={handleSave}>
        <Field
          id="google-api-key"
          label={info?.is_set ? 'Thay bằng key mới' : 'Google API key'}
          error={error}
          required={!info?.is_set}
          hint="Hệ thống gọi thử Google để xác thực key TRƯỚC khi lưu, và lưu dưới dạng mã hoá. Key không bao giờ được trả lại cho giao diện."
        >
          {(fieldProps) => (
            <div className="flex gap-2">
              <Input
                {...fieldProps}
                type={revealed ? 'text' : 'password'}
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  if (error) setError(null)
                }}
                placeholder="Dán key vào đây"
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
              />
              <Button
                type="button"
                variant="outline"
                size="icon"
                onClick={() => setRevealed((value) => !value)}
                aria-label={revealed ? 'Ẩn key' : 'Hiện key'}
                aria-pressed={revealed}
              >
                {revealed ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
              </Button>
            </div>
          )}
        </Field>
        <Button type="submit" loading={save.isPending} className="self-start">
          <KeyRound aria-hidden="true" />
          Xác thực &amp; lưu key
        </Button>
      </form>
    </div>
  )
}
