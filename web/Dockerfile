# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — build bundle
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Copy manifest trước để lớp `npm ci` được cache lại khi chỉ source đổi.
COPY package.json package-lock.json ./
# `npm ci` chứ không `npm install`: cài đúng theo lock, không âm thầm nâng
# phiên bản giữa máy dev và máy build.
RUN npm ci

COPY . .

# Build cũng chạy `tsc -b`, nên lỗi kiểu sẽ **chặn image**, không trôi ra production.
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — phục vụ tĩnh
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

# Bỏ cấu hình mặc định để nó không tranh `server_name _`.
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# `wget` có sẵn trong nginx:alpine; healthcheck đọc chính trang index.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD wget -qO- http://localhost/ >/dev/null || exit 1
