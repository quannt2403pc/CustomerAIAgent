# Cỗ máy AI Profiler & Rapport

> ### 📖 [**HƯỚNG DẪN SỬ DỤNG — đọc file này trước**](HUONG_DAN_SU_DUNG.md)
>
> Cài đặt xong thì **chưa chạy được gì cả**: hệ thống không kèm sẵn khoá AI nào
> và cố tình không chọn thay bạn. File trên hướng dẫn từng bước cấu hình và
> toàn bộ các luồng sử dụng. README này chỉ lo phần **cài đặt**.

Đọc trang Facebook công khai của một khách hàng, dựng hồ sơ dựa trên bằng chứng
có thật, rồi soạn chuỗi tin nhắn làm quen **0% chào bán**.

---

## Mục lục

- [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
- [Cách 1 — Chạy bằng Docker (khuyến nghị)](#cách-1--chạy-bằng-docker-khuyến-nghị)
- [Cách 2 — Chạy không Docker](#cách-2--chạy-không-docker)
- [Biến môi trường](#biến-môi-trường)
- [Kiểm tra cài đặt thành công](#kiểm-tra-cài-đặt-thành-công)
- [Chạy test](#chạy-test)
- [Xử lý sự cố khi cài](#xử-lý-sự-cố-khi-cài)

---

## Yêu cầu hệ thống

| | Docker | Không Docker |
|---|---|---|
| Docker Desktop / Engine | ✅ bắt buộc (kèm Compose v2) | — |
| Python | — | **3.12+** |
| Node.js | — | **20+** |
| PostgreSQL | — | **16** |
| RAM trống | ~2 GB | ~1 GB |

Ngoài ra, cả hai cách đều cần **một tài khoản Google** (để đăng nhập cổng AI)
**hoặc** một **Google API key**.

---

## Cách 1 — Chạy bằng Docker (khuyến nghị)

Toàn bộ 4 service lên bằng một lệnh: PostgreSQL, CLIProxy, API, và web.

### Bước 1 — Lấy mã nguồn

```bash
git clone <URL-repo>
cd CustomerAIAgent
```

### Bước 2 — Tạo file `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền **hai** giá trị bắt buộc:

```bash
# Sinh khoá mã hoá (bắt buộc — thiếu thì hệ thống dừng ngay khi khởi động)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```ini
APP_ENCRYPTION_KEY=<dán khoá vừa sinh>
POSTGRES_PASSWORD=<tự đặt một mật khẩu>
```

> Hệ thống **không** lưu secret dạng plaintext. Thiếu `APP_ENCRYPTION_KEY` thì
> nó báo lỗi rõ ràng và dừng, thay vì âm thầm chạy ở chế độ kém an toàn.

### Bước 3 — Sinh khoá quản trị CLIProxy

Chỉ cần thêm **một dòng** vào `.env`. Sinh khoá:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```ini
CLIPROXY_MGMT_KEY=<dán khoá vừa sinh>
```

**Không** phải tự tạo hay sửa `cliproxy/config.yaml`. Service `cliproxy-init`
chạy trước `cliproxy` sẽ tự tạo file đó từ bản mẫu và tiêm khoá vào — `.env` là
nguồn sự thật duy nhất, nên hai giá trị không bao giờ lệch nhau.

> Để rỗng thì `docker compose up` **dừng ngay** với thông báo rõ ràng, chứ không
> chạy nửa vời. Khoá rỗng khiến route quản trị của CLIProxy trả 404 và trang Cài
> đặt không đăng nhập Google được — một lỗi rất khó đoán nguyên nhân.
>
> Cả `.env` lẫn `cliproxy/config.yaml` đều đã nằm trong `.gitignore`.

### Bước 4 — Khởi động

```bash
docker compose up -d --build
```

Lần đầu mất vài phút để tải image và build. Migration database chạy **tự động**
khi API khởi động.

### Bước 5 — Mở ứng dụng

| Dịch vụ | Địa chỉ |
|---|---|
| Giao diện web | <http://localhost:5173> |
| API | <http://localhost:8000> |
| Health check | <http://localhost:8000/health> |

➡️ **Tiếp theo:** [Hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md) — mục *Cấu hình bắt
buộc: chọn cổng AI*.

### Lệnh thường dùng

```bash
docker compose ps                        # trạng thái các service
docker compose logs -f api               # xem log API
docker compose down                      # dừng (giữ dữ liệu)
docker compose down -v                   # dừng và XOÁ SẠCH dữ liệu
docker compose up -d --force-recreate api  # áp dụng thay đổi trong .env
```

> ⚠️ **`docker compose restart` KHÔNG nạp lại `.env`.** Sửa biến môi trường xong
> phải dùng `up -d --force-recreate`, nếu không bạn sẽ tưởng cấu hình đã có hiệu
> lực trong khi nó chưa.

---

## Cách 2 — Chạy không Docker

Cần tự chuẩn bị PostgreSQL 16. CLIProxy không bắt buộc — nếu bỏ qua thì dùng
**Google API Key** thay vì đăng nhập Google.

### Bước 1 — Database

Tạo database và user trong PostgreSQL 16:

```sql
CREATE USER appuser WITH PASSWORD 'mat-khau-cua-ban';
CREATE DATABASE customeraiagent OWNER appuser;
```

### Bước 2 — Backend

```bash
# Môi trường ảo
python -m venv .venv

# Kích hoạt — Windows
.venv\Scripts\activate
# Kích hoạt — macOS / Linux
source .venv/bin/activate

# Cài phụ thuộc
pip install -r requirements.txt

# Thêm công cụ phát triển (pytest, ruff, mypy) nếu cần chạy test
pip install -r requirements-dev.txt
```

### Bước 3 — Cấu hình

```bash
cp .env.example .env
```

Sửa `.env`:

```ini
DATABASE_URL=postgresql+psycopg://appuser:mat-khau-cua-ban@localhost:5432/customeraiagent
APP_ENCRYPTION_KEY=<sinh như Cách 1, Bước 2>
CORS_ORIGINS=http://localhost:5173
```

Nếu **không** chạy CLIProxy, điền thêm khoá Google và chọn cổng:

```ini
LLM_PROVIDER=google_api_key
GOOGLE_API_KEY=<khoá của bạn>
```

### Bước 4 — Migration

```bash
alembic upgrade head
```

### Bước 5 — Chạy API

```bash
python run.py              # http://127.0.0.1:8000
python run.py --reload     # chế độ phát triển, tự nạp lại khi sửa code
```

> Dùng `python run.py`, **không** dùng `uvicorn app.main:app` trực tiếp. Trên
> Windows, event loop policy phải được đặt **trước khi** loop đầu tiên được tạo;
> `uvicorn` dựng loop rồi mới import ứng dụng — lúc đó đã muộn và kết nối
> database sẽ hỏng.

### Bước 6 — Chạy frontend

Mở một terminal khác:

```bash
cd web
npm install
npm run dev     # http://localhost:5173
```

### (Tuỳ chọn) Bước 7 — CLIProxy

Chỉ cần nếu muốn **đăng nhập Google** thay vì dùng API key. Tải CLIProxy, tạo
`config.yaml` theo mẫu `cliproxy/config.example.yaml`, rồi:

```bash
./CLIProxyAPI -config ./cliproxy/config.yaml
```

> Cổng **51121 bắt buộc phải mở**. Google chuyển hướng OAuth về
> `http://localhost:51121/oauth-callback`; thiếu cổng này thì token **không bao
> giờ** được lưu, và lỗi hiện ra rất khó đoán nguyên nhân.

### (Tuỳ chọn) Bước 8 — Playwright

Chỉ cần nếu muốn đọc những trang render bằng JavaScript:

```bash
pip install -r requirements-playwright.txt
playwright install chromium
```

Rồi đặt `PLAYWRIGHT_ENABLED=true` trong `.env`.

---

## Biến môi trường

Toàn bộ danh sách nằm trong `.env.example` kèm giải thích. Những biến quan trọng
nhất:

### Bắt buộc

| Biến | Ý nghĩa |
|---|---|
| `APP_ENCRYPTION_KEY` | Khoá Fernet mã hoá secret at-rest. Thiếu → hệ thống dừng |
| `DATABASE_URL` | Chuỗi kết nối PostgreSQL |
| `POSTGRES_PASSWORD` | Chỉ dùng cho Docker |

### Cổng AI (chọn một)

| Biến | Ý nghĩa |
|---|---|
| `CLIPROXY_MGMT_KEY` | Khoá quản trị CLIProxy. **Docker:** chỉ đặt ở đây, `cliproxy-init` tự tiêm vào `config.yaml`. **Không Docker:** phải tự đặt trùng với `remote-management.secret-key` |
| `GOOGLE_API_KEY` | Dùng khi đi đường API key trực tiếp |
| `LLM_PROVIDER` | `antigravity` hoặc `google_api_key`. Để trống = buộc chọn trên UI |

### Facebook Page — gửi/nhận tự động (tuỳ chọn)

| Biến | Ý nghĩa |
|---|---|
| `MESSENGER_APP_SECRET` | App Secret của Meta App. Dùng kiểm chữ ký webhook |
| `MESSENGER_VERIFY_TOKEN` | Chuỗi bạn **tự đặt**, Facebook gửi lại khi xác minh webhook |

> Thiếu `MESSENGER_APP_SECRET` thì hệ thống **từ chối mọi webhook**. Đó là hành
> vi đúng: không xác thực được tin đến thì chấp nhận nó còn nguy hiểm hơn là từ
> chối — bất kỳ ai cũng bơm được dữ liệu khách giả vào hệ thống.

### Thu thập dữ liệu (tuỳ chọn)

| Biến | Ý nghĩa |
|---|---|
| `FACEBOOK_COOKIE` | Cookie của **chính bạn**. Đường chính là lưu qua UI; biến này chỉ dành cho CLI |
| `PLAYWRIGHT_ENABLED` | Bật lớp đọc trang render JS |

---

## Kiểm tra cài đặt thành công

```bash
curl http://localhost:8000/health
```

Kết quả mong đợi:

```json
{
  "status": "ok",
  "db": "ok",
  "provider": null,
  "model": null,
  "dry_run": true,
  "scheduler": {
    "enabled": true,
    "running": true,
    "next_run_at": "2026-10-08T20:00:00+07:00",
    "cron": "20:00 Asia/Ho_Chi_Minh",
    "detail": ""
  }
}
```

`provider` và `model` là `null` ở lần chạy đầu — **đúng như vậy**. Hệ thống buộc
bạn tự chọn cổng AI trên giao diện; nó không chọn thay bạn.

Mở <http://localhost:5173>, thấy Dashboard là xong phần cài đặt.

➡️ Tiếp tục với [Hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md).

---

## Chạy test

```bash
# Backend
pytest -q

# Kiểm tra định dạng và lint
ruff check app tests
ruff format --check app tests

# Frontend
cd web
npx tsc --noEmit --project tsconfig.app.json
npx eslint src --max-warnings 0
```

Bộ test không gọi mạng thật và không cần khoá AI — nó dùng HTTP giả lập
(`respx`).

---

## Xử lý sự cố khi cài

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Thiếu APP_ENCRYPTION_KEY` | Chưa sinh khoá | Làm Bước 2 của Cách 1 |
| API không lên, log báo lỗi kết nối DB | Postgres chưa sẵn sàng, hoặc sai `DATABASE_URL` | `docker compose ps` xem `db` có `healthy` chưa |
| Cổng đã bị chiếm (`port is already allocated`) | Có dịch vụ khác dùng 5432/8000/5173 | Đổi phần cổng máy chủ trong `docker-compose.yml` |
| Trang Cài đặt không đăng nhập Google được | `CLIPROXY_MGMT_KEY` lệch với `config.yaml` | Đặt lại cho **trùng nhau**, rồi `up -d --force-recreate` |
| Google chuyển hướng xong báo lỗi | Cổng 51121 chưa mở | Mở cổng 51121; hoặc dán URL callback vào ô trong Cài đặt |
| Sửa `.env` mà không có tác dụng | `restart` không nạp lại `.env` | `docker compose up -d --force-recreate api` |
| Docker tạo **thư mục** `cliproxy/config.yaml` | Chưa tạo file trước khi `up` | Xoá thư mục đó, `cp cliproxy/config.example.yaml cliproxy/config.yaml`, chạy lại |
| `python run.py` lỗi event loop trên Windows | Chạy `uvicorn` trực tiếp | Dùng `python run.py` |
| `npm run dev` không gọi được API | CORS | Đặt `CORS_ORIGINS=http://localhost:5173` trong `.env`, khởi động lại API |

### Khởi động lại từ đầu

```bash
docker compose down -v     # ⚠️ XOÁ SẠCH database
docker compose up -d --build
```

---

## Cấu trúc thư mục

```
app/
  collectors/   # đọc dữ liệu Facebook (og:meta, HTML, Playwright)
  core/         # cấu hình, lỗi, mã hoá, middleware, rate limit
  llm/          # hai cổng model + phân giải danh mục
  messenger/    # Facebook Page: gửi tin + xác thực webhook
  models/       # bảng SQLAlchemy
  routers/      # endpoint HTTP
  schemas/      # DTO Pydantic (gồm cả strict JSON nộp bài)
  services/     # pipeline, kiểm duyệt, hội thoại, lịch 20h
alembic/        # migration database
tests/          # test backend + canh gác luật thép
web/            # React 18 + TypeScript + Vite
main.py         # CLI một URL → một JSON
run.py          # khởi động API khi không dùng Docker
```

---

## Giấy phép & phạm vi

Dự án thực tập nội bộ. Hệ thống chỉ gửi tin cho người đã **chủ động nhắn Page**
của bạn trước; với mọi người khác nó chỉ soạn nháp để con người tự gửi. Chi tiết
và lý do: [Hướng dẫn sử dụng](HUONG_DAN_SU_DUNG.md), mục 1 và mục 4.
