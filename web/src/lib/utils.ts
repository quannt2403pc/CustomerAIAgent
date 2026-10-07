import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Ghép class Tailwind, lớp sau thắng lớp trước (shadcn/ui convention). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}

/**
 * Định dạng mốc thời gian theo giờ Việt Nam.
 *
 * Luôn nêu rõ múi giờ: toàn bộ sản phẩm neo vào mốc 20:00 Asia/Ho_Chi_Minh, nên
 * hiện giờ theo máy người xem sẽ làm lệch đúng con số quan trọng nhất.
 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'Asia/Ho_Chi_Minh',
  }).format(date)
}

export function formatPercent(value: number | null | undefined): string {
  // `null` nghĩa là **chưa có dữ liệu**, không phải 0% — hai điều khác nhau.
  if (value === null || value === undefined) return '—'
  return `${Math.round(value * 1000) / 10}%`
}

export function formatTokens(value: number | null | undefined): string {
  if (!value) return '—'
  return value >= 1000 ? `${Math.round(value / 1000)}k` : String(value)
}
