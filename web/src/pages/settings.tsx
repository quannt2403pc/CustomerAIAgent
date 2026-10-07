import * as RadioGroup from '@radix-ui/react-radio-group'
import { KeyRound, ShieldCheck } from 'lucide-react'

import { PageHeader } from '@/components/page-header'
import { useToast } from '@/components/toast-context'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiKeyCard } from '@/features/llm/api-key-card'
import { useLlmStatus, useSetProvider } from '@/features/llm/hooks'
import { ModelPicker } from '@/features/llm/model-picker'
import { CookieCard } from '@/features/conversations/cookie-card'
import { OAuthCard } from '@/features/llm/oauth-card'
import { PageCard } from '@/features/messenger/page-card'
import { errorMessage } from '@/lib/api'
import type { ProviderName } from '@/lib/types'
import { cn } from '@/lib/utils'

const PROVIDERS: {
  value: ProviderName
  title: string
  description: string
  icon: typeof ShieldCheck
}[] = [
  {
    value: 'antigravity',
    title: 'Đăng nhập Google (Antigravity qua CLIProxy)',
    description:
      'Hạn mức rộng hơn, hợp cho chạy thật: một lần phân tích gọi model 7–14 lượt. Cần CLIProxy đang chạy.',
    icon: ShieldCheck,
  },
  {
    value: 'google_api_key',
    title: 'Dùng Google API Key',
    description:
      'Cài nhanh nhất, không cần Docker hay CLIProxy. Hạn mức bản miễn phí dễ hết khi chạy trọn pipeline.',
    icon: KeyRound,
  },
]

export function SettingsPage() {
  const toast = useToast()
  const status = useLlmStatus()
  const setProvider = useSetProvider()

  const current = status.data?.provider ?? ''

  const handleChange = (value: string) => {
    setProvider.mutate(value as ProviderName, {
      onSuccess: (next) =>
        toast.info(
          next.must_choose_model
            ? 'Đã đổi cổng. Danh mục model của hai cổng khác nhau nên bạn cần chọn lại model.'
            : 'Đã đổi cổng model.',
        ),
      onError: (error) => toast.error(errorMessage(error)),
    })
  }

  return (
    <>
      <PageHeader
        title="Cài đặt → Cổng AI"
        description="Chọn nơi hệ thống gọi model, rồi chọn model sẽ dùng. Danh mục model luôn lấy trực tiếp từ cổng đang chọn."
      />

      {status.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : null}

      {status.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {errorMessage(status.error)}
        </p>
      ) : null}

      {status.data ? (
        <div className="flex flex-col gap-5">
          {/*
            Radio group thật (Radix), không phải hai `<div onClick>`: nhóm radio
            cho sẵn điều hướng bằng phím mũi tên và quan hệ "chọn một trong
            nhiều" mà screen reader đọc đúng.
          */}
          <RadioGroup.Root
            value={current}
            onValueChange={handleChange}
            aria-label="Chọn cổng model"
            className="grid gap-3 lg:grid-cols-2"
            disabled={setProvider.isPending}
          >
            {PROVIDERS.map((provider) => {
              const active = current === provider.value
              return (
                <RadioGroup.Item
                  key={provider.value}
                  value={provider.value}
                  className={cn(
                    'cursor-pointer rounded-lg border-2 bg-surface p-4 text-left transition-colors',
                    active
                      ? 'border-primary bg-primary/5'
                      : 'border-border hover:border-input-border',
                  )}
                >
                  <div className="flex items-start gap-3">
                    {/*
                      Nút tròn vẽ tay: Radix `Item` đã mang role/aria-checked, nên
                      phần này chỉ là hình. Trạng thái chọn **không** chỉ báo bằng
                      màu — có cả chấm tròn và viền dày (plan.md §6.2).
                    */}
                    <span
                      aria-hidden="true"
                      className={cn(
                        'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border-2',
                        active ? 'border-primary' : 'border-input-border',
                      )}
                    >
                      {active ? <span className="size-2.5 rounded-full bg-primary" /> : null}
                    </span>
                    <div className="min-w-0">
                      <span className="flex items-center gap-2 font-medium">
                        <provider.icon className="size-4 shrink-0" aria-hidden="true" />
                        {provider.title}
                      </span>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {provider.description}
                      </span>
                    </div>
                  </div>
                </RadioGroup.Item>
              )
            })}
          </RadioGroup.Root>

          {!current ? (
            <p className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
              Chưa chọn cổng model. Hệ thống <strong>không đoán hộ</strong> — hãy chọn một trong
              hai thẻ ở trên để bắt đầu.
            </p>
          ) : null}

          {current === 'antigravity' ? (
            <Card>
              <CardHeader>
                <CardTitle>Kết nối Google</CardTitle>
              </CardHeader>
              <CardContent>
                <OAuthCard status={status.data} />
              </CardContent>
            </Card>
          ) : null}

          {current === 'google_api_key' ? (
            <Card>
              <CardHeader>
                <CardTitle>Google API Key</CardTitle>
              </CardHeader>
              <CardContent>
                <ApiKeyCard status={status.data} />
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle>Chọn model</CardTitle>
            </CardHeader>
            <CardContent>
              <ModelPicker status={status.data} />
            </CardContent>
          </Card>

          <PageCard />

          <CookieCard />

          <DangerNote />
        </div>
      ) : null}
    </>
  )
}

/**
 * Nhắc lại giới hạn của hệ thống ngay tại nơi người vận hành cấu hình nó.
 *
 * Câu này **đã được sửa** khi luật L3 đổi (task.md X.6). Bản cũ nói "không có
 * chức năng tự gửi cho bất kỳ ai" — để nguyên thì nó thành một lời nói sai,
 * đúng ở chỗ nguy hiểm nhất: người vận hành sẽ tin là không có gì đi ra ngoài.
 */
function DangerNote() {
  return (
    <p className="text-xs text-muted-foreground">
      Hệ thống chỉ gửi tin cho người đã <strong>chủ động nhắn Page của bạn trước</strong>, và chỉ
      khi bạn bấm Gửi. Với những người khác, nó chỉ soạn nháp — bạn tự gửi tay. Chuỗi 10 tin ở
      Outbox <strong>không bao giờ</strong> được gửi tự động.
    </p>
  )
}
