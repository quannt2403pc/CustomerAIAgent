"""Giao thức Gemini native v1beta — dựng payload, đọc kết quả, chính sách retry.

Dùng chung cho **cả hai** cổng (plan.md §5.1.1): chúng chỉ khác base URL và
header, còn hình dạng payload thì y nhau.

Chính sách retry (plan.md §5.1.5) — điểm then chốt:

- Retry **chỉ** với `429, 500, 502, 503, 504`, 3 lượt, backoff `0.5s × 2^n`.
- **Không bao giờ** retry `401/403`. Đây không phải sự thận trọng chung chung:
  CLIProxy ban IP 30 phút sau 5 lần sai management key, mà container `api` dùng
  một IP duy nhất → retry là tự khoá mình (bẫy B3).
"""

from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

import httpx

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
from app.core.logging import get_logger

log = get_logger(__name__)

# Số lượt **retry** (chưa tính lượt gọi đầu) → tối đa 4 request.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# 401/403 nằm ngoài danh sách trên một cách có chủ đích. Đừng thêm vào.
NEVER_RETRY_STATUSES = frozenset({401, 403})


# ---------------------------------------------------------------------------
# Dựng payload
# ---------------------------------------------------------------------------
def text_part(text: str) -> dict[str, Any]:
    return {"text": text}


def image_part(data: bytes, *, mime_type: str) -> dict[str, Any]:
    """Ảnh nhúng trực tiếp (`inline_data`) — không cần Files API cho ảnh nhỏ."""
    return {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(data).decode()}}


def build_payload(
    parts: list[dict[str, Any]],
    *,
    temperature: float = 0.9,
    max_output_tokens: int = 4096,
    system_instruction: str | None = None,
    response_mime_type: str | None = None,
) -> dict[str, Any]:
    """Payload `:generateContent` một lượt (single-turn).

    `response_mime_type="application/json"` buộc model trả JSON — dùng cho các
    bước cần cấu trúc (demographics, chuỗi tin nhắn), đỡ phải vá chuỗi bằng regex.
    """
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_output_tokens,
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type

    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": generation_config,
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    return payload


