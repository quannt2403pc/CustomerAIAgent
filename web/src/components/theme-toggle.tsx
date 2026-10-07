import { Moon, Sun } from 'lucide-react'
import * as React from 'react'

import { Button } from './ui/button'

const STORAGE_KEY = 'caa-theme'
type Theme = 'light' | 'dark'

function readInitialTheme(): Theme {
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  // Chưa chọn → theo hệ điều hành. Ép light cho người đang dùng dark là chói mắt.
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Bật/tắt dark mode bằng `data-theme` trên `<html>` (khớp `darkMode` của Tailwind).
 *
 * Nút hiện **icon + chữ**, không phải icon trần: plan.md §6.2 cấm truyền thông
 * tin chỉ bằng hình. Trên màn hình hẹp chữ thu lại thành `sr-only` nhưng
 * `aria-label` vẫn đủ nghĩa.
 */
export function ThemeToggle() {
  const [theme, setTheme] = React.useState<Theme>(readInitialTheme)

  React.useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    window.localStorage.setItem(STORAGE_KEY, theme)
  }, [theme])

  const next = theme === 'dark' ? 'light' : 'dark'
  const Icon = theme === 'dark' ? Sun : Moon

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => setTheme(next)}
      aria-label={next === 'dark' ? 'Chuyển sang chế độ tối' : 'Chuyển sang chế độ sáng'}
    >
      <Icon aria-hidden="true" />
      <span className="hidden sm:inline">{next === 'dark' ? 'Tối' : 'Sáng'}</span>
    </Button>
  )
}
