"""D1.10 — cache danh mục + phân giải cổng từ DB.

Có một test đặc biệt ở cuối: grep toàn bộ `app/` để khẳng định **không tên model
nào bị hardcode** (luật L6).
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.core.errors import GatewayModelInvalid, GatewayNoCredential, GatewayNotConfigured
from app.llm.base import ModelInfo
from app.llm.catalog import ModelCatalog
from app.llm.resolver import get_active_config, resolve_gateway, set_model, set_provider
from app.services import credentials

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


class FakeGateway:
    """Gateway giả — đếm số lần danh mục bị gọi lại."""

    def __init__(self, provider: str, models: list[ModelInfo]):
        self.provider = provider
        self._models = models
        self.calls = 0

    async def list_models(self) -> list[ModelInfo]:
        self.calls += 1
        return list(self._models)

    def set_models(self, models: list[ModelInfo]) -> None:
        self._models = models


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway(
        "antigravity",
        [
            ModelInfo(id="co-vision", supports_vision=True),
            ModelInfo(id="khong-vision", supports_vision=False),
            ModelInfo(id="chua-biet", supports_vision=None),
        ],
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
async def test_second_call_hits_cache(gateway) -> None:
    catalog = ModelCatalog(clock=FakeClock())

    await catalog.list_models(gateway)
    await catalog.list_models(gateway)

    assert gateway.calls == 1


async def test_cache_expires_after_ttl(gateway) -> None:
    clock = FakeClock()
    catalog = ModelCatalog(ttl_seconds=600, clock=clock)

    await catalog.list_models(gateway)
    clock.advance(599)
    await catalog.list_models(gateway)
    assert gateway.calls == 1

    clock.advance(2)
    await catalog.list_models(gateway)
    assert gateway.calls == 2


async def test_refresh_forces_a_new_fetch(gateway) -> None:
    catalog = ModelCatalog(clock=FakeClock())

    await catalog.list_models(gateway)
    await catalog.list_models(gateway, refresh=True)

    assert gateway.calls == 2


async def test_invalidate_drops_the_entry(gateway) -> None:
    catalog = ModelCatalog(clock=FakeClock())

    await catalog.list_models(gateway)
    catalog.invalidate("antigravity")
    await catalog.list_models(gateway)

    assert gateway.calls == 2


async def test_cache_is_per_provider(gateway) -> None:
    other = FakeGateway("google_api_key", [ModelInfo(id="khac")])
    catalog = ModelCatalog(clock=FakeClock())

    await catalog.list_models(gateway)
    models = await catalog.list_models(other)

    assert [m.id for m in models] == ["khac"]
    assert other.calls == 1


# ---------------------------------------------------------------------------
# find / supports_vision
# ---------------------------------------------------------------------------
async def test_find_returns_model(gateway) -> None:
    catalog = ModelCatalog(clock=FakeClock())
    assert (await catalog.find(gateway, "co-vision")).id == "co-vision"


async def test_find_missing_model_names_model_and_provider(gateway) -> None:
    catalog = ModelCatalog(clock=FakeClock())

    with pytest.raises(GatewayModelInvalid) as exc:
        await catalog.find(gateway, "gemini-khong-ton-tai")

    message = str(exc.value)
    assert "gemini-khong-ton-tai" in message
    assert "antigravity" in message


async def test_find_refetches_before_giving_up(gateway) -> None:
    """Cache cũ không được biến một model có thật thành "không tồn tại"."""
    catalog = ModelCatalog(clock=FakeClock())
    await catalog.list_models(gateway)

    gateway.set_models([*(await gateway.list_models()), ModelInfo(id="model-vua-them")])
    gateway.calls = 0

    assert (await catalog.find(gateway, "model-vua-them")).id == "model-vua-them"


@pytest.mark.parametrize(
    "model_id, expected",
    [("co-vision", True), ("khong-vision", False), ("chua-biet", None)],
)
async def test_supports_vision_passes_through_unknown(gateway, model_id, expected) -> None:
    """`None` = chưa biết là một câu trả lời hợp lệ, không được quy về False."""
    catalog = ModelCatalog(clock=FakeClock())
    assert await catalog.supports_vision(gateway, model_id) is expected


# ---------------------------------------------------------------------------
# Resolver — đọc DB mỗi lần, không cache
# ---------------------------------------------------------------------------
async def test_fresh_install_has_no_provider_chosen(db_session) -> None:
    config = await get_active_config(db_session)
    assert config.provider == ""
    assert config.is_configured is False


async def test_resolve_without_provider_raises_not_configured(db_session) -> None:
    with pytest.raises(GatewayNotConfigured):
        await resolve_gateway(db_session)


async def test_switching_provider_takes_effect_without_restart(db_session) -> None:
    await set_provider(db_session, "antigravity")
    first = await resolve_gateway(db_session)
    assert first.provider == "antigravity"

    await credentials.save_secret(
        db_session, credentials.KIND_GOOGLE_API_KEY, "AIza-test-only-not-a-secret"
    )
    await set_provider(db_session, "google_api_key")
    second = await resolve_gateway(db_session)
    assert second.provider == "google_api_key"


async def test_switching_provider_clears_the_chosen_model(db_session) -> None:
    """Danh mục hai cổng khác nhau → giữ model cũ tạo cấu hình trông hợp lệ mà gọi là lỗi."""
    await set_provider(db_session, "antigravity")
    await set_model(db_session, "gemini-3-flash")
    assert (await get_active_config(db_session)).model == "gemini-3-flash"

    await set_provider(db_session, "google_api_key")
    assert (await get_active_config(db_session)).model == ""


async def test_same_provider_keeps_the_model(db_session) -> None:
    await set_provider(db_session, "antigravity")
    await set_model(db_session, "gemini-3-flash")
    await set_provider(db_session, "antigravity")
    assert (await get_active_config(db_session)).model == "gemini-3-flash"


async def test_google_provider_without_key_says_what_to_do(db_session, monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    await set_provider(db_session, "google_api_key")

    with pytest.raises(GatewayNoCredential) as exc:
        await resolve_gateway(db_session)
    assert "Cài đặt" in str(exc.value)


async def test_cli_provider_override_wins_over_db(db_session) -> None:
    await set_provider(db_session, "antigravity")
    await credentials.save_secret(
        db_session, credentials.KIND_GOOGLE_API_KEY, "AIza-test-only-not-a-secret"
    )

    gateway = await resolve_gateway(db_session, provider="google_api_key")
    assert gateway.provider == "google_api_key"


async def test_unknown_provider_override_is_rejected(db_session) -> None:
    with pytest.raises(GatewayNotConfigured, match="openai"):
        await resolve_gateway(db_session, provider="openai")


# ---------------------------------------------------------------------------
# Luật L6 — không hardcode danh mục model
# ---------------------------------------------------------------------------
def test_no_model_name_is_hardcoded_in_app_source() -> None:
    """Luật L6, canh gác bằng grep.

    `gemini-flash-latest` tồn tại trong cổng API-key nhưng **không** tồn tại
    trong channel `antigravity` — hardcode là sai lúc nào không biết (I-06 đo
    thật: danh mục antigravity gồm `gemini-3-flash`, `gemini-pro-agent`, …).
    """
    pattern = re.compile(r"\b(gemini|claude|gpt|text-embedding)[-.][a-z0-9.\-]+", re.IGNORECASE)
    offenders: list[str] = []

    for path in sorted(APP_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            # Comment/docstring được phép nêu tên model để giải thích bẫy.
            if stripped.startswith("#") or stripped.startswith(('"""', "'''", "|", "*")):
                continue
            if pattern.search(line):
                offenders.append(f"{path.relative_to(APP_DIR.parent)}:{lineno}: {stripped}")

    assert not offenders, "Tên model bị hardcode trong source (luật L6):\n" + "\n".join(offenders)
