# Cỗ máy AI Profiler & Rapport

Đọc trang Facebook công khai của một khách hàng, dựng hồ sơ **dựa trên bằng chứng
có thật**, rồi soạn chuỗi tin nhắn làm quen **0% chào bán**.

![Màn hình chính](docs/images/01-dashboard.jpg)

---

> ## 📖 [HƯỚNG DẪN SỬ DỤNG — mở file này sau khi cài xong](HUONG_DAN_SU_DUNG.md)
>
> **Cài đặt xong thì phần mềm vẫn chưa chạy được gì.** Nó không đi kèm sẵn tài
> khoản AI nào và cố ý không tự chọn thay bạn — bạn phải tự bật "bộ não" AI.
>
> File trên hướng dẫn **từng bước, có ảnh chụp màn hình**, viết cho người không
> rành kỹ thuật. README này chỉ lo phần **cài đặt**.

---

## Chọn cách cài

| | **Cách 1 — Docker** | **Cách 2 — Thủ công** |
|---|---|---|
| Độ khó | ⭐ Dễ | ⭐⭐⭐ Cần quen dòng lệnh |
| Thời gian | ~10 phút | ~30 phút |
| Cần cài sẵn | Docker Desktop | Python 3.12+, Node.js 20+, PostgreSQL 16 |
| Phù hợp | **Hầu hết mọi người** | Khi không cài được Docker |

👉 **Không chắc chọn gì? Dùng Cách 1.**

