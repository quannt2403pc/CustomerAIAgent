"""Security headers cho mọi response của API (plan.md §7.4, task.md D2.1).

CSP **không** nằm ở đây: nó thuộc nginx của service `web`, nơi phục vụ HTML.
API chỉ trả JSON, và một CSP đặt sai chỗ sẽ gây cảm giác an toàn sai lệch.

`Cache-Control: no-store` là có chủ đích: response của API chứa dữ liệu khách và
trạng thái credential. Để proxy/trình duyệt cache lại là mở một đường rò.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    # Không cần tính năng nào trong số này; tắt hết là mặc định an toàn.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            # `setdefault`: router nào cố ý đặt header khác (vd
            # `Content-Disposition` + cache riêng cho output.json) được quyền thắng.
            response.headers.setdefault(name, value)
        return response
