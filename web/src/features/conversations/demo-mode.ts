import * as React from 'react'

/**
 * Chế độ demo — trình bày trọn vòng trò chuyện mà **không gửi gì cho ai**.
 *
 * Vì sao cần: khi trình bày trước khách hàng, mở tab Facebook ra rồi dán tay là
 * vừa chậm vừa dễ vỡ (popup bị chặn, phải đăng nhập, lộ tin nhắn riêng trên màn
 * chiếu). Chế độ này bỏ hẳn bước đó: bấm Gửi là ghi thẳng vào lịch sử.
 *
 * Vì sao nó **không được** âm thầm: cả dự án này xây để chống việc hệ thống nói
 * điều không có thật. Một chế độ làm app *trông như* đã gửi mà thực ra chưa, nếu
 * giấu đi, chính là thứ nguy hiểm nhất ở đây. Nên nó đi kèm ba ràng buộc:
 *
 * 1. **Luôn hiện băng cảnh báo** trên màn hình khi bật.
 * 2. **Mỗi tin được đánh dấu `is_demo`** trong cơ sở dữ liệu, không chỉ ở giao
 *    diện — để sau buổi demo vẫn phân biệt được tin nào đã thật sự gửi.
 * 3. **Không bao giờ chạm đường gửi thật.** Bật demo thì Send API không được
 *    gọi, kể cả khi hội thoại đủ điều kiện gửi tự động.
 *
 * Lưu ở `localStorage` chứ không ở server: đây là lựa chọn của **người đang
 * trình bày trên máy này**, không phải cấu hình hệ thống. Hai người mở cùng một
 * hội thoại ở hai máy thì một người demo không được kéo người kia vào theo.
 */
const STORAGE_KEY = 'drbee.demo-mode'

function read(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === '1'
  } catch {
    // Trình duyệt chặn localStorage (chế độ riêng tư, chính sách doanh nghiệp).
    // Mặc định **tắt**: thà demo phải bật lại mỗi lần còn hơn vô tình chạy ở
    // chế độ demo mà không biết.
    return false
  }
}

export function useDemoMode(): [boolean, (next: boolean) => void] {
  const [enabled, setEnabled] = React.useState(read)

  const update = React.useCallback((next: boolean) => {
    setEnabled(next)
    try {
      if (next) window.localStorage.setItem(STORAGE_KEY, '1')
      else window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Không lưu được thì vẫn đổi trong phiên này — chỉ là không nhớ qua lần sau.
    }
  }, [])

  return [enabled, update]
}