Cả hai cách đều cần thêm **một tài khoản Google** (để đăng nhập AI) **hoặc** một
**Google API key**. Lấy ở bước nào thì [Hướng dẫn sử dụng, mục 3](HUONG_DAN_SU_DUNG.md#3-bật-bộ-não-ai-bắt-buộc) nói rõ.

---

# Cách 1 — Docker

Một lệnh là cả 4 thành phần cùng chạy: cơ sở dữ liệu, cổng AI, máy chủ, và giao diện web.

## Bước 1 — Tải mã nguồn

```bash
git clone <URL-repo>
cd CustomerAIAgent
```

## Bước 2 — Tạo file cấu hình

```bash
cp .env.example .env
```

File `.env` vừa tạo cần **ba dòng** bạn tự điền. Sinh hai mã ngẫu nhiên trước:

```bash
# Mã khoá để mã hoá dữ liệu nhạy cảm
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Mã quản trị cổng AI
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Mở `.env` bằng trình soạn thảo bất kỳ (Notepad cũng được) và điền:

```ini
APP_ENCRYPTION_KEY=<dán mã thứ nhất>
CLIPROXY_MGMT_KEY=<dán mã thứ hai>
POSTGRES_PASSWORD=<tự nghĩ một mật khẩu bất kỳ>
```

> ℹ️ **Không cần đụng tới `cliproxy/config.yaml`.** Hệ thống tự tạo file đó và tự
> điền mã vào — `.env` là nguồn duy nhất, nên hai nơi không bao giờ lệch nhau.
>
> Để trống `APP_ENCRYPTION_KEY` thì hệ thống **dừng ngay** kèm thông báo rõ ràng,
> chứ không âm thầm chạy ở chế độ kém an toàn.

## Bước 3 — Khởi động

```bash
docker compose up -d --build
```

Lần đầu mất vài phút để tải và dựng. Cơ sở dữ liệu tự tạo bảng, bạn không phải làm gì.

## Bước 4 — Mở trình duyệt

| Mở cái gì | Địa chỉ |
|---|---|
| **Giao diện chính** | <http://localhost:5173> |
| Máy chủ (cho người kỹ thuật) | <http://localhost:8000> |
| Kiểm tra sức khoẻ | <http://localhost:8000/health> |

✅ Thấy màn hình Dashboard là cài xong.

➡️ **Bước tiếp theo:** [Hướng dẫn sử dụng → mục 3: Bật "bộ não" AI](HUONG_DAN_SU_DUNG.md#3-bật-bộ-não-ai-bắt-buộc)

## Các lệnh dùng về sau

```bash
docker compose ps                          # xem cái gì đang chạy
docker compose logs -f api                 # xem nhật ký
docker compose down                        # tắt (dữ liệu vẫn còn)
docker compose up -d --force-recreate api  # áp dụng thay đổi trong .env
docker compose down -v                     # ⚠️ tắt và XOÁ SẠCH dữ liệu
```

> ⚠️ **`docker compose restart` KHÔNG đọc lại file `.env`.** Sửa cấu hình xong
> phải dùng `up -d --force-recreate`, nếu không bạn sẽ tưởng đã có hiệu lực trong
> khi chưa.

---

# Cách 2 — Thủ công (không Docker)

Bạn tự chuẩn bị PostgreSQL 16. Cổng AI (CLIProxy) **không bắt buộc** — bỏ qua thì
dùng Google API Key thay cho Đăng nhập Google.

## Bước 1 — Tạo cơ sở dữ liệu

```sql
CREATE USER appuser WITH PASSWORD 'mat-khau-cua-ban';
CREATE DATABASE customeraiagent OWNER appuser;
```

## Bước 2 — Cài thư viện Python

```bash
python -m venv .venv

# Bật môi trường ảo — Windows
.venv\Scripts\activate
# Bật môi trường ảo — macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt    # chỉ cần nếu muốn chạy test
```

## Bước 3 — Cấu hình

```bash
cp .env.example .env
```

Sửa trong `.env`:

```ini
DATABASE_URL=postgresql+psycopg://appuser:mat-khau-cua-ban@localhost:5432/customeraiagent
APP_ENCRYPTION_KEY=<sinh như Cách 1, Bước 2>
CORS_ORIGINS=http://localhost:5173
```

Nếu **không** chạy CLIProxy, thêm:

```ini
LLM_PROVIDER=google_api_key
GOOGLE_API_KEY=<chìa khoá của bạn>
```

## Bước 4 — Tạo bảng

```bash
alembic upgrade head
```

## Bước 5 — Chạy máy chủ

```bash
python run.py              # http://127.0.0.1:8000
python run.py --reload     # chế độ phát triển
```

> ⚠️ **Dùng `python run.py`, đừng dùng `uvicorn app.main:app`.** Trên Windows,
> một thiết lập quan trọng phải được đặt **trước khi** chương trình khởi động;
> `uvicorn` khởi động rồi mới nạp ứng dụng — lúc đó đã muộn và kết nối cơ sở dữ
> liệu sẽ hỏng.

## Bước 6 — Chạy giao diện

Mở **cửa sổ dòng lệnh thứ hai**:

```bash
cd web
npm install
npm run dev     # http://localhost:5173
```

## Bước 7 (tuỳ chọn) — CLIProxy

Chỉ cần nếu muốn **đăng nhập Google** thay vì dùng API key:

```bash
cp cliproxy/config.example.yaml cliproxy/config.yaml
# sửa remote-management.secret-key cho TRÙNG với CLIPROXY_MGMT_KEY trong .env
./CLIProxyAPI -config ./cliproxy/config.yaml
```

> ⚠️ **Cổng 51121 bắt buộc phải mở.** Google chuyển hướng đăng nhập về
> `http://localhost:51121/oauth-callback`; thiếu cổng này thì việc đăng nhập
> **không bao giờ** lưu lại được, và thông báo lỗi rất khó đoán nguyên nhân.

## Bước 8 (tuỳ chọn) — Playwright

Chỉ cần nếu muốn đọc những trang Facebook hiển thị bằng JavaScript:

```bash
pip install -r requirements-playwright.txt
playwright install chromium
```

Rồi đặt `PLAYWRIGHT_ENABLED=true` trong `.env`.

---

# Kiểm tra cài đặt thành công

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
bạn tự chọn trên giao diện; nó không chọn thay bạn.

---

# Danh sách biến cấu hình

Toàn bộ nằm trong `.env.example` kèm giải thích. Những biến quan trọng nhất:

### Bắt buộc

| Biến | Ý nghĩa |
|---|---|
| `APP_ENCRYPTION_KEY` | Mã khoá bảo vệ dữ liệu nhạy cảm. Thiếu → hệ thống dừng |
| `DATABASE_URL` | Địa chỉ cơ sở dữ liệu |
| `POSTGRES_PASSWORD` | Chỉ dùng cho Docker |

### Cổng AI — chọn một

| Biến | Ý nghĩa |
|---|---|
| `CLIPROXY_MGMT_KEY` | **Docker:** chỉ đặt ở `.env`, hệ thống tự điền vào `config.yaml`.<br>**Thủ công:** phải tự đặt trùng với `remote-management.secret-key` |
| `GOOGLE_API_KEY` | Khi dùng đường API key trực tiếp |
| `LLM_PROVIDER` | `antigravity` hoặc `google_api_key`. Để trống = buộc chọn trên giao diện |

### Facebook Page — gửi/nhận tự động (tuỳ chọn)

| Biến | Ý nghĩa |
|---|---|
| `MESSENGER_APP_SECRET` | Mã bí mật của ứng dụng Meta, dùng để xác thực tin đến |
| `MESSENGER_VERIFY_TOKEN` | Chuỗi bạn **tự đặt**, Facebook gửi lại khi xác minh |

> ℹ️ Thiếu `MESSENGER_APP_SECRET` thì hệ thống **từ chối mọi tin đến**. Đó là
> hành vi đúng: nếu không xác thực được tin thật sự từ Facebook, chấp nhận nó còn
> nguy hiểm hơn là từ chối — bất kỳ ai cũng bơm được dữ liệu khách giả vào.

### Thu thập dữ liệu (tuỳ chọn)

| Biến | Ý nghĩa |
|---|---|
| `FACEBOOK_COOKIE` | Cookie của **chính bạn**. Nên dùng qua giao diện; biến này chỉ cho dòng lệnh |
| `PLAYWRIGHT_ENABLED` | Bật lớp đọc trang hiển thị bằng JavaScript |

---

# Cài bị lỗi?

| Thông báo / hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `Thiếu APP_ENCRYPTION_KEY` | Chưa sinh mã khoá | Làm lại Cách 1, Bước 2 |
| `CLIPROXY_MGMT_KEY chưa đặt` | Thiếu dòng này trong `.env` | Sinh mã rồi điền vào |
| Máy chủ không lên, báo lỗi kết nối DB | PostgreSQL chưa sẵn sàng | `docker compose ps` xem `db` đã `healthy` chưa |
| `port is already allocated` | Cổng bị phần mềm khác chiếm | Đổi số cổng trong `docker-compose.yml` |
| Không đăng nhập Google được | `CLIPROXY_MGMT_KEY` lệch với `config.yaml` | Đặt lại cho trùng, rồi `up -d --force-recreate` |
| Google chuyển hướng xong báo lỗi | Cổng 51121 chưa mở | Mở cổng, hoặc dán URL vào ô trong Cài đặt |
| Sửa `.env` mà không có tác dụng | `restart` không đọc lại `.env` | `docker compose up -d --force-recreate api` |
| Docker tạo **thư mục** `cliproxy/config.yaml` | Chạy `up` trước khi file tồn tại | Xoá thư mục đó rồi chạy lại `docker compose up -d` |
| `npm run dev` không gọi được máy chủ | Thiếu cấu hình CORS | Đặt `CORS_ORIGINS=http://localhost:5173` rồi khởi động lại |

### Làm lại từ đầu

```bash
docker compose down -v     # ⚠️ XOÁ SẠCH cơ sở dữ liệu
docker compose up -d --build
```

---

# Dành cho người phát triển

<details>
<summary>Chạy test, kiểm tra chất lượng mã</summary>

```bash
# Backend
pytest -q
ruff check app tests scripts main.py run.py
ruff format --check app tests scripts main.py run.py

# Frontend
cd web
npx tsc --noEmit --project tsconfig.app.json
npx eslint src --max-warnings 0
```

Bộ test **không gọi mạng thật** và **không cần chìa khoá AI** — nó dùng HTTP giả
lập (`respx`).

</details>

<details>
<summary>Dùng bằng dòng lệnh</summary>

```bash
python main.py --url "https://www.facebook.com/<user>"
python main.py --url "..." --provider google_api_key --model gemini-x
python main.py --profile-file samples/pasted_profile.txt   # không cần mạng
python main.py --url "..." --no-db --out output.json
python main.py --url "..." --mask-pii                      # che thông tin cá nhân
```

Hai điều bảo đảm, để script gọi không phải xử lý ngoại lệ:

- **stdout chỉ có đúng một chuỗi JSON.** Mọi nhật ký đi stderr, nên
  `python main.py --url … > output.json` luôn ra file đọc được.
- **Mọi nhánh đều in JSON hợp lệ**, kể cả khi gặp lỗi không lường trước.

Mã thoát: `0` cho `SUCCESS` và `PARTIAL_OR_PRIVATE`, `1` cho `ERROR` và
`FAILED_VALIDATION`. `PARTIAL_OR_PRIVATE` **là kết quả đạt** nên không trả mã lỗi.

</details>

<details>
<summary>Cấu trúc thư mục</summary>

```
app/
  collectors/   # đọc dữ liệu Facebook (og:meta, HTML, Playwright)
  core/         # cấu hình, lỗi, mã hoá, middleware, giới hạn tần suất
  llm/          # hai cổng AI + lấy danh mục model
  messenger/    # Facebook Page: gửi tin + xác thực tin đến
  models/       # bảng cơ sở dữ liệu
  routers/      # các endpoint HTTP
  schemas/      # định dạng dữ liệu (gồm JSON nộp bài)
  services/     # quy trình, kiểm duyệt, hội thoại, lịch 20h
alembic/        # thay đổi cấu trúc cơ sở dữ liệu
scripts/        # công cụ vận hành (đo a11y, chạy test 3 link)
tests/          # test backend + canh gác các luật an toàn
web/            # giao diện React + TypeScript
docs/images/    # ảnh dùng trong tài liệu
main.py         # dòng lệnh: một URL → một JSON
run.py          # khởi động máy chủ khi không dùng Docker
```

</details>

---

# Phạm vi & giới hạn

Hệ thống chỉ gửi tin cho người đã **chủ động nhắn Page của bạn trước** — đó là
luật của Facebook, không phải lựa chọn của phần mềm. Với mọi người khác, nó chỉ
soạn sẵn để bạn tự gửi.

Chi tiết và lý do: [Hướng dẫn sử dụng → mục 2 và mục 5](HUONG_DAN_SU_DUNG.md#2-ba-điều-nó-sẽ-không-làm).
