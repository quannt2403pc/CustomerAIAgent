import type { Config } from 'tailwindcss'

/**
 * Token đọc từ CSS variable, **không** nhúng hex vào đây (plan.md §6.1).
 *
 * Lý do: dark mode đổi giá trị của cùng một biến, nên component viết
 * `bg-background` là đúng ở cả hai chế độ. Nhúng hex vào config thì mỗi
 * component phải tự biết đang ở chế độ nào — đúng thứ sinh ra `dark:bg-[#0f172a]`
 * rải khắp codebase.
 *
 * Dùng `rgb(var(--x) / <alpha-value>)` thay vì `var(--x)` trực tiếp để Tailwind
 * còn sinh được `bg-primary/10`; với `var()` thuần thì mọi tiện ích opacity chết.
 */
const token = (name: string) => `rgb(var(${name}) / <alpha-value>)`

export default {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: token('--color-background'),
        foreground: token('--color-foreground'),
        primary: {
          DEFAULT: token('--color-primary'),
          foreground: token('--color-on-primary'),
        },
        secondary: token('--color-secondary'),
        accent: token('--color-accent'),
        muted: {
          DEFAULT: token('--color-muted'),
          foreground: token('--color-muted-foreground'),
        },
        surface: token('--color-surface'),
        border: token('--color-border'),
        // Tách khỏi `border`: ranh giới của control cần ≥3:1 (WCAG 1.4.11),
        // còn phân cách trang trí thì không (task.md I-42).
        'input-border': token('--color-input-border'),
        destructive: {
          DEFAULT: token('--color-destructive'),
          foreground: token('--color-on-destructive'),
        },
        success: token('--color-success'),
        warning: token('--color-warning'),
        ring: token('--color-ring'),
      },
      fontFamily: {
        // Self-host qua @fontsource — hệ thống phải chạy được trong mạng nội bộ
        // / offline, nên không gọi fonts.googleapis.com (plan.md §6.1).
        sans: ['"Fira Sans"', 'system-ui', 'sans-serif'],
        mono: ['"Fira Code"', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '0.375rem',
        lg: '0.5rem',
      },
      // Dashboard dữ liệu dày → thang 4/8px (ui-ux-pro-max: spacing-scale).
      spacing: {
        '4.5': '1.125rem',
      },
      transitionDuration: {
        DEFAULT: '200ms', // 150–300ms theo plan.md §6.2
      },
    },
  },
  plugins: [],
} satisfies Config
