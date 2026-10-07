"""App factory FastAPI (task.md D2.1).

Ba điều file này cưỡng chế:

1. **Mọi lỗi ra response dạng `{code, message}`** — không stack trace, không
   payload thô (plan.md §7.3.6). Xem `app/core/http_errors.py`.
2. **Security headers trên mọi response** (plan.md §7.4).
3. **`/docs` tắt theo `DOCS_ENABLED`**, mặc định tắt (plan.md §7.2).

CORS dùng whitelist origin thật của service `web`, **không** `["*"]`.
`allow_credentials=False` vì app không dùng cookie để xác thực (một người vận
hành, plan.md §12.1) — bật lên mà không cần là mở rộng bề mặt tấn công không đổi
lấy gì.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.http_errors import ErrorNormalizingMiddleware, install_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import SecurityHeadersMiddleware
from app.db import engine as db_engine
from app.routers import conversations, health, llm, messenger, outbox, profiles
from app.scheduler import runner as scheduler_runner

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = get_settings()
    log.info("API khởi động — env=%s, dry_run=%s", settings.app_env, settings.dry_run)
    # Scheduler không lên được thì `start()` tự ghi lỗi và `/health` nói ra —
    # API vẫn phải phục vụ được trang Cài đặt để người vận hành đi sửa.
    await scheduler_runner.start()
    try:
        yield
    finally:
        await scheduler_runner.shutdown()
        await db_engine.dispose_engine()
        log.info("API đã dừng")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Cỗ máy AI Profiler & Rapport",
        version="1.0.0",
        lifespan=_lifespan,
        # plan.md §7.2: Swagger tắt mặc định, chỉ bật khi DOCS_ENABLED=true.
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Thứ tự quan trọng: `add_middleware` gọi sau nằm **ngoài** hơn. Ta cần
    # `SecurityHeaders` ngoài cùng để nó đóng dấu được cả response lỗi do
    # `ErrorNormalizing` sinh ra.
    app.add_middleware(ErrorNormalizingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    install_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(llm.router)
    app.include_router(profiles.router)
    app.include_router(outbox.router)
    app.include_router(conversations.router)
    app.include_router(messenger.router)
    return app


app = create_app()
