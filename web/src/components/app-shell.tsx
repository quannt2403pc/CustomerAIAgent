import { useQuery } from '@tanstack/react-query'
import { AlarmClock, BarChart3, Inbox, Search, Settings } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import * as React from 'react'

import { api } from '@/lib/api'
import type { Health } from '@/lib/types'
import { cn } from '@/lib/utils'

import { ThemeToggle } from './theme-toggle'
import { Badge } from './ui/badge'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

/** Điều hướng **giống nhau ở mọi trang** (ui-ux-pro-max `navigation-consistency`). */
const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: BarChart3 },
  { to: '/phan-tich', label: 'Phân tích', icon: Search },
  { to: '/outbox', label: 'Outbox', icon: Inbox },
  { to: '/cai-dat', label: 'Cài đặt', icon: Settings },
]

export function AppShell() {
  const location = useLocation()
  const mainRef = React.useRef<HTMLElement>(null)

  /*
   * Đổi route → chuyển focus về vùng nội dung chính.
   *
   * Không làm thì người dùng bàn phím/screen reader đổi trang mà focus vẫn nằm ở
   * link vừa bấm: họ phải Tab lại từ đầu nav mỗi lần (WCAG `focus-on-route-change`).
   * `preventScroll` để không nhảy cuộn — trang đã ở đầu sau khi đổi route.
   */
  React.useEffect(() => {
    mainRef.current?.focus({ preventScroll: true })
  }, [location.pathname])

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      {/* Skip link: lối thoát cho người dùng bàn phím khỏi phải Tab qua cả nav. */}
      <a href="#noi-dung" className="skip-link">
        Bỏ qua điều hướng, tới nội dung chính
      </a>

      <header className="sticky top-0 z-40 border-b border-border bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-2">
            <AlarmClock className="size-5 shrink-0 text-primary" aria-hidden="true" />
            <span className="truncate font-mono text-sm font-semibold">AI Profiler &amp; Rapport</span>
          </div>

          {/* `aria-label` vì có nhiều vùng điều hướng tiềm năng trên trang. */}
          <nav aria-label="Điều hướng chính" className="order-last w-full sm:order-none sm:w-auto">
            <ul className="flex flex-wrap items-center gap-1">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      cn(
                        'flex min-h-11 cursor-pointer items-center gap-2 rounded px-3 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                      )
                    }
                  >
                    {/*
                      Vị trí hiện tại **không** chỉ báo bằng màu: `NavLink` tự
                      đặt `aria-current="page"` lên thẻ `<a>`. Đặt thêm một lần
                      nữa lên `<span>` bên trong thì screen reader thông báo
                      "trang hiện tại" **hai lần** cho cùng một mục — đo thật
                      thấy 2 phần tử mang `aria-current` (task.md I-43).
                    */}
                    <>
                      <item.icon className="size-4 shrink-0" aria-hidden="true" />
                      <span>{item.label}</span>
                    </>
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <HealthIndicator />
            <ThemeToggle />
          </div>
        </div>
      </header>

      {/*
       * `tabIndex={-1}`: để `focus()` lúc đổi route hoạt động mà **không** đưa
       * vùng này vào thứ tự Tab bình thường.
       */}
      <main
        id="noi-dung"
        ref={mainRef}
        tabIndex={-1}
        className="mx-auto w-full max-w-7xl flex-1 px-4 py-6"
      >
        <Outlet />
      </main>

      <footer className="border-t border-border px-4 py-3 text-center text-xs text-muted-foreground">
        Hệ thống chỉ <strong>soạn nháp</strong>. Không có chức năng tự gửi tin nhắn cho bất kỳ ai.
      </footer>
    </div>
  )
}

/**
 * Chỉ báo sức khoẻ hệ thống trên header.
 *
 * Hiện ở **mọi trang** vì hai thứ có thể chết âm thầm: kết nối DB, và lịch 20h
 * (một deliverable của đề bài). Không có chỉ báo thì lịch có thể không chạy hàng
 * tuần mà không ai biết.
 */
function HealthIndicator() {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => api.get<Health>('/health', undefined, signal),
    refetchInterval: 60_000,
  })

  if (isError) {
    return (
      <Badge tone="danger" title="Không gọi được /health">
        API không phản hồi
      </Badge>
    )
  }
  if (!data) return null

  const dbDown = data.db !== 'ok'
  const schedulerDown = data.scheduler.enabled && !data.scheduler.running

  if (dbDown) {
    return (
      <Badge tone="danger" title="Không kết nối được PostgreSQL">
        Mất kết nối DB
      </Badge>
    )
  }
  if (schedulerDown) {
    return (
      <Badge tone="warning" title={data.scheduler.detail}>
        Lịch 20h không chạy
      </Badge>
    )
  }
  return (
    <Badge
      tone="success"
      className="hidden md:inline-flex"
      title={`Lịch ${data.scheduler.cron}${
        data.scheduler.next_run_at ? ` — lượt kế tiếp ${data.scheduler.next_run_at}` : ''
      }`}
    >
      Hệ thống bình thường
    </Badge>
  )
}
