import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/empty-state'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Không tìm thấy trang" />
      <EmptyState
        icon={Compass}
        title="Đường dẫn này không tồn tại"
        description="Có thể bạn dán thiếu một phần URL. Dùng thanh điều hướng phía trên để quay lại."
        action={
          <Button asChild variant="outline">
            <Link to="/">Về Dashboard</Link>
          </Button>
        }
      />
    </>
  )
}
