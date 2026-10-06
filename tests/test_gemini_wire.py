"""D1.6 — dựng/đọc payload Gemini v1beta + chính sách retry.

Hai test quan trọng nhất ở đây canh gác bẫy B3 (403 không retry → không tự ban
IP) và hành vi 429 (retry đúng số lượt rồi bỏ cuộc).
"""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from app.core.errors import (
    GatewayAuthError,
    GatewayBadResponse,
    GatewayDisabled,
    GatewayModelInvalid,
    GatewayNoCredential,
    GatewayProviderBlocked,
    GatewayRateLimited,
    GatewayUnavailable,
)
from app.llm import gemini_wire as wire

URL = "https://example.test/v1beta/models/m:generateContent"


@pytest.fixture
def no_sleep():
    """Thay `asyncio.sleep` để test không chờ 0.5 + 1 + 2 = 3.5s thật."""
    calls: list[float] = []

    async def _sleep(delay: float) -> None:
        calls.append(delay)

    return calls, _sleep


# ---------------------------------------------------------------------------
# Dựng payload
# ---------------------------------------------------------------------------
def test_build_payload_shape() -> None:
    payload = wire.build_payload(
        [wire.text_part("xin chào")], temperature=0.5, max_output_tokens=256
    )
    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"] == [{"text": "xin chào"}]
    assert payload["generationConfig"] == {"temperature": 0.5, "maxOutputTokens": 256}
    assert "systemInstruction" not in payload


def test_build_payload_with_system_instruction_and_json_mime() -> None:
    payload = wire.build_payload(
        [wire.text_part("x")],
        system_instruction="chỉ trả JSON",
        response_mime_type="application/json",
    )
    assert payload["systemInstruction"]["parts"][0]["text"] == "chỉ trả JSON"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_image_part_is_base64_inline_data() -> None:
    part = wire.image_part(b"\x89PNG-gia", mime_type="image/webp")
    assert part["inline_data"]["mime_type"] == "image/webp"
    assert base64.b64decode(part["inline_data"]["data"]) == b"\x89PNG-gia"


# ---------------------------------------------------------------------------
# Đọc kết quả
# ---------------------------------------------------------------------------
def test_extract_text_joins_parts() -> None:
    response = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    assert wire.extract_text(response) == "ab"


@pytest.mark.parametrize(
    "response, expect_in_message",
    [
        ({}, "không trả về nội dung"),
        ({"candidates": []}, "không trả về nội dung"),
        (
            {"promptFeedback": {"blockReason": "SAFETY"}},
            "bộ lọc an toàn",
        ),
        (
            {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]},
            "bộ lọc an toàn",
        ),
        (
            {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]},
            "giới hạn token",
        ),
        (
            {"candidates": [{"finishReason": "RECITATION", "content": {}}]},
            "bản quyền",
        ),
        (
            {"candidates": [{"content": {"parts": []}}]},
            "rỗng",
        ),
        (
            {"error": {"message": "model not found"}},
            "trả về lỗi",
        ),
    ],
)
def test_extract_text_broken_shapes_give_specific_messages(response, expect_in_message) -> None:
    """Mỗi nhánh hỏng phải nói rõ hỏng ở đâu — không gộp thành một câu chung."""
    with pytest.raises(GatewayBadResponse) as exc:
        wire.extract_text(response)
    assert expect_in_message in str(exc.value)


def test_extract_usage_skips_missing_fields_instead_of_faking_zero() -> None:
    response = {"usageMetadata": {"promptTokenCount": 11, "totalTokenCount": 30}}
    assert wire.extract_usage(response) == {"prompt_tokens": 11, "total_tokens": 30}


def test_extract_usage_empty_when_absent() -> None:
    assert wire.extract_usage({}) == {}


def test_extract_finish_reason() -> None:
    assert wire.extract_finish_reason({"candidates": [{"finishReason": "STOP"}]}) == "STOP"
    assert wire.extract_finish_reason({}) is None


