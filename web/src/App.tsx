import { QueryClientProvider } from '@tanstack/react-query'
import * as React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { BrowserRouter } from 'react-router-dom'

import { AppShell } from './components/app-shell'
import { ErrorBoundary } from './components/error-boundary'
import { ToastProvider } from './components/toast'
import { createQueryClient } from './lib/query'
import { AnalyzePage } from './pages/analyze'
import { DashboardPage } from './pages/dashboard'
import { NotFoundPage } from './pages/not-found'
import { OutboxPage } from './pages/outbox'
import { SettingsPage } from './pages/settings'

/**
 * `QueryClient` tạo **một lần** bằng `useState`, không phải mỗi lần render.
 * Tạo lại mỗi render làm cache rỗng liên tục → UI nhấp nháy và gọi API lặp.
 *
 * Thứ tự provider có chủ đích: `ErrorBoundary` **ngoài cùng** để nó bắt được cả
 * lỗi render của provider bên trong; `ToastProvider` nằm trong `QueryClientProvider`
 * để hook mutation gọi được `useToast`.
 *
 * TanStack Query **devtools không được nhúng** (plan.md §7.3.4): devtools in
 * nguyên payload response ra một panel trên trang.
 */
export function App() {
  const [queryClient] = React.useState(createQueryClient)

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          {/*
            Bật sẵn cờ v7 của react-router. Hai lý do:
            - Không bật thì router in **cảnh báo ra console** ở bản dev, làm nhiễu
              đúng cái bằng chứng "Console trống" mà luật L5 cần (D2.12).
            - Hành vi v7 (bọc cập nhật state trong `startTransition`, phân giải
              route tương đối trong splat) là hành vi ta muốn — bật sớm thì nâng
              cấp sau này không đổi hành vi dưới chân mình.
          */}
          <BrowserRouter
            future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
          >
            <Routes>
              <Route element={<AppShell />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/phan-tich" element={<AnalyzePage />} />
                <Route path="/phan-tich/:profileId" element={<AnalyzePage />} />
                <Route path="/outbox" element={<OutboxPage />} />
                <Route path="/cai-dat" element={<SettingsPage />} />
                {/* Đường dẫn cũ/lỗi chính tả → về trang chủ thay vì trang trắng. */}
                <Route path="/dashboard" element={<Navigate to="/" replace />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
