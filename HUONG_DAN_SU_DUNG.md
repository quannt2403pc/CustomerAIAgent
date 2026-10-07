# Hướng dẫn sử dụng

Tài liệu này đi từ màn hình trắng tới lúc gửi được tin nhắn thật. Đọc theo thứ
tự lần đầu; những lần sau tra mục cần dùng.

> Cài đặt (Docker / không Docker) nằm ở [README.md](README.md). Tài liệu này
> giả định hệ thống **đã chạy được** ở `http://localhost:5173`.

---

## Mục lục

1. [Hệ thống làm gì, và không làm gì](#1-hệ-thống-làm-gì-và-không-làm-gì)
2. [Cấu hình bắt buộc: chọn cổng AI](#2-cấu-hình-bắt-buộc-chọn-cổng-ai)
3. [Cấu hình nên có: cookie Facebook](#3-cấu-hình-nên-có-cookie-facebook)
4. [Cấu hình tuỳ chọn: kết nối Facebook Page](#4-cấu-hình-tuỳ-chọn-kết-nối-facebook-page)
5. [Luồng A — Phân tích một khách](#luồng-a--phân-tích-một-khách)
6. [Luồng B — Trò chuyện nhiều lượt](#luồng-b--trò-chuyện-nhiều-lượt)
7. [Luồng C — Chuỗi 10 tin & lịch 20h](#luồng-c--chuỗi-10-tin--lịch-20h)
8. [Luồng D — Dùng bằng dòng lệnh](#luồng-d--dùng-bằng-dòng-lệnh)
9. [Hiểu các trạng thái và thông báo](#9-hiểu-các-trạng-thái-và-thông-báo)
10. [Xử lý sự cố](#10-xử-lý-sự-cố)

---

## 1. Hệ thống làm gì, và không làm gì

Nó đọc **trang Facebook công khai** của một người, rồi soạn tin nhắn làm quen
dựa trên những gì **thật sự đọc được**.

Ba ranh giới quyết định cách bạn dùng nó — biết trước sẽ đỡ hiểu nhầm:

**Không bịa.** Mọi câu đều phải truy vết về bằng chứng có thật. Đọc được ít thì
hệ thống nói ít, và đánh dấu `PARTIAL_OR_PRIVATE`. Một hồ sơ trống không phải
lỗi — nó là sự thật về trang đó.

**Không chào bán.** Mọi tin đều qua kiểm duyệt tự động; câu nào nhắc giá, khuyến
mãi, sản phẩm đều bị loại và sinh lại. Đây là tin làm quen, không phải tin bán
hàng.

**Chỉ gửi cho người đã chủ động nhắn Page của bạn trước.** Đây là luật của
Facebook, không phải lựa chọn của hệ thống: không có cách hợp lệ nào nhắn một
profile cá nhân chưa từng liên hệ bạn. Với nhóm đó, hệ thống soạn sẵn và bạn tự
gửi tay — xem [Luồng B](#luồng-b--trò-chuyện-nhiều-lượt).

---

## 2. Cấu hình bắt buộc: chọn cổng AI

**Không làm bước này thì không chạy được gì cả.** Hệ thống không kèm sẵn khoá AI
nào, và cố tình không chọn thay bạn.

Vào **Cài đặt** → mục *Cổng AI*. Có hai lựa chọn:

| | Đăng nhập Google (CLIProxy) | Google API Key |
|---|---|---|
| Cài đặt | Cần CLIProxy chạy (có sẵn trong Docker) | Dán một dòng khoá |
| Hạn mức | Rộng, hợp chạy thật | Bản miễn phí dễ hết |
| Nên dùng khi | Chạy cả pipeline nhiều lần | Thử nhanh, không Docker |

Một lần phân tích gọi model **7–14 lượt**. Hạn mức miễn phí thường hết giữa
chừng, nên nếu định chạy nhiều, chọn đường Google.

### Đường 1 — Đăng nhập Google

1. Bấm **Đăng nhập Google** → trình duyệt mở trang Google.
2. Đăng nhập, đồng ý cấp quyền.
3. Google chuyển về một URL. Nếu trang không tự quay lại, **sao chép toàn bộ URL
   đó** rồi dán vào ô *Gặp lỗi khi Google quay về?* trong Cài đặt.

### Đường 2 — Google API Key

1. Lấy khoá tại [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Dán vào ô **API key** → **Lưu**.

Khoá được mã hoá trước khi lưu và **không bao giờ** hiện lại.

### Chọn model

Sau khi kết nối, mục *Chọn model* hiện danh sách **lấy trực tiếp từ cổng đang
chọn** — không phải danh sách viết cứng trong code. Chọn một model rồi bấm
**Kiểm tra kết nối**.

Mỗi model ghi rõ **đọc được ảnh** hay không. Chọn model không đọc được ảnh thì
`visual_context` sẽ luôn trống, và chất lượng gợi ý giảm rõ rệt — ảnh đại diện
thường là nguồn dữ kiện giàu nhất của một trang Facebook.

> **Có model nằm trong danh sách nhưng đã ngừng phục vụ.** Luôn bấm *Kiểm tra
> kết nối* trước khi chạy thật, nếu không bạn sẽ chờ 70 giây rồi nhận lỗi.

---

## 3. Cấu hình nên có: cookie Facebook

Không có cookie, Facebook **che tiêu đề và nội dung bài viết** với khách chưa
đăng nhập — kể cả bài để chế độ Công khai. Hệ thống chỉ đọc được tên và ảnh.

Có cookie thì gợi ý bám được vào nội dung bài đăng, không chỉ vào ảnh. Khác biệt
rất lớn về chất lượng.

**Rủi ro, nói trước khi bạn dán:** cookie cho hệ thống đọc Facebook **dưới danh
nghĩa tài khoản của bạn**. Facebook có thể gắn cờ hoặc khoá tài khoản bị dùng để
truy cập tự động. Cân nhắc dùng một **tài khoản phụ của chính bạn**. Chỉ dán
cookie của chính bạn — dùng tài khoản người khác là sai cả pháp lý lẫn điều
khoản Facebook.

**Cách lấy:**

1. Mở `facebook.com` đã đăng nhập.
2. `F12` → tab **Network** → tải lại trang → chọn một request bất kỳ.
3. Ở mục *Request Headers*, sao chép **toàn bộ** giá trị của header `Cookie`.
4. Dán vào Cài đặt → *Cookie Facebook* → **Kiểm tra & lưu cookie**.

Chuỗi phải chứa `c_user` và `xs`. Hệ thống ping thử Facebook **trước khi lưu**
để bạn biết ngay cookie còn sống hay đã hết hạn.

---

## 4. Cấu hình tuỳ chọn: kết nối Facebook Page

Bước này bật **gửi và nhận tự động**. Không làm thì hệ thống vẫn chạy đầy đủ,
chỉ là bạn gửi tin bằng tay.

### Trước khi làm, hiểu giới hạn

Facebook chỉ cho gửi tin tới người **đã chủ động nhắn Page của bạn trước**.
Không có ngoại lệ, không có quyền nào mở được điều này.

Nên cách dùng đúng không phải đi tìm người để nhắn, mà **làm khách mở lời
trước**, rồi AI lo toàn bộ phần sau:

- Quảng cáo **Click-to-Messenger** (cách đạt quy mô lớn)
- Nút **Messenger** gắn trên website
- Link `m.me/<page>` đặt ở bio, bài đăng, chữ ký email
- **Mã QR** của Page in trên bao bì, tại quầy

Mỗi người bấm vào là một khách mà hệ thống gửi tự động được ngay.

### Bảy bước

Hướng dẫn đầy đủ nằm ngay trong **Cài đặt → Kết nối Facebook Page → "Chưa có
Page? Xem hướng dẫn từng bước"**, kèm ô copy sẵn Webhook URL. Tóm tắt:

1. Tạo **Facebook Page** (miễn phí, không cần duyệt).
2. Tạo **Meta App** tại `developers.facebook.com` → loại **Business**.
3. Trong App: **Add Product → Messenger → Set Up**.
4. **Settings → Access Tokens → Add or Remove Pages** → chọn Page → **Generate
   Token**. Dán token vào Cài đặt.
5. Đặt `MESSENGER_APP_SECRET` (App → Settings → Basic) và
   `MESSENGER_VERIFY_TOKEN` (chuỗi bạn tự đặt) vào `.env`, rồi:
   ```bash
   docker compose up -d --force-recreate api
   ```
   Dùng `--force-recreate`, **không** phải `restart` — `restart` không nạp lại
   `.env`.
6. Mở một đường HTTPS công khai (Facebook không gọi được `localhost`):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
7. App → Messenger → **Webhooks → Add Callback URL**: dán URL ở bước 6 cộng
   `/api/messenger/webhook`, và Verify Token ở bước 5. Rồi **Add Subscriptions**
   cho Page, tick `messages`.

### Hai chỗ sai phổ biến nhất

- **Dán User Access Token thay vì Page Access Token.** Hệ thống từ chối ngay lúc
  lưu, không để bạn phát hiện lúc đang nói chuyện với khách.
- **Chọn nhầm Page.** Nếu bạn quản lý nhiều Page, token phải thuộc đúng Page mà
  khách đã nhắn.

### Chế độ Phát triển

App mới ở chế độ **Development**: chỉ nhắn được cho người có **vai trò** trong
app (Admin / Developer / Tester). Để thử, thêm tài khoản test vào **App Roles →
Testers** và chấp nhận lời mời từ tài khoản đó.

Muốn nhắn mọi khách thật thì phải qua **App Review** cho quyền `pages_messaging`
— cần Privacy Policy URL, app icon, hạng mục, Business Verification và video
minh hoạ. Tên app **không được chứa** "Messenger", "Facebook", "Instagram",
"Meta" (tên thương hiệu của họ).

---

## Luồng A — Phân tích một khách

Đây là luồng gốc của đề bài: một URL vào, một hồ sơ ra.

1. Vào **Phân tích**.
2. Dán URL trang Facebook công khai → **Bắt đầu phân tích**.
3. Theo dõi tiến trình theo từng bước: thu thập → đọc ảnh → dựng hồ sơ → sinh
   tin → kiểm duyệt.

**Kết quả gồm:**

| Phần | Ý nghĩa |
|---|---|
| Tên khách | `null` nếu không đọc được — không đoán |
| Bối cảnh hình ảnh | Model mô tả ảnh đại diện. Trống nếu model không đọc được ảnh |
| Góc đồng cảm cốt lõi | Điểm chung để bắt chuyện |
| Chuỗi 10 tin | Tin làm quen, đã qua kiểm 0% chào bán |
| Bằng chứng | Trích dẫn nguyên văn cho từng dữ kiện |

Bấm **Tải output.json** để lấy JSON đúng định dạng nộp bài.

### Nếu trang bị khoá

Hệ thống trả `PARTIAL_OR_PRIVATE` và nói rõ **đọc được tới đâu**. Đây là kết quả
hợp lệ, không phải lỗi.

Khi đó dùng **đường dán tay**: tự mở trang, sao chép phần nội dung bạn nhìn
thấy, dán vào ô *Nội dung tự dán*. Hệ thống xử lý y hệt, chỉ khác nguồn dữ liệu.

### Phân tích lại

Gọi lại cùng URL **không** chạy lại — hệ thống trả bản ghi cũ, không tốn lượt
gọi model nào. Muốn chạy lại thật, bật **Phân tích lại** (API: `refresh: true`).

---

## Luồng B — Trò chuyện nhiều lượt

Khác Luồng A ở chỗ: chuỗi 10 tin sinh một lần rồi thôi, còn đây là **cuộc trò
chuyện đang diễn ra** — gợi ý lượt sau đọc được phản hồi của khách.

```
Bắt đầu phiên  →  AI đọc bài đăng + ảnh  →  gợi ý lượt 1
     ↓
bạn chọn một câu  →  bấm Gửi
     ↓
khách trả lời  →  gợi ý lượt 2 (bám vào câu họ vừa nói)
     ↓
          … lặp lại …
```

### Bắt đầu

Ở trang kết quả phân tích, bấm **Bắt đầu phiên làm việc**. Hệ thống sinh ngay
gợi ý lượt đầu và chuyển bạn sang trang hội thoại.

Các phiên đang mở nằm ở menu **Hội thoại**.

### Gửi tin — hai đường

Giao diện tự chọn đường đúng; bạn không phải quyết định.

**Đường tự động** (khi người này đã nhắn Page và bạn đã kết nối Page): nút ghi
**"Gửi"**. Bấm là tin đi thẳng qua Send API. Khách trả lời thì hội thoại **tự
cập nhật**, kèm gợi ý lượt kế — không phải làm gì thêm.

**Đường thủ công** (mọi trường hợp còn lại): nút ghi **"Gửi qua Messenger"**.
Bấm thì hệ thống:

1. Chép nội dung vào clipboard
2. Mở **trang cá nhân** của khách ở tab mới

Bạn bấm **Nhắn tin** trên trang đó, dán (`Ctrl+V`), Enter.

> **Vì sao mở trang cá nhân chứ không mở thẳng khung chat?** Facebook không còn
> URL điều hướng được tới chat cá nhân — đã thử `m.me`, `messenger.com/t/…` và
> `facebook.com/messages/t/…`, cả ba đều hỏng. Bấm "Nhắn tin" mở khung chat ngay
> trong trang, URL không đổi. Thêm một cú bấm, nhưng luôn đúng.

Sau khi gửi, dán câu trả lời của khách vào ô **Phản hồi của khách** → **Ghi phản
hồi & gợi ý tiếp**. AI đọc câu đó và gợi ý lượt mới.

### Khi khách nhắn Page trước

Nếu đã bật webhook, một người nhắn Page sẽ **tự tạo hội thoại mới** trong mục
Hội thoại, kèm gợi ý trả lời — không ai phải bấm gì. Hội thoại đó chưa gắn
profile nào, hiện là *"Khách từ Messenger (chưa gán profile)"*.

### Gợi ý bị trống

Nếu lượt nào không có gợi ý, hệ thống **nói rõ lý do** thay vì để bạn nhìn danh
sách rỗng. Thường là cả lô bị kiểm duyệt loại. Bạn tự viết ở ô soạn là được.

---

## Luồng C — Chuỗi 10 tin & lịch 20h

**Outbox** chứa chuỗi 10 tin sinh sẵn cho từng khách đã phân tích.

Mỗi ngày **20:00** (giờ Việt Nam), hệ thống tự sinh một "evening hook" cho các
profile đang chờ và đẩy vào Outbox. Trạng thái lịch xem ở **Dashboard**.

Với mỗi mục trong Outbox bạn có thể: **Sao chép** → tự gửi → bấm **Đã gửi tay**,
hoặc **Bỏ qua**.

> **Outbox không bao giờ được gửi tự động.** Đây là nội dung soạn cho người
> **chưa hề liên hệ** bạn; gửi tự động chỗ đó đúng là tin nhắn rác. Hệ thống
> không có đường nào làm việc đó, và có test canh để nó không mọc ra.

Bấm **Chạy ngay** nếu muốn kiểm chứng mà không chờ tới 20h.

---

## Luồng D — Dùng bằng dòng lệnh

Dùng khi muốn chạy hàng loạt hoặc ghép vào script khác.

```bash
# Cơ bản
python main.py --url "https://www.facebook.com/<user>"

# Chỉ định cổng và model
python main.py --url "..." --provider google_api_key --model gemini-x

# Không cần mạng — đọc từ nội dung đã dán sẵn
python main.py --profile-file samples/pasted_profile.txt

# Không ghi DB, xuất ra file
python main.py --url "..." --no-db --out output.json

# Che thông tin cá nhân trong output
python main.py --url "..." --mask-pii
```

Hai điều đảm bảo, để script gọi không phải xử lý ngoại lệ:

- **stdout chỉ có đúng một chuỗi JSON.** Mọi log đi stderr, nên
  `python main.py --url … > output.json` luôn ra file parse được.
- **Mọi nhánh đều in JSON hợp lệ**, kể cả khi lỗi không lường trước.

Exit code: `0` cho `SUCCESS` và `PARTIAL_OR_PRIVATE`, `1` cho `ERROR` và
`FAILED_VALIDATION`. `PARTIAL_OR_PRIVATE` **là kết quả đạt** nên không trả mã
lỗi.

---

## 9. Hiểu các trạng thái và thông báo

### Trạng thái profile

| Trạng thái | Nghĩa |
|---|---|
| `SUCCESS` | Đọc được đủ dữ kiện, sinh nội dung bình thường |
| `PARTIAL_OR_PRIVATE` | Trang bị khoá hoặc đọc được quá ít. **Là kết quả đạt** |
| `FAILED_VALIDATION` | Sinh lại 2 lượt vẫn không qua kiểm duyệt. Không trả nội dung bẩn |
| `ERROR` | Lỗi hệ thống hoặc lỗi cổng model |

### Nhãn kiểm duyệt

**`ZERO_SALES_CONFIRMED`** chỉ hiện khi thật sự có nội dung và nội dung đó đã
qua `ZeroSalesValidator`. Nếu chuỗi tin trống, nhãn này **không** hiện — xác
nhận "0% chào bán" cho một chuỗi rỗng vừa vô nghĩa vừa gây hiểu nhầm là đã duyệt.

### Mã lỗi thường gặp

| Mã | Nghĩa | Làm gì |
|---|---|---|
| `E-LLM-409-NOCONF` | Chưa chọn cổng model | Vào Cài đặt chọn cổng |
| `E-LLM-409-AUTH` | Hết phiên hoặc sai API key | Kết nối lại. **Đừng thử lại nhiều lần** — sai khoá 5 lần có thể bị chặn IP 30 phút |
| `E-MSG-409-OFF` | Chưa kết nối Page | Cài đặt → Kết nối Facebook Page |
| `E-MSG-409-NOLINK` | Người này chưa nhắn Page | Mời họ nhắn Page trước; hoặc dùng đường thủ công |
| `E-MSG-409-WINDOW` | Quá 7 ngày kể từ tin cuối của họ | Chờ họ nhắn lại |

---

## 10. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| Danh sách model trống | Chưa kết nối cổng, hoặc CLIProxy chưa chạy | Kiểm tra Cài đặt; `docker compose ps` xem `cliproxy` |
| Phân tích chạy rất lâu rồi lỗi | Model đã chọn ngừng phục vụ | Bấm **Kiểm tra kết nối**, đổi model khác |
| Luôn ra `PARTIAL_OR_PRIVATE` | Facebook che nội dung với khách chưa đăng nhập | Thêm cookie (mục 3), hoặc dùng đường dán tay |
| `visual_context` luôn trống | Model không đọc được ảnh | Chọn model có nhãn *đọc được ảnh* |
| Gọi lại cùng URL không chạy lại | Dedupe có chủ đích để khỏi tốn lượt gọi model | Bật **Phân tích lại** |
| Bấm "Gửi" báo chưa liên kết | Người này chưa nhắn Page | Dùng đường thủ công, hoặc mời họ nhắn Page |
| Sửa `.env` mà không có tác dụng | `restart` **không** nạp lại `.env` | `docker compose up -d --force-recreate api` |
| Webhook không nhận tin | Chữ ký sai, hoặc tunnel đã đổi URL | Kiểm `MESSENGER_APP_SECRET` khớp App Secret thật; dán lại Callback URL |
| Lịch 20h không chạy | Scheduler tắt hoặc chưa khởi động | Xem trạng thái ở **Dashboard** |

### Xem log

```bash
docker compose logs -f api      # API + scheduler
docker compose logs -f web      # nginx
docker compose logs -f cliproxy # cổng model
```

Secret **không bao giờ** xuất hiện trong log. Nếu bạn thấy một giá trị trông như
khoá, đó là lỗi cần báo.
