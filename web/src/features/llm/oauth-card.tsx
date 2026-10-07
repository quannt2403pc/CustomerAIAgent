import { ChevronDown, ExternalLink, LogIn, Unplug } from 'lucide-react'
import * as React from 'react'

import { useToast } from '@/components/toast-context'
import { ConnectionBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/field'
import { errorMessage } from '@/lib/api'
import type { LlmStatus } from '@/lib/types'

import {
  useCancelOAuth,
  useDisconnect,
  useOAuthStatus,
  useStartOAuth,
  useSubmitCallback,
} from './hooks'

/** CLIProxy chỉ giữ `state` 5 phút — dừng poll đúng lúc đó, không chờ vô hạn. */
const TIMEOUT_MS = 5 * 60 * 1000

export function OAuthCard({ status }: { status: LlmStatus | undefined }) {
  const toast = useToast()
  const [state, setState] = React.useState<string | null>(null)
  const [expired, setExpired] = React.useState(false)
  const [showFallback, setShowFallback] = React.useState(false)
  const [callbackUrl, setCallbackUrl] = React.useState('')
  const [callbackError, setCallbackError] = React.useState<string | null>(null)

  const start = useStartOAuth()
  const cancel = useCancelOAuth()
  const disconnect = useDisconnect()
  const submitCallback = useSubmitCallback()

  const waiting = Boolean(state) && !expired
  const poll = useOAuthStatus(state, waiting)

  /** Dừng poll khi hết 5 phút. Đồng hồ gắn với `state` nên mỗi phiên một lần đếm. */
  React.useEffect(() => {
    if (!state) return
    const timer = window.setTimeout(() => setExpired(true), TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [state])

  /**
   * Kết thúc phiên khi CLIProxy báo xong.
   *
   * Badge "Đã kết nối" đọc từ `connected` (nguồn là `auth-files`), **không** từ
   * `status === 'ok'` — bẫy B6: gọi thiếu `state` thì `get-auth-status` trả "ok"
   * dù chưa đăng nhập bao giờ.
   */
  React.useEffect(() => {
    const data = poll.data
    if (!data || data.status === 'wait') return

    if (data.status === 'ok' && data.connected) {
      toast.success(data.message)
    } else {
      toast.error(data.message)
    }
    setState(null)
    setExpired(false)
  }, [poll.data, toast])

  const handleStart = () => {
    start.mutate(undefined, {
      onSuccess: (data) => {
        setState(data.state)
        setExpired(false)
        setShowFallback(false)
        /*
         * `noopener,noreferrer` là bắt buộc: không có nó, tab Google giữ được
         * `window.opener` và có thể điều hướng tab của ta đi nơi khác.
         */
        const opened = window.open(data.url, '_blank', 'noopener,noreferrer')
        if (!opened) {
          // Trình duyệt chặn popup → vẫn phải có đường đi tiếp, không bế tắc.
          toast.info('Trình duyệt chặn cửa sổ mới. Hãy bấm "Mở trang đăng nhập Google" bên dưới.')
        }
      },
      onError: (error) => toast.error(errorMessage(error)),
    })
  }

  const handleCancel = () => {
    const current = state
    setState(null)
    setExpired(false)
    if (current) {
      cancel.mutate(current, {
        onSuccess: (data) => toast.info(data.message),
        onError: (error) => toast.error(errorMessage(error)),
      })
    }
  }

  const handleSubmitCallback = (event: React.FormEvent) => {
    event.preventDefault()
    if (!state) {
      setCallbackError('Phiên đăng nhập đã đóng. Hãy bấm "Đăng nhập Google" để mở phiên mới.')
      return
    }
    if (!callbackUrl.trim()) {
      setCallbackError('Hãy dán URL bạn thấy trên thanh địa chỉ sau khi đồng ý ở Google.')
      return
    }
    setCallbackError(null)
    submitCallback.mutate(
      { state, url: callbackUrl.trim() },
      {
        onSuccess: (data) => {
          toast.success(data.message)
          setCallbackUrl('')
        },
        // Lỗi hiện **cạnh field**, không chỉ ở toast (plan.md §6.2).
        onError: (error) => setCallbackError(errorMessage(error)),
      },
    )
  }

  const connected = Boolean(status?.connected) && status?.provider === 'antigravity'

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {status?.provider === 'antigravity' ? (
          <ConnectionBadge
            connected={Boolean(status.connected)}
            reachable={Boolean(status.reachable)}
            account={status.account}
          />
        ) : null}
      </div>

      {waiting ? (
        <div
          className="rounded border border-primary/30 bg-primary/5 p-3 text-sm"
          // Trạng thái chờ đổi theo thời gian → báo cho screen reader.
          role="status"
          aria-live="polite"
        >
          <p className="font-medium">Đang chờ bạn đồng ý ở cửa sổ Google…</p>
          <p className="mt-1 text-muted-foreground">
            Sau khi đồng ý, trang này tự nhận kết quả. Phiên đăng nhập hết hạn sau 5 phút.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={handleCancel} loading={cancel.isPending}>
              Huỷ phiên đăng nhập
            </Button>
          </div>
        </div>
      ) : null}

      {expired ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          Phiên đăng nhập đã quá 5 phút và bị đóng. Hãy bấm "Đăng nhập Google" để mở phiên mới.
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Button onClick={handleStart} loading={start.isPending} disabled={waiting}>
          <LogIn aria-hidden="true" />
          {connected ? 'Đăng nhập lại' : 'Đăng nhập Google'}
        </Button>

        {start.data && waiting ? (
          <Button asChild variant="outline">
            <a href={start.data.url} target="_blank" rel="noopener noreferrer">
              <ExternalLink aria-hidden="true" />
              Mở trang đăng nhập Google
            </a>
          </Button>
        ) : null}

        {connected ? (
          <Button
            variant="outline"
            loading={disconnect.isPending}
            onClick={() =>
              disconnect.mutate(undefined, {
                onSuccess: (data) => toast.success(data.message),
                onError: (error) => toast.error(errorMessage(error)),
              })
            }
          >
            <Unplug aria-hidden="true" />
            Ngắt kết nối
          </Button>
        ) : null}
      </div>

      {/*
        Đường dự phòng (bẫy B1): Google chuyển hướng về `localhost:51121`; nếu
        cổng đó không mở được thì token không bao giờ được lưu. Dùng `<details>`
        để nó ẩn đi nhưng **vẫn điều hướng được bằng bàn phím**, thay vì một nút
        tự dựng phải tự lo aria-expanded.
      */}
      <details
        className="rounded border border-border bg-muted/40 p-3"
        open={showFallback}
        onToggle={(event) => setShowFallback((event.target as HTMLDetailsElement).open)}
      >
        <summary className="flex cursor-pointer items-center gap-1 text-sm font-medium">
          <ChevronDown className="size-4 transition-transform" aria-hidden="true" />
          Gặp lỗi khi Google quay về?
        </summary>
        <form className="mt-3 flex flex-col gap-3" onSubmit={handleSubmitCallback}>
          <p className="text-sm text-muted-foreground">
            Nếu sau khi đồng ý mà trình duyệt báo lỗi không mở được trang, hãy sao chép{' '}
            <strong>toàn bộ</strong> URL trên thanh địa chỉ rồi dán vào đây.
          </p>
          <Field
            id="callback-url"
            label="URL callback"
            error={callbackError}
            hint="Dạng http://localhost:51121/oauth-callback?state=…&code=… — hệ thống tự bóc mã từ URL."
          >
            {(fieldProps) => (
              <Input
                {...fieldProps}
                type="url"
                value={callbackUrl}
                onChange={(event) => {
                  setCallbackUrl(event.target.value)
                  if (callbackError) setCallbackError(null)
                }}
                placeholder="http://localhost:51121/oauth-callback?..."
                autoComplete="off"
              />
            )}
          </Field>
          <Button type="submit" variant="outline" loading={submitCallback.isPending}>
            Nạp URL callback
          </Button>
        </form>
      </details>
    </div>
  )
}
