"""Fixture dùng chung.

Test chạm DB cần Postgres thật (lược đồ dùng JSONB/ARRAY/UUID — SQLite không
kham được). Không có DB → `skip`, không `fail`: `pytest -q` phải xanh trên máy
chưa dựng Docker, còn CI/máy dev thì vẫn chạy đủ.

Bật bằng `TEST_DATABASE_URL`, hoặc mặc định dùng db của `docker compose`
(127.0.0.1:5432, mật khẩu đọc từ `.env`).
"""

from __future__ import annotations

import base64
import os
import pathlib
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import crypto
from app.core.config import get_settings
from app.core.eventloop import ensure_compatible_event_loop_policy
from app.llm.catalog import get_catalog

# Phải gọi ở import-time: pytest-asyncio tạo loop qua policy hiện hành (I-04).
ensure_compatible_event_loop_policy()

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Khoá Fernet dùng riêng cho test. **Sinh** từ một chuỗi đánh dấu thay vì nhúng
# base64 sẵn: một blob base64 trong source trông y như khoá thật với cả người
# đọc lẫn gitleaks, còn dòng này thì tự nói ra nó là giả.
TEST_FERNET_KEY = base64.urlsafe_b64encode(b"test-only-not-a-secret-32-bytes!").decode()


def _test_database_url() -> str | None:
    if explicit := os.environ.get("TEST_DATABASE_URL"):
        return explicit

    # Lấy mật khẩu từ .env của repo (file này không được commit).
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return None
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    password = values.get("POSTGRES_PASSWORD", "").strip()
    if not password or password == "change-me":
        return None
    user = values.get("POSTGRES_USER", "appuser").strip()
    name = values.get("POSTGRES_DB", "customeraiagent").strip()
    return f"postgresql+psycopg://{user}:{password}@127.0.0.1:5432/{name}"


@pytest.fixture(autouse=True)
def _reset_process_wide_caches():
    """Mỗi test nhìn thấy trạng thái của chính nó.

    `ModelCatalog` dùng chung cả tiến trình và khoá cache theo `provider`. Trong
    production đó là ý muốn (TTL 10 phút), nhưng giữa các test nó làm một test
    thấy danh mục của test trước — đã khiến một model khai `supports_vision=False`
    bị đọc thành `True` từ cache cũ.
    """
    get_settings.cache_clear()
    crypto.reset_cache()
    get_catalog().invalidate()
    yield
    get_settings.cache_clear()
    crypto.reset_cache()
    get_catalog().invalidate()


async def _reset_config_tables(session: AsyncSession) -> None:
    """Mỗi test chạm DB bắt đầu từ **máy mới cài**: chưa chọn cổng, chưa có key.

    Vì sao cần: `llm_settings` chỉ có **một hàng** dùng chung (plan.md §12.1), và
    DB dev giữ hàng đó sau khi người vận hành cấu hình thật qua UI/API. Test viết
    theo giả định "cài mới → `provider == ''`" vì vậy đỏ lên trên máy *đã dùng
    thật* mà xanh trên máy sạch — kiểu lỗi tệ nhất của bộ test: nó phụ thuộc máy
    chạy, không phụ thuộc code.

    Xoá trong transaction của test nên dữ liệu thật trở lại nguyên vẹn sau rollback.
    Cố ý **không** xoá `profiles`: test nào đếm profile thì tự dọn, còn xoá hộ ở
    đây sẽ che mất việc chúng đang đếm trên phạm vi quá rộng.
    """
    from sqlalchemy import delete

    from app.models import LlmCredential, LlmSettings

    await session.execute(delete(LlmCredential))
    await session.execute(delete(LlmSettings))
    await session.flush()


@pytest.fixture
def fernet_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENCRYPTION_KEY", TEST_FERNET_KEY)
    get_settings.cache_clear()
    crypto.reset_cache()


@pytest_asyncio.fixture
async def db_session(monkeypatch) -> AsyncIterator[AsyncSession]:
    """Session có transaction **rollback cuối test** → không để lại rác trong DB."""
    url = _test_database_url()
    if url is None:
        pytest.skip("Chưa có Postgres cho test (đặt TEST_DATABASE_URL hoặc `docker compose up -d`)")

    monkeypatch.setenv("APP_ENCRYPTION_KEY", TEST_FERNET_KEY)
    get_settings.cache_clear()
    crypto.reset_cache()

    engine = create_async_engine(url, poolclass=None)
    try:
        conn = await engine.connect()
    except Exception as exc:  # pragma: no cover — phụ thuộc môi trường
        await engine.dispose()
        pytest.skip(f"Không kết nối được Postgres cho test: {type(exc).__name__}")

    trans = await conn.begin()
    maker = async_sessionmaker(bind=conn, expire_on_commit=False)
    session = maker()
    try:
        await _reset_config_tables(session)
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()
