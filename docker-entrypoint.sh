#!/bin/sh
# Entrypoint của container `api`.
#
# 1. Chờ Postgres thật sự nhận kết nối (compose healthcheck đã chờ `pg_isready`,
#    nhưng `pg_isready` xanh trước khi Postgres sẵn sàng nhận client là chuyện
#    đã gặp — chờ thêm ở đây cho chắc).
# 2. `alembic upgrade head` — tắt được bằng RUN_MIGRATIONS=0.
# 3. exec lệnh CMD.
set -eu

: "${RUN_MIGRATIONS:=1}"
: "${DB_WAIT_SECONDS:=60}"

log() { printf '[entrypoint] %s\n' "$1" >&2; }

if [ "${RUN_MIGRATIONS}" = "1" ]; then
  log "Chờ database nhận kết nối (tối đa ${DB_WAIT_SECONDS}s)…"
  waited=0
  until python -c "
import os, sys
import psycopg
url = os.environ['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
try:
    psycopg.connect(url, connect_timeout=3).close()
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    waited=$((waited + 2))
    if [ "${waited}" -ge "${DB_WAIT_SECONDS}" ]; then
      log "LỖI: database không phản hồi sau ${DB_WAIT_SECONDS}s. Kiểm tra DATABASE_URL và service db."
      exit 1
    fi
    sleep 2
  done
  log "Database đã sẵn sàng. Chạy alembic upgrade head…"
  alembic upgrade head
  log "Migration xong."
else
  log "RUN_MIGRATIONS=0 → bỏ qua migration."
fi

exec "$@"
