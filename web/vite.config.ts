import path from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * Luật thép L5 — không lộ JSON response ra console trình duyệt (plan.md §7.3).
 *
 * `esbuild.drop` là **lớp thứ hai**, không phải lớp duy nhất: ESLint
 * `no-console: error` chặn ngay lúc viết code, còn `drop` bảo đảm bản production
 * không còn lệnh `console.*` nào kể cả khi một thư viện bên thứ ba có.
 * Một lớp thì ai cũng vượt được bằng `// eslint-disable-next-line`.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  esbuild: {
    drop: ['console', 'debugger'],
  },
  server: {
    port: 5173,
    // Dev proxy: FE gọi `/api/...` cùng origin nên **không cần CORS** khi chạy
    // `npm run dev`. Bản production đi qua nginx với cùng đường dẫn (D2.10) →
    // một hợp đồng URL duy nhất cho cả hai môi trường.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false, // sourcemap trong production là một đường lộ code
  },
})