# ---------------------------------------------------------------------------
# Retry — bẫy B3
# ---------------------------------------------------------------------------
@respx.mock
async def test_403_raises_immediately_with_exactly_one_request(no_sleep) -> None:
    """Bẫy B3: sai key 5 lần → CLIProxy ban IP 30 phút. Retry là tự khoá mình."""
    calls, sleep = no_sleep
    route = respx.post(URL).mock(return_value=httpx.Response(403, json={"error": "forbidden"}))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayAuthError):
            await wire.request_with_retry(
                client, "POST", URL, provider="antigravity", sleep=sleep, json={}
            )

    assert route.call_count == 1
    assert calls == []  # không hề ngủ → không hề retry


@respx.mock
async def test_401_also_never_retried(no_sleep) -> None:
    _, sleep = no_sleep
    route = respx.post(URL).mock(return_value=httpx.Response(401, text="unauthorized"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayAuthError):
            await wire.request_with_retry(
                client, "POST", URL, provider="google_api_key", sleep=sleep, json={}
            )

    assert route.call_count == 1


@respx.mock
async def test_429_retries_three_times_then_raises(no_sleep) -> None:
    calls, sleep = no_sleep
    route = respx.post(URL).mock(return_value=httpx.Response(429, text="quota"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayRateLimited):
            await wire.request_with_retry(
                client, "POST", URL, provider="google_api_key", sleep=sleep, json={}
            )

    assert route.call_count == wire.RETRY_ATTEMPTS + 1  # 1 lượt đầu + 3 retry
    assert calls == [0.5, 1.0, 2.0]  # backoff 0.5s × 2^n


@respx.mock
async def test_503_then_200_succeeds(no_sleep) -> None:
    _, sleep = no_sleep
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, text="temporarily down"),
            httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}),
        ]
    )

    async with httpx.AsyncClient() as client:
        response = await wire.request_with_retry(
            client, "POST", URL, provider="antigravity", sleep=sleep, json={}
        )

    assert wire.extract_text(response.json()) == "ok"


@respx.mock
async def test_503_auth_unavailable_means_no_credential_not_outage(no_sleep) -> None:
    """CLIProxy trả 503 `auth_unavailable` khi chưa đăng nhập.

    Nhập nhèm với "cổng chết" sẽ khiến người vận hành chờ vô ích thay vì bấm
    Đăng nhập Google.
    """
    _, sleep = no_sleep
    respx.post(URL).mock(return_value=httpx.Response(503, json={"error": "auth_unavailable"}))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayNoCredential):
            await wire.request_with_retry(
                client, "POST", URL, provider="antigravity", sleep=sleep, json={}
            )


@respx.mock
async def test_timeout_is_retried_then_reported_as_unavailable(no_sleep) -> None:
    calls, sleep = no_sleep
    respx.post(URL).mock(side_effect=httpx.ConnectTimeout("quá hạn"))

    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayUnavailable):
            await wire.request_with_retry(
                client, "POST", URL, provider="antigravity", sleep=sleep, json={}
            )

    assert len(calls) == wire.RETRY_ATTEMPTS


# ---------------------------------------------------------------------------
# Ánh xạ status → lỗi
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status, body, expected",
    [
        (403, '{"error":"auth_unavailable"}', GatewayNoCredential),
        (403, '{"error":"account blocked"}', GatewayProviderBlocked),
        (403, "forbidden", GatewayAuthError),
        (404, "model gemini-x not found", GatewayModelInvalid),
        (404, "page not found", GatewayDisabled),
        # Google báo key sai bằng 400, không phải 401.
        (400, "API key not valid. Please pass a valid API key.", GatewayAuthError),
        (400, "invalid model name", GatewayModelInvalid),
        (400, "bad request", GatewayBadResponse),
        (429, "quota exceeded", GatewayRateLimited),
        (500, "boom", GatewayUnavailable),
        (502, "bad gateway", GatewayUnavailable),
    ],
)
def test_status_mapping(status: int, body: str, expected: type[Exception]) -> None:
    response = httpx.Response(status, text=body, request=httpx.Request("POST", URL))
    with pytest.raises(expected):
        wire.raise_for_gateway_status(response, provider="antigravity")


