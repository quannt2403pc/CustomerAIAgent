"""Engine + session SQLAlchemy async (psycopg3).

Engine được tạo **lười** (lazy): CLI chạy với `--no-db` hoặc đường L4 manual
paste không cần Postgres, nên import module này không được mở kết nối.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _async_url(url: str) -> str:
    """psycopg3 nói được cả sync và async qua cùng driver `postgresql+psycopg`."""
    return url.replace("postgresql://", "postgresql+psycopg://")


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        _async_url(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # echo=False cố định: echo=True sẽ đổ SQL (có thể chứa secret_enc) vào log.
        echo=False,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency của FastAPI — một session cho mỗi request."""
    async with get_sessionmaker()() as session:
        yield session


async def ping() -> bool:
    """`SELECT 1` — dùng cho `/health`. Không raise, chỉ trả True/False."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("Không kết nối được database: %s", type(exc).__name__)
        return False


async def dispose_engine() -> None:
    """Đóng pool lúc shutdown."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
