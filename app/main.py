"""App factory FastAPI.

Bản D1.2 chỉ có `/health` — vừa đủ để nghiệm thu Docker. D2.1 sẽ bổ sung
exception handler chuẩn hoá, security headers, CORS và các router còn lại.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db import engine as db_engine
from app.routers import health

log = get_logger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = get_settings()
    log.info("API khởi động — env=%s, dry_run=%s", settings.app_env, settings.dry_run)
    yield
    await db_engine.dispose_engine()
    log.info("API đã dừng")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(
        title="Cỗ máy AI Profiler & Rapport",
        version="0.1.0",
        lifespan=_lifespan,
        # plan.md §7.2: Swagger tắt mặc định, chỉ bật khi DOCS_ENABLED=true.
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.include_router(health.router)
    return app


app = create_app()