def test_success_status_does_not_raise() -> None:
    response = httpx.Response(200, text="{}", request=httpx.Request("POST", URL))
    wire.raise_for_gateway_status(response, provider="antigravity")


def test_error_details_never_reach_the_api_payload() -> None:
    response = httpx.Response(
        500, text="stack trace nội bộ + api_key=AIzaLEAK", request=httpx.Request("POST", URL)
    )
    with pytest.raises(GatewayUnavailable) as exc:
        wire.raise_for_gateway_status(response, provider="antigravity")

    payload = exc.value.to_payload()
    assert set(payload) == {"code", "message"}
    assert "AIzaLEAK" not in str(payload)


def test_retry_policy_excludes_auth_statuses() -> None:
    """Canh gác: ai thêm 401/403 vào danh sách retry sẽ làm test này đỏ."""
    assert wire.RETRYABLE_STATUSES.isdisjoint({401, 403})
    assert wire.RETRYABLE_STATUSES == {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# I-15 — danh mục liệt kê cả model không gọi được
# ---------------------------------------------------------------------------
def test_retired_model_404_keeps_googles_own_suggestion() -> None:
    """`models.list` vẫn liệt kê model đã ngừng cho người dùng mới (đo thật I-15).

    Google nói luôn phải dùng model nào thay thế — vứt câu đó đi rồi chỉ nói
    "chọn lại từ danh sách" là bỏ mất chỉ dẫn hữu ích nhất.
    """
    body = (
        '{ "error": { "code": 404, "message": "This model models/gemini-2.5-flash is no '
        "longer available to new users. Please update your code to use "
        'models/gemini-3.8-flash for the latest features and improvements." } }'
    )
    response = httpx.Response(404, text=body, request=httpx.Request("POST", URL))

    with pytest.raises(GatewayModelInvalid) as exc:
        wire.raise_for_gateway_status(response, provider="google_api_key")

    message = str(exc.value)
    assert "no longer available" in message
    assert "gemini-3.8-flash" in message  # tên đến từ phản hồi lúc chạy, không hardcode


def test_404_without_a_message_falls_back_to_generic_text() -> None:
    response = httpx.Response(404, text="model not found", request=httpx.Request("POST", URL))
    with pytest.raises(GatewayModelInvalid) as exc:
        wire.raise_for_gateway_status(response, provider="antigravity")
    assert "chọn lại" in str(exc.value)


def test_api_message_survives_a_truncated_body() -> None:
    """`_safe_body_snippet` cắt ngắn body → `message` có thể mất nháy đóng.

    Đây chính là lý do lần đầu câu gợi ý của Google không hiện ra (I-15).
    """
    cut = (
        '{   "error": {     "code": 404,     "message": "This model '
        "models/gemini-2.5-flash is no longer available to new users. Please update "
        "your code to use models/gemini-3.8-flash for the latest features"
    )
    response = httpx.Response(404, text=cut, request=httpx.Request("POST", URL))

    with pytest.raises(GatewayModelInvalid) as exc:
        wire.raise_for_gateway_status(response, provider="google_api_key")
    assert "gemini-3.8-flash" in str(exc.value)


def test_body_snippet_is_wide_enough_for_googles_pretty_printed_errors() -> None:
    """Thân lỗi của Google in đẹp — `message` nằm sau rất nhiều khoảng trắng.

    Cắt body ở 300 ký tự là mất đúng phần hữu ích nhất.
    """
    padding = " " * 320  # mô phỏng JSON in đẹp nhiều cấp
    body = f'{{{padding}"error": {{"code": 404, "message": "Use models/thay-the instead"}}}}'
    response = httpx.Response(404, text=body, request=httpx.Request("POST", URL))

    with pytest.raises(GatewayModelInvalid) as exc:
        wire.raise_for_gateway_status(response, provider="google_api_key")
    assert "thay-the" in str(exc.value)
