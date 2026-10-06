"""D1.9 — cổng B: Google API Key trực tiếp.

Trọng tâm: key **không bao giờ** lọt vào message lỗi/log, và dùng **cùng**
`gemini_wire` với cổng A (không nhân bản code dựng payload).
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.errors import GatewayAuthError, GatewayNoCredential, GatewayRateLimited
from app.core.logging import setup_logging
from app.llm import gemini_wire as wire
from app.llm.google_api_key import GoogleApiKeyGateway

BASE = "https://generativelanguage.test"
KEY = "AIzaSy-test-only-not-a-secret-7777"

MODELS_PAGE = {
    "models": [
        {
            "name": "models/gemini-3-flash",
            "displayName": "Gemini 3 Flash",
            "inputTokenLimit": 1048576,
            "outputTokenLimit": 65536,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/text-embedding-004",
            "displayName": "Text Embedding 004",
            "supportedGenerationMethods": ["embedContent"],
        },
    ]
}


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, google_api_base_url=BASE)


@pytest.fixture
def no_sleep(monkeypatch):
    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("app.llm.gemini_wire.asyncio.sleep", _sleep)


# ---------------------------------------------------------------------------
# Khởi tạo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_key", ["", "   "])
def test_empty_key_is_refused_up_front(bad_key: str, settings) -> None:
    with pytest.raises(GatewayNoCredential):
        GoogleApiKeyGateway(bad_key, settings)


# ---------------------------------------------------------------------------
# Danh mục model — lọc generateContent, phân trang
# ---------------------------------------------------------------------------
@respx.mock
async def test_list_models_filters_to_generate_content(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_PAGE))

    async with httpx.AsyncClient() as client:
        models = await GoogleApiKeyGateway(KEY, settings, client).list_models()

    # Model embedding có trong danh mục nhưng chọn vào thì pipeline chết.
    assert [m.id for m in models] == ["gemini-3-flash"]
    assert models[0].input_token_limit == 1048576


@respx.mock
async def test_list_models_follows_pagination(settings) -> None:
    """Bỏ qua `nextPageToken` sẽ cắt mất model ở trang sau."""
    respx.get(f"{BASE}/v1beta/models").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/a",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "trang-2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/b",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                },
            ),
        ]
    )

    async with httpx.AsyncClient() as client:
        models = await GoogleApiKeyGateway(KEY, settings, client).list_models()

    assert [m.id for m in models] == ["a", "b"]


@respx.mock
async def test_model_without_methods_field_is_kept_not_guessed_away(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "models/la-lung"}]})
    )

    async with httpx.AsyncClient() as client:
        models = await GoogleApiKeyGateway(KEY, settings, client).list_models()

    assert [m.id for m in models] == ["la-lung"]


@respx.mock
async def test_vision_capability_is_unknown_not_invented(settings) -> None:
    """`models.list` của Google không có cờ vision → None, UI tự cảnh báo (I-06)."""
    respx.get(f"{BASE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_PAGE))

    async with httpx.AsyncClient() as client:
        models = await GoogleApiKeyGateway(KEY, settings, client).list_models()

    assert models[0].supports_vision is None


# ---------------------------------------------------------------------------
# Key đi trong header, và không bao giờ lọt ra ngoài
# ---------------------------------------------------------------------------
@respx.mock
async def test_key_travels_in_header_not_query_string(settings) -> None:
    """`?key=` lọt vào access log của mọi proxy trên đường đi."""
    route = respx.get(f"{BASE}/v1beta/models").mock(
        return_value=httpx.Response(200, json=MODELS_PAGE)
    )

    async with httpx.AsyncClient() as client:
        await GoogleApiKeyGateway(KEY, settings, client).list_models()

    request = route.calls[0].request
    assert request.headers["x-goog-api-key"] == KEY
    assert "key" not in request.url.params


@respx.mock
async def test_wrong_key_error_never_echoes_the_key(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "API key not valid. Please pass a valid API key."}}
        )
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayAuthError) as exc:
            await GoogleApiKeyGateway(KEY, settings, client).validate_key()

    # Google báo key sai bằng **400**, không phải 401 — phải nhận ra để câu
    # thông báo chỉ đúng việc cần làm ("nhập lại key"), không phải "kiểm tra model".
    rendered = f"{exc.value} {exc.value.detail} {exc.value.to_payload()}"
    assert KEY not in rendered


@respx.mock
async def test_403_is_auth_error_in_vietnamese(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(
        return_value=httpx.Response(403, json={"error": {"message": "forbidden"}})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayAuthError) as exc:
            await GoogleApiKeyGateway(KEY, settings, client).validate_key()

    assert "key sai" in exc.value.message or "hết hạn" in exc.value.message
    assert KEY not in exc.value.message


@respx.mock
async def test_key_absent_from_logs_at_debug_level(settings, capsys, no_sleep) -> None:
    setup_logging("DEBUG", force=True)
    logging.getLogger().setLevel("DEBUG")
    respx.get(f"{BASE}/v1beta/models").mock(return_value=httpx.Response(429, text="quota"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayRateLimited):
            await GoogleApiKeyGateway(KEY, settings, client).list_models()

    assert KEY not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Gọi model — dùng CHUNG gemini_wire với cổng A
# ---------------------------------------------------------------------------
@respx.mock
async def test_generate_content_uses_shared_payload_builder(settings) -> None:
    route = respx.post(f"{BASE}/v1beta/models/gemini-3-flash:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "xin chào"}]}}],
                "usageMetadata": {"promptTokenCount": 7, "totalTokenCount": 19},
            },
        )
    )

    payload = wire.build_payload([wire.text_part("chào")], temperature=0.3, max_output_tokens=64)

    async with httpx.AsyncClient() as client:
        raw = await GoogleApiKeyGateway(KEY, settings, client).generate_content(
            payload, model="gemini-3-flash"
        )

    assert wire.extract_text(raw) == "xin chào"
    assert wire.extract_usage(raw) == {"prompt_tokens": 7, "total_tokens": 19}

    sent = json.loads(route.calls[0].request.content)
    assert sent["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 64}
    assert sent["contents"][0]["parts"] == [{"text": "chào"}]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@respx.mock
async def test_health_connected_hides_key_behind_hint(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_PAGE))

    async with httpx.AsyncClient() as client:
        health = await GoogleApiKeyGateway(KEY, settings, client).health()

    assert (health.reachable, health.connected) == (True, True)
    assert health.account == "••••7777"
    assert KEY not in str(health)


@respx.mock
async def test_health_unreachable_on_bad_key(settings) -> None:
    respx.get(f"{BASE}/v1beta/models").mock(return_value=httpx.Response(403, text="forbidden"))

    async with httpx.AsyncClient() as client:
        health = await GoogleApiKeyGateway(KEY, settings, client).health()

    assert (health.reachable, health.connected) == (False, False)
    assert KEY not in str(health)