# ---------------------------------------------------------------------------
# Đọc kết quả
# ---------------------------------------------------------------------------
def extract_text(response: dict[str, Any]) -> str:
    """Lấy text từ `candidates[0].content.parts[].text`.

    Mọi nhánh hỏng đều phải cho ra câu **nói rõ hỏng ở đâu**. Trả chuỗi rỗng ở
    đây sẽ đẩy một lỗi hạ tầng xuống thành "model nói chuyện nhạt" — rất khó lần.
    """
    if not isinstance(response, dict):
        raise GatewayBadResponse(detail=f"Kiểu phản hồi lạ: {type(response).__name__}")

    # Google báo lỗi logic bằng thân `{"error": {...}}` kèm HTTP 200 trong một
    # số đường (qua proxy chẳng hạn) — kiểm tra trước khi tìm candidates.
    if error := response.get("error"):
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        raise GatewayBadResponse(
            "Cổng model trả về lỗi. Hãy kiểm tra lại model đang chọn.",
            detail=f"error trong body: {message[:300]}",
        )

    candidates = response.get("candidates")
    if not candidates:
        # Prompt bị chặn ngay từ đầu thì `promptFeedback.blockReason` mới có.
        block_reason = (response.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            raise GatewayBadResponse(
                f"Yêu cầu bị bộ lọc an toàn của Google chặn ({block_reason}). "
                "Hãy thử lại với nội dung trung tính hơn.",
                detail=f"promptFeedback.blockReason={block_reason}",
            )
        raise GatewayBadResponse(
            "Cổng model không trả về nội dung nào.",
            detail="thiếu `candidates` trong phản hồi",
        )

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    parts = (candidate.get("content") or {}).get("parts") or []
    chunks = [p["text"] for p in parts if isinstance(p, dict) and p.get("text")]

    if not chunks:
        if finish_reason == "SAFETY":
            raise GatewayBadResponse(
                "Nội dung bị bộ lọc an toàn của Google chặn. Hãy thử lại hoặc "
                "giảm mức độ riêng tư của dữ liệu đưa vào.",
                detail="finishReason=SAFETY, parts rỗng",
            )
        if finish_reason == "MAX_TOKENS":
            raise GatewayBadResponse(
                "Phản hồi bị cắt vì vượt giới hạn token. Hãy tăng max_output_tokens.",
                detail="finishReason=MAX_TOKENS, parts rỗng",
            )
        if finish_reason == "RECITATION":
            raise GatewayBadResponse(
                "Google chặn phản hồi vì nghi trích dẫn nguyên văn nguồn có bản quyền.",
                detail="finishReason=RECITATION",
            )
        raise GatewayBadResponse(
            "Cổng model trả về phần nội dung rỗng.",
            detail=f"parts rỗng, finishReason={finish_reason}",
        )

    return "".join(chunks).strip()


def extract_finish_reason(response: dict[str, Any]) -> str | None:
    candidates = response.get("candidates") or []
    return candidates[0].get("finishReason") if candidates else None


def extract_usage(response: dict[str, Any]) -> dict[str, int]:
    """`usageMetadata` → dict phẳng. Thiếu field nào thì bỏ, không điền 0 giả."""
    meta = response.get("usageMetadata") or {}
    mapping = {
        "promptTokenCount": "prompt_tokens",
        "candidatesTokenCount": "output_tokens",
        "totalTokenCount": "total_tokens",
    }
    return {
        our_name: meta[wire_name]
        for wire_name, our_name in mapping.items()
        if isinstance(meta.get(wire_name), int)
    }


# ---------------------------------------------------------------------------
# Gọi HTTP + retry
# ---------------------------------------------------------------------------
def raise_for_gateway_status(response: httpx.Response, *, provider: str) -> None:
    """Dịch HTTP status → exception trong taxonomy (plan.md §5.1.5)."""
    status = response.status_code
    if status < 400:
        return

    body = _safe_body_snippet(response)

    if status in (401, 403):
        # CLIProxy trả 503 `auth_unavailable` khi chưa có credential, nhưng một
        # số bản trả 403 — bắt cả hai để câu thông báo đúng việc cần làm.
        if "auth_unavailable" in body or "no available" in body.lower():
            raise GatewayNoCredential(detail=f"{provider} {status}: {body}")
        if "blocked" in body.lower() or "suspended" in body.lower():
            raise GatewayProviderBlocked(detail=f"{provider} {status}: {body}")
        raise GatewayAuthError(detail=f"{provider} {status}: {body}")

    if status == 404:
        # Hai nghĩa rất khác nhau: model không tồn tại, hay route quản trị tắt.
        if "model" in body.lower():
            # Google thường nói luôn phải dùng model nào thay thế. Vứt câu đó đi
            # rồi chỉ nói "chọn lại từ danh sách" là bỏ mất chỉ dẫn hữu ích nhất
            # (task.md I-15). Tên model ở đây đến từ **phản hồi lúc chạy**, không
            # phải danh mục hardcode — không vi phạm L6.
            if hint := _extract_api_message(body):
                raise GatewayModelInvalid(
                    f"Cổng `{provider}` từ chối model đang chọn. Google trả lời: {hint}",
                    detail=f"{provider} 404: {body}",
                )
            raise GatewayModelInvalid(detail=f"{provider} 404: {body}")
        raise GatewayDisabled(detail=f"{provider} 404: {body}")

    if status == 400:
        lowered = body.lower()
        # Google báo key sai bằng **400**, không phải 401: body là
        # "API key not valid. Please pass a valid API key." Để nó rơi vào nhánh
        # chung thì người dùng nhận câu "kiểm tra model và tham số" — sai hướng.
        if "api key" in lowered or "api_key" in lowered:
            raise GatewayAuthError(detail=f"{provider} 400: {body}")
        if "model" in lowered:
            raise GatewayModelInvalid(detail=f"{provider} 400: {body}")
        raise GatewayBadResponse(
            "Cổng model từ chối yêu cầu (400). Hãy kiểm tra model và tham số.",
            detail=f"{provider} 400: {body}",
        )

    if status == 429:
        raise GatewayRateLimited(detail=f"{provider} 429: {body}")

    if status == 503 and "auth_unavailable" in body:
        raise GatewayNoCredential(detail=f"{provider} 503: {body}")

    raise GatewayUnavailable(detail=f"{provider} {status}: {body}")


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    sleep=asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Gọi HTTP có retry theo đúng chính sách §5.1.5.

    `sleep` tiêm được để test không phải chờ thật.
    """
    last_error: Exception | None = None

    for attempt in range(RETRY_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = GatewayUnavailable(detail=f"{provider} {type(exc).__name__}: {exc}")
            if attempt == RETRY_ATTEMPTS:
                raise last_error from exc
            await sleep(RETRY_BASE_DELAY * (2**attempt))
            continue

        if response.status_code in NEVER_RETRY_STATUSES:
            # Dừng tại đây, đúng 1 request cho nhánh này (bẫy B3).
            raise_for_gateway_status(response, provider=provider)

        if response.status_code in RETRYABLE_STATUSES and attempt < RETRY_ATTEMPTS:
            delay = RETRY_BASE_DELAY * (2**attempt)
            log.warning(
                "Cổng %s trả %s, thử lại lượt %d/%d sau %.1fs",
                provider,
                response.status_code,
                attempt + 1,
                RETRY_ATTEMPTS,
                delay,
            )
            await sleep(delay)
            continue

        raise_for_gateway_status(response, provider=provider)
        return response

    # Hết lượt mà vẫn lỗi mạng (nhánh raise ở trên đã lo), giữ cho mypy vui.
    raise last_error or GatewayUnavailable()


def _extract_api_message(body: str, *, limit: int = 220) -> str:
    """Lấy `error.message` của Google ra khỏi thân JSON.

    Dùng regex chứ không `json.loads`: `body` ở đây là đoạn đã cắt ngắn để log
    nên thường **không còn là JSON hợp lệ** — dấu nháy đóng của `message` rất
    có thể đã bị cắt mất. Vì vậy mẫu nhận cả chuỗi chưa đóng (`|$`).
    """
    match = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)', body)
    if not match:
        return ""
    message = match.group(1).replace('\\"', '"').replace("\\n", " ")
    return " ".join(message.split())[:limit]


def _safe_body_snippet(response: httpx.Response, *, limit: int = 600) -> str:
    """Trích thân phản hồi để **log**, không bao giờ đưa ra response của app.

    600 ký tự chứ không 300: thân lỗi của Google in đẹp (rất nhiều khoảng trắng)
    nên 300 ký tự cắt mất cả `error.message` — đúng phần hữu ích nhất (I-15).
    """
    try:
        text = response.text
    except Exception:  # pragma: no cover — body nhị phân/hỏng
        return "<không đọc được thân phản hồi>"
    return text[:limit].replace("\n", " ")
