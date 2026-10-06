"""D1.8 — client Management API của CLIProxy.

Mọi phản hồi mock ở đây sao lại **nguyên văn** phản hồi đo thật trên
`eceasy/cli-proxy-api:latest` v8.0.16 ngày 2026-10-06. Ba bẫy được canh gác:

- **B6** `get-auth-status` thiếu `state` → `{"status":"ok"}` dù chưa đăng nhập.
- **B7** lỗi báo bằng **HTTP 200** + `{"status":"error"}`.
- **B10** `DELETE /auth-files` không có chế độ "xoá tất cả".
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.errors import GatewayAuthError, GatewayBadResponse
from app.llm.cliproxy_admin import CliProxyAdmin

BASE = "http://cliproxy.test:8317"
MGMT = f"{BASE}/v0/management"
STATE = "4213cda54b08045cd1773553bf5de992"
GOOGLE_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&redirect_uri="
    "http%3A%2F%2Flocalhost%3A51121%2Foauth-callback&response_type=code&state=" + STATE
)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        cliproxy_base_url=BASE,
        cliproxy_mgmt_key="test-only-not-a-secret",
        cliproxy_auth_provider="antigravity",
    )


@pytest.fixture
async def admin(settings):
    async with httpx.AsyncClient() as client:
        yield CliProxyAdmin(settings, client)


# ---------------------------------------------------------------------------
# start_oauth
# ---------------------------------------------------------------------------
@respx.mock
async def test_start_oauth_returns_url_and_state(admin) -> None:
    route = respx.get(f"{MGMT}/antigravity-auth-url").mock(
        return_value=httpx.Response(200, json={"status": "ok", "url": GOOGLE_URL, "state": STATE})
    )

    session = await admin.start_oauth()

    assert session.state == STATE
    assert session.url.startswith("https://accounts.google.com/")
    # is_webui=1 để CLIProxy không tự mở trình duyệt phía server (trong container
    # không có trình duyệt nào) mà trả URL về cho FE.
    assert route.calls[0].request.url.params["is_webui"] == "1"


@respx.mock
async def test_start_oauth_missing_state_is_reported(admin) -> None:
    respx.get(f"{MGMT}/antigravity-auth-url").mock(
        return_value=httpx.Response(200, json={"status": "ok", "url": GOOGLE_URL})
    )
    with pytest.raises(GatewayBadResponse):
        await admin.start_oauth()


# ---------------------------------------------------------------------------
# oauth_status — bẫy B6 + B7
# ---------------------------------------------------------------------------
async def test_oauth_status_requires_state_trap_b6(admin) -> None:
    """Bẫy B6: thiếu `state`, CLIProxy trả `{"status":"ok"}` dù chưa đăng nhập.

    Client phải chặn ngay thay vì gọi rồi tin lời.
    """
    with pytest.raises(ValueError, match="B6"):
        await admin.oauth_status("")


@respx.mock
async def test_oauth_status_wait_then_ok(admin) -> None:
    respx.get(f"{MGMT}/get-auth-status").mock(
        side_effect=[
            httpx.Response(200, json={"status": "wait"}),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )

    first = await admin.oauth_status(STATE)
    assert (first.status, first.is_final) == ("wait", False)

    second = await admin.oauth_status(STATE)
    assert (second.status, second.is_final) == ("ok", True)


@respx.mock
async def test_oauth_status_error_arrives_as_http_200_trap_b7(admin) -> None:
    """Bẫy B7 — phản hồi đo thật: HTTP 200 + {"status":"error"}.

    Đọc theo status code sẽ tưởng đăng nhập thành công.
    """
    respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(
            200, json={"error": "Failed to exchange token", "status": "error"}
        )
    )

    result = await admin.oauth_status(STATE)

    assert result.status == "error"
    assert result.is_final is True
    assert "exchange" in result.error


@respx.mock
async def test_oauth_status_unknown_status_is_rejected(admin) -> None:
    respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(200, json={"status": "dang-nghi-ngoi"})
    )
    with pytest.raises(GatewayBadResponse):
        await admin.oauth_status(STATE)


# ---------------------------------------------------------------------------
# submit_callback — đường dự phòng dán URL
# ---------------------------------------------------------------------------
@respx.mock
async def test_submit_callback_extracts_code_from_pasted_url(admin) -> None:
    """CLIProxy nhận `{state, code}`, không nhận cả URL (I-08).

    Ta tự bóc `code` để UI chỉ cần một ô dán, không bắt người dùng tìm tham số.
    """
    route = respx.post(f"{MGMT}/oauth-callback").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    await admin.submit_callback(
        STATE, f"http://localhost:51121/oauth-callback?state={STATE}&code=4%2F0AX4abc&scope=email"
    )

    import json

    sent = json.loads(route.calls[0].request.content)
    assert sent == {"state": STATE, "code": "4/0AX4abc"}


@respx.mock
async def test_submit_callback_rejects_url_from_another_session(admin) -> None:
    await _assert_rejects(admin, "http://localhost:51121/oauth-callback?state=khac&code=abc")


@respx.mock
async def test_submit_callback_without_code_says_what_to_do(admin) -> None:
    with pytest.raises(GatewayBadResponse) as exc:
        await admin.submit_callback(STATE, "http://localhost:51121/oauth-callback?state=" + STATE)
    assert "code" in str(exc.value)


@respx.mock
async def test_submit_callback_surfaces_google_denial(admin) -> None:
    with pytest.raises(GatewayAuthError) as exc:
        await admin.submit_callback(
            STATE, f"http://localhost:51121/oauth-callback?state={STATE}&error=access_denied"
        )
    assert "access_denied" in str(exc.value)


@respx.mock
async def test_submit_callback_empty_url(admin) -> None:
    with pytest.raises(GatewayBadResponse):
        await admin.submit_callback(STATE, "   ")


@respx.mock
async def test_submit_callback_expired_state_tells_user_to_restart(admin) -> None:
    """CLIProxy chỉ giữ `state` 5 phút — câu thông báo phải nói đúng việc cần làm."""
    respx.post(f"{MGMT}/oauth-callback").mock(
        return_value=httpx.Response(
            200, json={"error": "unknown or expired state", "status": "error"}
        )
    )

    with pytest.raises(GatewayAuthError) as exc:
        await admin.submit_callback(STATE, f"http://x/cb?state={STATE}&code=abc")
    assert "5 phút" in str(exc.value)


# ---------------------------------------------------------------------------
# cancel_oauth
# ---------------------------------------------------------------------------
@respx.mock
async def test_cancel_oauth(admin) -> None:
    route = respx.delete(f"{MGMT}/oauth-session").mock(
        return_value=httpx.Response(200, json={"cancelled": True, "status": "ok"})
    )

    assert await admin.cancel_oauth(STATE) is True
    assert route.calls[0].request.url.params["state"] == STATE


async def test_cancel_oauth_requires_state(admin) -> None:
    with pytest.raises(ValueError, match="state"):
        await admin.cancel_oauth("")


# ---------------------------------------------------------------------------
# auth-files — nguồn sự thật của badge "Đã kết nối" (B6) + bẫy B10
# ---------------------------------------------------------------------------
@respx.mock
async def test_is_connected_reads_auth_files_not_auth_status(admin) -> None:
    files_route = respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"files": []})
    )
    status_route = respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    assert await admin.is_connected() is False

    assert files_route.called
    assert not status_route.called, (
        "Badge kết nối KHÔNG được đọc từ get-auth-status: thiếu state nó trả "
        '{"status":"ok"} dù chưa đăng nhập bao giờ (bẫy B6).'
    )


async def test_delete_auth_file_refuses_empty_name_trap_b10(admin) -> None:
    """Bẫy B10: route không có "xoá tất cả"; thiếu `?name=` → 400 invalid name."""
    with pytest.raises(ValueError, match="B10"):
        await admin.delete_auth_file("")


@respx.mock
async def test_disconnect_all_deletes_one_by_one(admin) -> None:
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(
            200, json={"files": ["antigravity-a@gmail.com.json", "antigravity-b@gmail.com.json"]}
        )
    )
    delete_route = respx.delete(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    assert await admin.disconnect_all() == 2
    assert delete_route.call_count == 2
    deleted = {call.request.url.params["name"] for call in delete_route.calls}
    assert deleted == {"antigravity-a@gmail.com.json", "antigravity-b@gmail.com.json"}


# ---------------------------------------------------------------------------
# Bẫy B3 — không retry lỗi xác thực
# ---------------------------------------------------------------------------
@respx.mock
async def test_auth_error_makes_exactly_one_request_trap_b3(admin) -> None:
    route = respx.get(f"{MGMT}/antigravity-auth-url").mock(
        return_value=httpx.Response(401, json={"error": "invalid management key"})
    )

    with pytest.raises(GatewayAuthError):
        await admin.start_oauth()

    assert route.call_count == 1


async def _assert_rejects(admin, url: str) -> None:
    with pytest.raises(GatewayBadResponse) as exc:
        await admin.submit_callback(STATE, url)
    assert "phiên đăng nhập khác" in str(exc.value)
