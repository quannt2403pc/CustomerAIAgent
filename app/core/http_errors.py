"""Exception handler chuẩn hoá cho FastAPI (plan.md §7.3.6, task.md D2.1).

Hợp đồng **duy nhất** của mọi response lỗi: `{"code": "...", "message": "..."}`.
Không stack trace, không payload thô, không tên field nội bộ của Pydantic.

Lý do nghiêm khắc: UI hiển thị `message` cho người vận hành và `code` để đối
chiếu log. Nếu response mang theo chi tiết kỹ thuật thì FE buộc phải đọc/đổ nó
ra đâu đó — và cái "đâu đó" trong thực tế luôn là `console.log` (phá luật L5).
Chi tiết đi vào log server, nơi `RedactingFormatter` đã che secret.

Riêng lỗi validate đầu vào cần cẩn thận gấp đôi: `RequestValidationError` của
Pydantic mang **cả giá trị người dùng gửi lên** trong `ctx`/`input`. Với
`PUT /api/llm/api-key` thì giá trị đó chính là Google API key. Vì vậy ở đây chỉ
lấy *vị trí* field, tuyệt đối không lấy `input`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)

GENERIC_500 = {
    "code": "E-APP-500",
    "message": "Hệ thống gặp lỗi không lường trước. Xem log server để biết chi tiết.",
}


def _json(status: int, payload: dict[str, str]) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload)


def _field_path(location: tuple[object, ...]) -> str:
    """`('body', 'facebook_url')` → `facebook_url`. Chỉ tên field, không giá trị."""
    parts = [str(part) for part in location if part not in ("body", "query", "path")]
    return ".".join(parts) or "(thân yêu cầu)"


class ErrorNormalizingMiddleware(BaseHTTPMiddleware):
    """Bắt lỗi không lường trước **trong tầng middleware**, không chỉ ở handler.

    Vì sao cần, dù đã có `@app.exception_handler(Exception)`: trong Starlette,
    handler đó do `ServerErrorMiddleware` gọi, mà middleware đó nằm **ngoài cùng**
    — ngoài cả middleware của ta. Hệ quả đo được: response 500 sinh từ handler
    **không đi qua** `SecurityHeadersMiddleware`, nên trang lỗi ra đời thiếu
    `X-Frame-Options`/`nosniff` (tức là nhúng iframe được).

    Đặt việc chuẩn hoá ở đây thì response 500 là một `Response` bình thường, đi
    ngược ra qua đủ các lớp middleware như mọi response khác. Handler
    `Exception` vẫn giữ làm lưới cuối cho lỗi xảy ra *ngoài* phạm vi này.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except Exception:
            log.error(
                "Lỗi không lường trước ở %s %s",
                request.method,
                request.url.path,
                exc_info=True,
            )
            return _json(500, dict(GENERIC_500))


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        """Lỗi có chủ đích — `message` đã là câu tiếng Việt hành động được."""
        # `detail` chỉ vào log, không bao giờ vào response.
        log.warning(
            "%s %s → %s %s%s",
            request.method,
            request.url.path,
            exc.http_status,
            exc.code,
            f" ({exc.detail})" if exc.detail else "",
        )
        return _json(exc.http_status, exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 của Pydantic → 400 với **chỉ tên field**, không echo giá trị."""
        fields = sorted({_field_path(err.get("loc", ())) for err in exc.errors()})
        log.warning(
            "%s %s → 400 dữ liệu vào không hợp lệ: %s",
            request.method,
            request.url.path,
            ", ".join(fields),
        )
        return _json(
            400,
            {
                "code": "E-APP-400",
                "message": "Dữ liệu gửi lên không hợp lệ ở: " + ", ".join(fields) + ".",
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """404/405… `detail` của Starlette là chuỗi tiếng Anh ngắn, không phải payload."""
        message = exc.detail if isinstance(exc.detail, str) else "Yêu cầu không được chấp nhận."
        if exc.status_code == 404:
            message = "Không tìm thấy đường dẫn này."
        elif exc.status_code == 405:
            message = "Phương thức HTTP không được hỗ trợ ở đường dẫn này."
        return _json(exc.status_code, {"code": f"E-APP-{exc.status_code}", "message": message})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Lưới cuối. `exc_info=True` để traceback vào **log**, không vào response."""
        log.error(
            "Lỗi không lường trước ở %s %s",
            request.method,
            request.url.path,
            exc_info=True,
        )
        return _json(500, dict(GENERIC_500))
