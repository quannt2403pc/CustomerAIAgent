# syntax=docker/dockerfile:1

# ============================================================================
# Multi-stage. Hai image đích:
#   --target runtime     (mặc định) — nhẹ, KHÔNG có Playwright
#   --target playwright  — thêm Chromium + thư viện hệ thống, chỉ khi cần L3
# Tách ra vì Playwright kéo theo ~500MB thư viện GUI (plan.md R7).
# ============================================================================

# ---------- 1. deps: biên dịch wheel một lần, tái dùng cho mọi stage ----------
FROM python:3.12-slim AS deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /wheels
COPY requirements.txt .
RUN python -m pip wheel --wheel-dir /wheels -r requirements.txt


# ---------- 2. runtime: image mặc định ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Ho_Chi_Minh

# curl cho healthcheck của compose; tzdata để APScheduler biết Asia/Ho_Chi_Minh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=deps /wheels /wheels
COPY requirements.txt .
RUN python -m pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY alembic.ini pyproject.toml main.py run.py ./
COPY samples ./samples
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Chạy không phải root. `var/` cần ghi được (screenshot, ảnh upload).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var/screenshots /app/var/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------- 3. playwright: chỉ dùng khi PLAYWRIGHT_ENABLED=true ----------
#
# Base KHÁC hẳn stage `runtime` một cách có chủ đích. Thử cách gọn hơn —
# `FROM runtime` rồi `playwright install --with-deps chromium` — thì **vỡ**:
# Playwright không nhận ra Debian của `python:3.12-slim` nên fallback sang tên
# gói Ubuntu 20.04 và apt chết với `Package 'ttf-unifont' has no installation
# candidate` (task.md I-26). Image chính thức của Playwright đã có Chromium +
# đủ thư viện hệ thống, nên dùng nó là đường ít vỡ nhất.
#
# Dùng tag **noble** (Ubuntu 24.04, Python 3.12.3) chứ không phải `jammy`:
# jammy ship Python **3.10**, trong khi `pyproject.toml` khai
# `requires-python = ">=3.12"`. Hai phiên bản Python trong cùng một repo nghĩa là
# một tính năng 3.12 thêm sau này sẽ vỡ **chỉ** ở image Playwright, đúng chỗ ít
# ai chạy test nhất (task.md I-28).
#
# Stage này KHÔNG ảnh hưởng image mặc định: `runtime` vẫn là target mặc định.
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble AS playwright

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Ho_Chi_Minh

# `DEBIAN_FRONTEND=noninteractive` + đặt sẵn `/etc/timezone` là BẮT BUỘC ở đây.
# Base jammy (Ubuntu) cấu hình `tzdata` qua debconf và **hỏi tương tác**
# "Geographic area:", làm build treo vô hạn. Base Debian của stage `runtime`
# không hỏi, nên lỗi này chỉ lộ ra ở stage này (task.md I-27).
RUN ln -snf /usr/share/zoneinfo/Asia/Ho_Chi_Minh /etc/localtime \
    && echo "Asia/Ho_Chi_Minh" > /etc/timezone \
    && DEBIAN_FRONTEND=noninteractive apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-playwright.txt ./
RUN python -m pip install -r requirements-playwright.txt

COPY alembic.ini pyproject.toml main.py run.py ./
COPY alembic ./alembic
COPY app ./app
COPY samples ./samples
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Chromium của image gốc nằm ở /ms-playwright, đã đọc được bởi mọi user.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var/screenshots /app/var/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
