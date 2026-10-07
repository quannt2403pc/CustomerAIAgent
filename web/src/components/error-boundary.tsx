import { RotateCcw, ShieldAlert } from 'lucide-react'
import * as React from 'react'

import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'

/**
 * Error boundary — trang lỗi thân thiện, **không in stack ra console** (luật L5).
 *
 * React tự log lỗi chưa bắt ra console ở bản **development**; ở bản production
 * `esbuild.drop` đã xoá mọi lệnh console nên không còn gì in ra. Điều quan trọng
 * là chính chúng ta **không** thêm `console.error(error)` vào `componentDidCatch`
 * — đó là chỗ mặc định ai cũng đặt, và nó in trọn stack kèm props (có thể chứa
 * dữ liệu khách) ra console trình duyệt.
 *
 * `error.message` cũng **không** hiện ra UI: nó có thể chứa chi tiết nội bộ. Người
 * vận hành cần biết "cái gì hỏng và làm gì tiếp", không cần biết tên biến.
 */
interface State {
  failed: boolean
}

interface Props {
  children: React.ReactNode
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(): void {
    // Cố ý để trống. Xem docstring: không log stack ra console trình duyệt.
  }

  private handleReload = (): void => {
    window.location.reload()
  }

  render(): React.ReactNode {
    if (!this.state.failed) return this.props.children

    return (
      <div className="flex min-h-dvh items-center justify-center p-6">
        <Card className="w-full max-w-lg">
          <CardHeader>
            <div className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="size-5 shrink-0" aria-hidden="true" />
              <CardTitle as="h2">Giao diện gặp lỗi</CardTitle>
            </div>
            <CardDescription>
              Một phần giao diện không dựng được. Dữ liệu của bạn trên máy chủ không bị ảnh
              hưởng — chưa có tin nhắn nào được gửi cho ai.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              Hãy tải lại trang. Nếu lỗi lặp lại, xem log của service <code>api</code> để biết
              chi tiết.
            </p>
            <Button onClick={this.handleReload} className="self-start">
              <RotateCcw aria-hidden="true" />
              Tải lại trang
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }
}
