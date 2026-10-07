import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  // Không `console.error` (luật L5). Ném lỗi để nó nổi lên error boundary /
  // trang lỗi thật, thay vì im lặng render ra một trang trắng.
  throw new Error('Thiếu phần tử #root trong index.html')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
