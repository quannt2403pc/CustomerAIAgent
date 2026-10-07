import { Check, Copy, ExternalLink, Info } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'

/**
 * Hướng dẫn tạo Facebook Page + Meta App (task.md X.7).
 *
 * Vì sao hướng dẫn nằm **trong UI** chứ không chỉ trong README: để bật được
 * tính năng này, người dùng phải rời ứng dụng sang `developers.facebook.com`
 * làm bảy bước, rồi mang hai giá trị quay lại đây. Hướng dẫn ở file khác nghĩa
 * là họ phải tự ghép hai nửa với nhau — và hai ô cần copy (Webhook URL, Verify
 * Token) thì chỉ ứng dụng biết giá trị thật.
 *
 * Vì sao phần "giới hạn" đặt **trên** các bước: giới hạn lớn nhất của
 * Messenger Platform là chỉ nhắn được cho người đã nhắn Page trước. Đọc nó sau
 * khi làm xong bảy bước là lúc tệ nhất để biết.
 */

function CopyRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = () => {
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => setCopied(false))
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? 'Đã copy' : 'Copy'}
        </Button>
      </div>
      {/*
        `tabIndex={0}` là **bắt buộc**, không phải trang trí (axe
        `scrollable-region-focusable`, đo thật ở mốc 375px): một vùng
        `overflow-x-auto` mà không focus được thì người dùng bàn phím **không có
        cách nào** cuộn để đọc hết URL — họ chỉ thấy đúng phần bị cắt.
        `role="group"` + `aria-label` để trình đọc màn hình nói được đây là gì.
      */}
      <code
        tabIndex={0}
        role="group"
        aria-label={label}
        className="block overflow-x-auto rounded border border-input-border bg-muted/40 px-3 py-2 text-xs text-foreground"
      >
        {value || '(chưa có — xem ghi chú bên dưới)'}
      </code>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

const STEPS: { title: string; body: React.ReactNode }[] = [
  {
    title: 'Tạo một Facebook Page',
    body: (
      <>
        Vào{' '}
        <a
          href="https://www.facebook.com/pages/create"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          facebook.com/pages/create <ExternalLink className="inline size-3" aria-hidden="true" />
        </a>{' '}
        và tạo Page cho cửa hàng. Page miễn phí, không cần duyệt. Nếu đã có Page bán hàng thì dùng
        luôn, không cần tạo mới.
      </>
    ),
  },
  {
    title: 'Tạo một Meta App',
    body: (
      <>
        Vào{' '}
        <a
          href="https://developers.facebook.com/apps"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          developers.facebook.com/apps <ExternalLink className="inline size-3" aria-hidden="true" />
        </a>{' '}
        → <strong>Create App</strong>. Chọn loại <strong>Business</strong>. App ở chế độ{' '}
        <strong>Development</strong> là đủ để chạy với Page của chính bạn — chưa cần App Review.
      </>
    ),
  },
  {
    title: 'Thêm sản phẩm Messenger',
    body: (
      <>
        Trong App vừa tạo: <strong>Add Product</strong> → <strong>Messenger</strong> →{' '}
        <strong>Set Up</strong>.
      </>
    ),
  },
  {
    title: 'Lấy Page Access Token',
    body: (
      <>
        Ở trang Messenger → <strong>Settings</strong> → mục <strong>Access Tokens</strong> →{' '}
        <strong>Add or Remove Pages</strong>, chọn Page ở bước 1 → bấm{' '}
        <strong>Generate Token</strong>. Dán token đó vào ô bên dưới.
        <br />
        <span className="text-destructive">
          Phải là token của <strong>Page</strong>, không phải User Access Token
        </span>{' '}
        — đây là chỗ sai phổ biến nhất.
      </>
    ),
  },
  {
    title: 'Đặt hai biến môi trường cho webhook',
    body: (
      <>
        Mở file <code>.env</code> của hệ thống và đặt:
        <br />
        <code>MESSENGER_APP_SECRET</code> — lấy ở App → <strong>Settings</strong> →{' '}
        <strong>Basic</strong> → <strong>App Secret</strong>.
        <br />
        <code>MESSENGER_VERIFY_TOKEN</code> — một chuỗi bạn <strong>tự đặt</strong>, dài và khó
        đoán. Nó chỉ dùng cho bước bắt tay ở bước 7.
        <br />
        Rồi chạy lại API: <code>docker compose up -d --force-recreate api</code>
        .
        <br />
        <span className="text-muted-foreground">
          Dùng <code>--force-recreate</code> chứ không phải <code>restart</code>:{' '}
          <code>restart</code> không nạp lại <code>.env</code>.
        </span>
      </>
    ),
  },
  {
    title: 'Mở một đường HTTPS công khai tới máy bạn',
    body: (
      <>
        Facebook chỉ gọi webhook qua HTTPS công khai, nên <code>localhost</code> không dùng được.
        Chạy một đường hầm, ví dụ:
        <br />
        <code>cloudflared tunnel --url http://localhost:8000</code>
        <br />
        Nó in ra một địa chỉ dạng <code>https://….trycloudflare.com</code>. Webhook URL của bạn là
        địa chỉ đó cộng <code>/api/messenger/webhook</code>.
      </>
    ),
  },
  {
    title: 'Đăng ký webhook với Facebook',
    body: (
      <>
        Ở trang Messenger → <strong>Settings</strong> → <strong>Webhooks</strong> →{' '}
        <strong>Add Callback URL</strong>. Dán Webhook URL ở bước 6 và Verify Token ở bước 5.
        Facebook sẽ gọi thử ngay; nếu hai giá trị khớp thì nó báo thành công.
        <br />
        Sau đó bấm <strong>Add Subscriptions</strong> cho Page và tick <code>messages</code>.
      </>
    ),
  },
]

