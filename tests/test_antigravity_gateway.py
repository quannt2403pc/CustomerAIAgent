"""D1.7 — cổng A: gọi model, danh mục model, health.

Dữ liệu fixture lấy từ phản hồi **thật** của `eceasy/cli-proxy-api:latest`
v8.0.16 đo ngày 2026-10-06 (task.md I-06), đã rút gọn.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.errors import (
    GatewayAuthError,
    GatewayBadResponse,
    GatewayDisabled,
    GatewayUnavailable,
)
from app.llm.antigravity import AntigravityGateway
from app.llm.cliproxy_admin import AuthFile, CliProxyAdmin
from app.llm.gemini_wire import extract_text

BASE = "http://cliproxy.test:8317"
MGMT = f"{BASE}/v0/management"

MODEL_DEFINITIONS = {
    "channel": "antigravity",
    "models": [
        {
            "id": "gemini-3-flash",
            "display_name": "Gemini 3 Flash",
            "context_length": 1048576,
            "max_completion_tokens": 65536,
            "supportedInputModalities": ["text", "image", "audio", "video"],
        },
        {
            "id": "gpt-oss-120b-medium",
            "display_name": "GPT-OSS 120B (Medium)",
            "context_length": 114000,
            "max_completion_tokens": 32768,
            "supportedInputModalities": ["text"],
        },
        {
            "id": "mo-hinh-khong-ro-modality",
            "display_name": "Không khai báo modality",
        },
    ],
}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        cliproxy_base_url=BASE,
        cliproxy_mgmt_key="test-only-not-a-secret",
        cliproxy_auth_provider="antigravity",
    )


@pytest.fixture
def no_sleep():
    async def _sleep(_delay: float) -> None:
        return None

    return _sleep


# ---------------------------------------------------------------------------
# Danh mục model — luật L6 + I-06
# ---------------------------------------------------------------------------
@respx.mock
async def test_list_models_comes_from_live_catalog(settings) -> None:
    respx.get(f"{MGMT}/model-definitions/antigravity").mock(
        return_value=httpx.Response(200, json=MODEL_DEFINITIONS)
    )

    async with httpx.AsyncClient() as client:
        gateway = AntigravityGateway(settings, client)
        models = await gateway.list_models()

    assert [m.id for m in models] == [
        "gemini-3-flash",
        "gpt-oss-120b-medium",
        "mo-hinh-khong-ro-modality",
    ]


@respx.mock
async def test_vision_flag_is_read_not_guessed(settings) -> None:
    """`supportedInputModalities` là dữ liệu thật; thiếu nó thì trả None, không đoán."""
    respx.get(f"{MGMT}/model-definitions/antigravity").mock(
        return_value=httpx.Response(200, json=MODEL_DEFINITIONS)
    )

    async with httpx.AsyncClient() as client:
        models = {m.id: m for m in await AntigravityGateway(settings, client).list_models()}

    assert models["gemini-3-flash"].supports_vision is True
    assert models["gpt-oss-120b-medium"].supports_vision is False
    assert models["mo-hinh-khong-ro-modality"].supports_vision is None


@respx.mock
async def test_model_definitions_missing_key_is_reported(settings) -> None:
    respx.get(f"{MGMT}/model-definitions/antigravity").mock(
        return_value=httpx.Response(200, json={"channel": "antigravity"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayBadResponse):
            await AntigravityGateway(settings, client).list_models()


@respx.mock
async def test_management_key_is_sent_as_bearer(settings) -> None:
    route = respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )

    async with httpx.AsyncClient() as client:
        await CliProxyAdmin(settings, client).auth_files()

    assert route.calls[0].request.headers["authorization"] == "Bearer test-only-not-a-secret"


# ---------------------------------------------------------------------------
# Gọi model
# ---------------------------------------------------------------------------
@respx.mock
async def test_generate_content_hits_v1beta_without_auth_header(settings) -> None:
    """`api-keys: []` → đường gọi model không gửi header xác thực."""
    route = respx.post(f"{BASE}/v1beta/models/gemini-3-flash:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "chào chị"}]}}]}
        )
    )

    async with httpx.AsyncClient() as client:
        raw = await AntigravityGateway(settings, client).generate_content(
            {"contents": []}, model="gemini-3-flash"
        )

    assert extract_text(raw) == "chào chị"
    assert "authorization" not in route.calls[0].request.headers


@respx.mock
async def test_generate_content_non_json_body_is_unavailable_not_crash(settings) -> None:
    respx.post(f"{BASE}/v1beta/models/m:generateContent").mock(
        return_value=httpx.Response(200, text="<html>502 from a proxy</html>")
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayUnavailable) as exc:
            await AntigravityGateway(settings, client).generate_content({}, model="m")
    assert "phi-JSON" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# Health — phân biệt "cổng chết" với "chưa đăng nhập"
# ---------------------------------------------------------------------------
@respx.mock
async def test_health_connected_reports_account_email(settings) -> None:
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"files": ["antigravity-nguoidung@gmail.com.json"]})
    )

    async with httpx.AsyncClient() as client:
        health = await AntigravityGateway(settings, client).health()

    assert health.reachable is True
    assert health.connected is True
    assert health.account == "nguoidung@gmail.com"


@respx.mock
async def test_health_reachable_but_not_connected(settings) -> None:
    """Cổng sống, chưa đăng nhập → phải nói "bấm Đăng nhập", không phải "thử lại sau"."""
    respx.get(f"{MGMT}/auth-files").mock(return_value=httpx.Response(200, json={"files": []}))

    async with httpx.AsyncClient() as client:
        health = await AntigravityGateway(settings, client).health()

    assert health.reachable is True
    assert health.connected is False
    assert "Đăng nhập" in health.detail or "kết nối" in health.detail


@respx.mock
async def test_health_unreachable_when_cliproxy_is_down(settings, no_sleep, monkeypatch) -> None:
    monkeypatch.setattr("app.llm.gemini_wire.asyncio.sleep", no_sleep)
    respx.get(f"{MGMT}/auth-files").mock(side_effect=httpx.ConnectError("refused"))

    async with httpx.AsyncClient() as client:
        health = await AntigravityGateway(settings, client).health()

    assert health.reachable is False
    assert health.connected is False


@respx.mock
async def test_wrong_management_key_is_auth_error_with_one_request(settings) -> None:
    """Bẫy B3: 5 lần sai key → ban IP 30 phút. Đúng 1 request, không retry."""
    route = respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(401, json={"error": "invalid management key"})
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayAuthError):
            await CliProxyAdmin(settings, client).auth_files()

    assert route.call_count == 1


@respx.mock
async def test_html_body_on_management_route_means_disabled(settings) -> None:
    """Bẫy B4: `secret-key` rỗng → route quản trị trả 404/HTML, không phải 401."""
    respx.get(f"{MGMT}/auth-files").mock(return_value=httpx.Response(200, text="<html>nope"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayDisabled):
            await CliProxyAdmin(settings, client).auth_files()


# ---------------------------------------------------------------------------
# Bóc tên tài khoản từ tên file
# ---------------------------------------------------------------------------
# Hình dạng **thật** một phần tử `files[]` sau khi OAuth thành công, sao từ
# `GET /v0/management/auth-files` ngày 2026-10-06 (email đã đổi).
REAL_AUTH_FILE = {
    "account": "nguoidung@gmail.com",
    "account_type": "oauth",
    "auth_index": "0f691ad2ce182b60",
    "disabled": False,
    "email": "nguoidung@gmail.com",
    "failed": 0,
    "id": "antigravity-nguoidung@gmail.com.json",
    "label": "nguoidung@gmail.com",
    "name": "antigravity-nguoidung@gmail.com.json",
    "path": "/root/.cli-proxy-api/antigravity-nguoidung@gmail.com.json",
    "project_id": "aicode-consumers",
    "provider": "antigravity",
    "status": "active",
    "type": "antigravity",
    "unavailable": False,
}


@pytest.mark.parametrize(
    "raw, expected_account",
    [
        ("antigravity-ai@gmail.com.json", "ai@gmail.com"),
        ({"name": "antigravity-b@x.vn.json"}, "b@x.vn"),
        ({"name": "f.json", "email": "c@y.vn"}, "c@y.vn"),
        ("khong-co-email.json", None),
        (REAL_AUTH_FILE, "nguoidung@gmail.com"),
    ],
)
def test_auth_file_parsing(raw, expected_account) -> None:
    assert AuthFile.from_wire(raw).account == expected_account


@respx.mock
async def test_health_parses_the_real_auth_files_shape(settings) -> None:
    """Phần tử `files[]` thật là object nhiều field, không phải chuỗi tên file."""
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(
            200, json={"files": [REAL_AUTH_FILE], "observed_at": "2026-10-06T04:07:15Z"}
        )
    )

    async with httpx.AsyncClient() as client:
        health = await AntigravityGateway(settings, client).health()

    assert health.connected is True
    assert health.account == "nguoidung@gmail.com"


def test_auth_file_rejects_unexpected_shape() -> None:
    with pytest.raises(GatewayBadResponse):
        AuthFile.from_wire(42)
