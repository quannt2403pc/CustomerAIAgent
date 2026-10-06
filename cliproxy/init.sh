#!/bin/sh
# Khởi tạo cliproxy/config.yaml TRƯỚC khi service `cliproxy` lên.
#
# Vì sao cần một service riêng (bẫy B8): nếu bind-mount `./cliproxy/config.yaml`
# mà file chưa tồn tại, Docker **tạo một thư mục** trùng tên; cliproxy sau đó
# chết với log vô nghĩa ("is a directory" ở tầng rất sâu).
set -eu

CONFIG=/work/config.yaml
EXAMPLE=/work/config.example.yaml

if [ -d "$CONFIG" ]; then
  echo "[cliproxy-init] LỖI: $CONFIG đang là THƯ MỤC (bẫy B8)." >&2
  echo "[cliproxy-init] Xoá nó rồi chạy lại: docker compose down && rm -rf cliproxy/config.yaml" >&2
  exit 1
fi

if [ ! -f "$CONFIG" ]; then
  echo "[cliproxy-init] Chưa có config.yaml → tạo từ bản mẫu."
  cp "$EXAMPLE" "$CONFIG"
fi

if [ -z "${CLIPROXY_MGMT_KEY:-}" ]; then
  echo "[cliproxy-init] LỖI: CLIPROXY_MGMT_KEY rỗng. Để rỗng thì route quản trị" >&2
  echo "[cliproxy-init] của CLIProxy trả 404 (bẫy B4). Sinh khoá rồi điền vào .env:" >&2
  echo '[cliproxy-init]   python -c "import secrets; print(secrets.token_urlsafe(32))"' >&2
  exit 1
fi

# Luôn áp lại khoá từ .env: .env là nguồn sự thật duy nhất. CLIProxy sẽ băm lại
# giá trị này khi khởi động (bẫy B5) — đó là hành vi bình thường.
sed -i "s|^\( *secret-key: \).*$|\1\"${CLIPROXY_MGMT_KEY}\"|" "$CONFIG"

echo "[cliproxy-init] config.yaml đã sẵn sàng."