export function PageGuide({ webhookUrl }: { webhookUrl: string }) {
  const isLocal = /localhost|127\.0\.0\.1/.test(webhookUrl)

  return (
    <div className="space-y-5">
      <div className="flex gap-3 rounded border border-secondary/40 bg-secondary/5 p-3">
        <Info className="mt-0.5 size-4 shrink-0 text-secondary" aria-hidden="true" />
        <div className="space-y-2 text-sm text-foreground">
          <p>
            <strong>Giới hạn cần biết trước khi làm:</strong> Facebook chỉ cho gửi tin tới người đã{' '}
            <strong>chủ động nhắn Page của bạn trước</strong>. Không có cách hợp lệ nào nhắn một
            profile cá nhân bất kỳ.
          </p>
          <p className="text-muted-foreground">
            Nên luồng dùng được là: bạn mời khách nhắn Page (chia sẻ link <code>m.me</code> của
            Page, gắn nút Messenger lên website, hay chạy quảng cáo Click-to-Messenger). Ngay khi họ
            nhắn, hội thoại tự xuất hiện ở đây và nút Gửi hoạt động. Trả lời được trong 7 ngày kể từ
            tin cuối của họ.
          </p>
        </div>
      </div>

      <ol className="space-y-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex gap-3">
            <span
              className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
              aria-hidden="true"
            >
              {index + 1}
            </span>
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">{step.title}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="space-y-3 rounded border border-border bg-muted/20 p-3">
        <CopyRow
          label="Webhook URL"
          value={webhookUrl}
          hint={
            isLocal
              ? 'Đây là địa chỉ nội bộ — Facebook không gọi được. Thay phần trước /api bằng địa chỉ HTTPS công khai ở bước 6.'
              : 'Dán nguyên văn vào ô Callback URL ở bước 7.'
          }
        />
        <p className="text-xs text-muted-foreground">
          <strong className="text-foreground">Verify Token</strong> không có ô copy ở đây: nó là
          chuỗi bạn tự đặt trong <code>.env</code> (<code>MESSENGER_VERIFY_TOKEN</code>), và hệ
          thống không hiện lại secret đã lưu (luật L4).
        </p>
      </div>
    </div>
  )
}
