import { AlertTriangle, Gauge, RefreshCw } from 'lucide-react'
import * as React from 'react'

import { useToast } from '@/components/toast-context'
import { Badge, VisionBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Select } from '@/components/ui/field'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api'
import type { LlmStatus, ModelInfo } from '@/lib/types'
import { formatTokens } from '@/lib/utils'

import { useModels, useRefreshModels, useSetModel, useTestGateway } from './hooks'

/**
 * Chọn model — luật thép L6: danh mục **luôn** lấy từ cổng đang chọn lúc chạy.
 * Không có tên model nào được viết cứng ở file này.
 */
export function ModelPicker({ status }: { status: LlmStatus | undefined }) {
  const toast = useToast()
  const provider = status?.provider ?? null
  const models = useModels(provider)
  const refresh = useRefreshModels()
  const setModel = useSetModel()
  const test = useTestGateway()

  const selected: ModelInfo | undefined = React.useMemo(
    () => models.data?.models.find((model) => model.id === status?.model),
    [models.data, status?.model],
  )

  if (!provider) {
    return (
      <p className="text-sm text-muted-foreground">
        Chọn một cổng model ở trên, rồi danh sách model sẽ hiện ra đây.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field
          id="model-select"
          label="Model sẽ dùng"
          className="flex-1"
          error={
            status?.must_choose_model
              ? 'Bạn vừa đổi cổng nên model cũ không còn hiệu lực. Hãy chọn lại một model.'
              : null
          }
          hint={models.data?.note}
        >
          {(fieldProps) =>
            models.isPending ? (
              <Skeleton className="h-11 w-full" />
            ) : (
              <Select
                {...fieldProps}
                value={status?.model ?? ''}
                disabled={setModel.isPending || !models.data}
                onChange={(event) => {
                  const value = event.target.value
                  if (!value) return
                  setModel.mutate(value, {
                    onSuccess: () => toast.success(`Đã chọn model ${value}.`),
                    onError: (error) => toast.error(errorMessage(error)),
                  })
                }}
              >
                <option value="" disabled>
                  — Chọn model —
                </option>
                {models.data?.models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.id}
                    {model.supports_vision === true ? ' · đọc được ảnh' : ''}
                    {model.supports_vision === false ? ' · không đọc được ảnh' : ''}
                    {model.output_token_limit
                      ? ` · ra tối đa ${formatTokens(model.output_token_limit)} token`
                      : ''}
                  </option>
                ))}
              </Select>
            )
          }
        </Field>

        <Button
          variant="outline"
          loading={refresh.isPending}
          onClick={() =>
            refresh.mutate(undefined, {
              onSuccess: (data) => toast.success(`Đã nạp lại danh mục: ${data.models.length} model.`),
              onError: (error) => toast.error(errorMessage(error)),
            })
          }
        >
          <RefreshCw aria-hidden="true" />
          Nạp lại danh mục
        </Button>
      </div>

      {models.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {errorMessage(models.error)}
        </p>
      ) : null}

      {selected ? (
        <div className="flex flex-wrap items-center gap-2">
          <VisionBadge supports={selected.supports_vision} />
          {selected.output_token_limit ? (
            <Badge tone="neutral" icon={Gauge}>
              Ra tối đa {formatTokens(selected.output_token_limit)} token
            </Badge>
          ) : null}
        </div>
      ) : null}

      {/*
        Cảnh báo bắt buộc theo DoD D2.7. Hai mức khác nhau vì hai sự thật khác
        nhau (task.md I-06): cổng A **biết chắc** model không đọc được ảnh; cổng
        B **không biết** — nói "không đọc được" ở đó là bịa.
      */}
      {selected?.supports_vision === false ? (
        <p className="flex items-start gap-2 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <span>
            Model này <strong>không đọc được ảnh</strong>. Bước mô tả ảnh sẽ bị bỏ qua và{' '}
            <code>visual_context</code> sẽ là <code>null</code> — tin nhắn chỉ dựa được vào phần
            chữ thu thập được.
          </span>
        </p>
      ) : null}

      {selected?.supports_vision === null ? (
        <p className="flex items-start gap-2 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
          <span>
            Cổng này <strong>không cho biết</strong> model có đọc được ảnh hay không. Nếu model
            không đọc được ảnh thì <code>visual_context</code> sẽ là <code>null</code>. Bấm
            &quot;Kiểm tra kết nối&quot; để thử trước khi chạy thật.
          </span>
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <Button
          variant="outline"
          loading={test.isPending}
          disabled={!status?.model}
          onClick={() =>
            test.mutate(undefined, {
              onSuccess: (data) =>
                toast.success(`Gọi thử thành công sau ${data.latency_ms} ms. ${data.note}`),
              onError: (error) => toast.error(errorMessage(error)),
            })
          }
        >
          <Gauge aria-hidden="true" />
          Kiểm tra kết nối
        </Button>

        {/*
          Kết quả hiện **cạnh nút**, không chỉ trong toast đã biến mất: đây là số
          liệu người vận hành cần đối chiếu khi chọn giữa nhiều model.
        */}
        {test.data ? (
          <p className="text-sm" role="status">
            <span className="font-medium text-success">Gọi được</span>{' '}
            <span className="tabular text-muted-foreground">
              — {test.data.latency_ms} ms, model {test.data.model}
            </span>
          </p>
        ) : null}
        {test.isError ? (
          <p role="alert" className="text-sm font-medium text-destructive">
            {errorMessage(test.error)}
          </p>
        ) : null}
      </div>
    </div>
  )
}
