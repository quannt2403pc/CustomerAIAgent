import { Play, RotateCcw, Search } from 'lucide-react'
import * as React from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { useToast } from '@/components/toast-context'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, Input, Textarea } from '@/components/ui/field'
import { Skeleton } from '@/components/ui/skeleton'
import { useCreateAnalysis, useJob, useProfile } from '@/features/profiles/hooks'
import { ResultView } from '@/features/profiles/result-view'
import { StepTimeline } from '@/features/profiles/step-timeline'
import { ApiError, errorMessage } from '@/lib/api'

/** Kiểm sơ bộ ở client. Kiểm **thật** vẫn ở server — đây chỉ để phản hồi nhanh. */
function looksLikeFacebookUrl(value: string): boolean {
  try {
    const url = new URL(value.trim())
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false
    const host = url.hostname.toLowerCase()
    // So khớp **đúng domain hoặc subdomain**, không dùng `includes`:
    // `facebook.com.evil.test` phải bị loại (đã có test ở backend).
    return (
      host === 'facebook.com' ||
      host.endsWith('.facebook.com') ||
      host === 'fb.com' ||
      host.endsWith('.fb.com')
    )
  } catch {
    return false
  }
}

export function AnalyzePage() {
  const { profileId: routeProfileId } = useParams()
  const navigate = useNavigate()
  const toast = useToast()

  const [url, setUrl] = React.useState('')
  const [manualText, setManualText] = React.useState('')
  const [usePlaywright, setUsePlaywright] = React.useState(false)
  const [urlError, setUrlError] = React.useState<string | null>(null)
  const [jobId, setJobId] = React.useState<string | null>(null)
  const [activeProfileId, setActiveProfileId] = React.useState<string | null>(
    routeProfileId ?? null,
  )

  const create = useCreateAnalysis()
  const job = useJob(jobId)
  const profile = useProfile(activeProfileId)

  /** Job xong → chuyển sang xem kết quả. */
  React.useEffect(() => {
    const data = job.data
    if (!data || data.ok === null) return
    if (data.profile_id) {
      setActiveProfileId(data.profile_id)
      navigate(`/phan-tich/${data.profile_id}`, { replace: true })
    }
    if (data.ok === false && data.error) toast.error(data.error)
  }, [job.data, navigate, toast])

  const submit = (refresh: boolean) => {
    const trimmedUrl = url.trim()
    const trimmedText = manualText.trim()

    if (!trimmedUrl && !trimmedText) {
      setUrlError('Nhập URL Facebook công khai, hoặc dán nội dung trang ở ô bên dưới.')
      return
    }
    if (trimmedUrl && !looksLikeFacebookUrl(trimmedUrl)) {
      setUrlError('Đây không phải link facebook.com. Kiểm tra lại đường dẫn.')
      return
    }
    setUrlError(null)

    create.mutate(
      {
        facebook_url: trimmedUrl || null,
        profile_text: trimmedText || null,
        use_playwright: usePlaywright,
        refresh,
      },
      {
        onSuccess: (accepted) => {
          if (accepted.reused && accepted.profile_id) {
            // Không gọi model lần nào — nói rõ để người dùng biết vì sao nhanh thế.
            toast.info(accepted.message)
            setJobId(accepted.job_id)
            setActiveProfileId(accepted.profile_id)
            navigate(`/phan-tich/${accepted.profile_id}`, { replace: true })
            return
          }
          toast.info(accepted.message)
          setJobId(accepted.job_id)
          setActiveProfileId(null)
        },
        onError: (error) => {
          const message = errorMessage(error)
          // Lỗi thuộc về ô URL thì hiện **cạnh ô đó**; lỗi cấu hình thì toast.
          if (error instanceof ApiError && error.code === 'E-COL-400-URL') setUrlError(message)
          else toast.error(message)
        },
      },
    )
  }

  const running = Boolean(job.data && job.data.ok === null)
  const alreadyAnalysed = Boolean(activeProfileId)

  return (
    <>
      <PageHeader
        title="Phân tích"
        description="Nhập một trang Facebook công khai. Hệ thống chỉ đọc dữ liệu công khai, mỗi giây một yêu cầu."
      />

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Nguồn dữ liệu</CardTitle>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-4"
              onSubmit={(event) => {
                event.preventDefault()
                submit(false)
              }}
            >
              <Field
                id="facebook-url"
                label="URL trang Facebook"
                error={urlError}
                hint="Ví dụ https://www.facebook.com/ten_nguoi_dung — tham số thừa như ?mibextid sẽ được bỏ tự động."
              >
                {(fieldProps) => (
                  <Input
                    {...fieldProps}
                    type="url"
                    value={url}
                    onChange={(event) => {
                      setUrl(event.target.value)
                      if (urlError) setUrlError(null)
                    }}
                    placeholder="https://www.facebook.com/..."
                    autoComplete="off"
                  />
                )}
              </Field>

              <Field
                id="manual-text"
                label="Hoặc dán nội dung trang (tuỳ chọn)"
                hint="Dùng khi Facebook chặn đọc tự động. Dán những gì BẠN nhìn thấy; có thể ghi nhãn như “Tên:”, “Giới thiệu:”, “Bài viết:”."
              >
                {(fieldProps) => (
                  <Textarea
                    {...fieldProps}
                    rows={4}
                    value={manualText}
                    onChange={(event) => setManualText(event.target.value)}
                    placeholder="Tên: ...&#10;Giới thiệu: ..."
                  />
                )}
              </Field>

              <label className="flex cursor-pointer items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={usePlaywright}
                  onChange={(event) => setUsePlaywright(event.target.checked)}
                  className="mt-1 size-4 cursor-pointer accent-[rgb(var(--color-primary))]"
                />
                <span>
                  Bật lớp trình duyệt thật (Playwright)
                  <span className="block text-xs text-muted-foreground">
                    Chậm hơn nhưng lấy được ảnh công khai. Chỉ hoạt động nếu image có Chromium.
                  </span>
                </span>
              </label>

              <div className="flex flex-wrap gap-2">
                {/*
                  `loading` phủ **cả** lúc gửi yêu cầu lẫn lúc job chạy nền
                  (plan.md §6.2: nút async phải disable **và** có spinner). Chỉ
                  `disabled` mà không có spinner thì người dùng thấy một nút chết
                  và không biết hệ thống đang làm gì — mà job này chạy hàng chục giây.
                */}
                <Button type="submit" loading={create.isPending || running}>
                  <Play aria-hidden="true" />
                  {running ? 'Đang phân tích…' : 'Phân tích'}
                </Button>
                {alreadyAnalysed ? (
                  <Button
                    type="button"
                    variant="outline"
                    loading={create.isPending || running}
                    onClick={() => submit(true)}
                  >
                    <RotateCcw aria-hidden="true" />
                    Phân tích lại
                  </Button>
                ) : null}
              </div>
              <p className="text-xs text-muted-foreground">
                Một lần phân tích gọi model 7–14 lượt và mất vài chục giây. URL đã phân tích rồi sẽ
                trả kết quả cũ, trừ khi bạn bấm &quot;Phân tích lại&quot;.
              </p>
            </form>
          </CardContent>
        </Card>

        {jobId ? (
          <Card>
            <CardHeader>
              <CardTitle>Tiến trình</CardTitle>
            </CardHeader>
            <CardContent>
              <StepTimeline job={job.data} loading={job.isPending} />
            </CardContent>
          </Card>
        ) : null}

        {profile.isPending && activeProfileId ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-64 w-full" />
          </div>
        ) : null}

        {profile.isError ? (
          <p role="alert" className="text-sm font-medium text-destructive">
            {errorMessage(profile.error)}
          </p>
        ) : null}

        {profile.data ? <ResultView profile={profile.data} /> : null}

        {!jobId && !activeProfileId ? (
          <EmptyState
            icon={Search}
            title="Chưa có kết quả nào"
            description="Nhập một URL Facebook công khai ở trên rồi bấm Phân tích. Kết quả gồm profile, 10 tin nhắn tâm sự và câu chuyện mồi 20h."
          />
        ) : null}
      </div>
    </>
  )
}
