import { BarChart3, FileText, Inbox, MessageSquare, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { ProfileStatusBadge, SalesCheckBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useProfiles, useStats } from '@/features/profiles/hooks'
import { errorMessage } from '@/lib/api'
import { formatDateTime, formatPercent } from '@/lib/utils'

export function DashboardPage() {
  const stats = useStats()
  const profiles = useProfiles(10, 0)

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Số liệu đếm trực tiếp từ cơ sở dữ liệu, không ước lượng."
        actions={
          <Button asChild>
            <Link to="/phan-tich">
              <Search aria-hidden="true" />
              Phân tích mới
            </Link>
          </Button>
        }
      />

      <div className="flex flex-col gap-5">
        <section aria-labelledby="kpi-heading">
          <h2 id="kpi-heading" className="sr-only">
            Chỉ số tổng quan
          </h2>
          {stats.isPending ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-24" />
              ))}
            </div>
          ) : stats.isError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {errorMessage(stats.error)}
            </p>
          ) : stats.data ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Kpi
                icon={FileText}
                label="Profile đã phân tích"
                value={String(stats.data.profiles_total)}
                hint={`${stats.data.profiles_success} thành công · ${stats.data.profiles_partial} một phần · ${stats.data.profiles_failed} lỗi`}
              />
              <Kpi
                icon={BarChart3}
                label="Tỉ lệ đọc được"
                value={formatPercent(stats.data.readable_rate)}
                /*
                  `null` ≠ 0%. Chưa có profile nào thì không có tỉ lệ nào để nói —
                  hiện "0%" cho một mẫu rỗng là một lời nói sai.
                */
                hint={
                  stats.data.readable_rate === null
                    ? 'Chưa có profile nào để tính'
                    : 'Thành công hoặc đọc được một phần'
                }
              />
              <Kpi
                icon={MessageSquare}
                label="Tin nhắn đã sinh"
                value={String(stats.data.messages_total)}
                hint="Tổng qua mọi lượt chạy"
              />
              <Kpi
                icon={Inbox}
                label="Nháp 20h chờ gửi"
                value={String(stats.data.hooks_waiting)}
                hint="Bạn phải tự gửi tay"
              />
            </div>
          ) : null}
        </section>

        <Card>
          <CardHeader>
            <CardTitle>Profile gần đây</CardTitle>
          </CardHeader>
          <CardContent>
            {profiles.isPending ? (
              <div className="flex flex-col gap-2" aria-busy="true">
                {Array.from({ length: 4 }, (_, index) => (
                  <Skeleton key={index} className="h-12" />
                ))}
              </div>
            ) : profiles.isError ? (
              <p role="alert" className="text-sm font-medium text-destructive">
                {errorMessage(profiles.error)}
              </p>
            ) : profiles.data && profiles.data.items.length > 0 ? (
              /* Bảng cuộn ngang **trong khung của nó**, không làm cả trang cuộn ngang. */
              <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
                <table className="w-full min-w-[46rem] text-sm">
                  <caption className="sr-only">
                    Danh sách profile đã phân tích, mới nhất trước
                  </caption>
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Khách
                      </th>
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Trạng thái
                      </th>
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Tin nhắn
                      </th>
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Kiểm duyệt
                      </th>
                      <th scope="col" className="py-2 font-medium">
                        Thời điểm
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {profiles.data.items.map((item) => (
                      <tr key={item.id} className="border-b border-border/60 last:border-0">
                        <td className="py-2 pr-3">
                          <Link
                            to={`/phan-tich/${item.id}`}
                            className="font-medium text-primary underline-offset-2 hover:underline"
                          >
                            {item.customer_name ?? 'Không đọc được tên'}
                          </Link>
                          <span className="block max-w-[22rem] truncate text-xs text-muted-foreground">
                            {item.facebook_url}
                          </span>
                        </td>
                        <td className="py-2 pr-3">
                          <ProfileStatusBadge status={item.status} />
                        </td>
                        <td className="tabular py-2 pr-3">{item.message_count}</td>
                        <td className="py-2 pr-3">
                          {/* Cùng luật I-21/I-46: không xác nhận "0% chào bán" cho nội dung rỗng. */}
                          {item.message_count > 0 ? (
                            <SalesCheckBadge value={item.sales_check} />
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </td>
                        <td className="tabular py-2 text-muted-foreground">
                          {formatDateTime(item.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon={Search}
                title="Chưa phân tích profile nào"
                description="Bắt đầu bằng một link Facebook công khai ở trang Phân tích."
                action={
                  <Button asChild variant="outline">
                    <Link to="/phan-tich">Tới trang Phân tích</Link>
                  </Button>
                }
              />
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

function Kpi({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: LucideIcon
  label: string
  value: string
  hint: string
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Icon className="size-4 shrink-0" aria-hidden="true" />
          <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
        </div>
        {/* `tabular`: số không nhảy cột khi giá trị đổi lúc refetch. */}
        <p className="tabular mt-1 text-2xl font-semibold">{value}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}
