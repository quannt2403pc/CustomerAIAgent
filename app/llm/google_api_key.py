"""Cổng B — Google API Key trực tiếp. plan.md §5.1.3.

Đây là đường cài đặt **đơn giản nhất**: không cần Docker, không cần CLIProxy.
Vì vậy nhánh "không Docker" của README dựa vào cổng này.

Khác cổng A ở đúng ba điểm: base URL, header `x-goog-api-key`, và nguồn danh
mục model (`GET /v1beta/models`). Phần dựng/đọc payload dùng chung `gemini_wire`.

Quy tắc về key, không thương lượng: **không bao giờ** echo key ra message lỗi,
log, hay response. Key chỉ đi trong header.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import GatewayError, GatewayNoCredential, GatewayUnavailable
from app.core.logging import get_logger
from app.llm.base import GatewayHealth, ModelInfo
from app.llm.gemini_wire import request_with_retry

log = get_logger(__name__)

# Chỉ nhận model gọi được `generateContent` — model embedding/tts có trong danh
# mục nhưng chọn vào thì pipeline chết.
REQUIRED_METHOD = "generateContent"


class GoogleApiKeyGateway:
    """Hiện thực `LLMGateway` cho cổng B."""

    provider = "google_api_key"

    def __init__(
        self,
        api_key: str,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise GatewayNoCredential(
                "Chưa có Google API key. Vào Cài đặt → “Dùng Google API Key” để nhập."
            )
        self._api_key = api_key.strip()
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))

    @property
    def base_url(self) -> str:
        return self._settings.google_api_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        # Header, KHÔNG query string: `?key=` lọt vào access log của mọi proxy
        # trên đường đi.
        return {"x-goog-api-key": self._api_key, "Accept": "application/json"}

    async def generate_content(self, payload: dict, *, model: str) -> dict:
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        response = await request_with_retry(
            self._client,
            "POST",
            url,
            provider=self.provider,
            json=payload,
            headers={**self._headers(), "Content-Type": "application/json"},
        )
        return _json_object(response)

    async def list_models(self) -> list[ModelInfo]:
        """Danh mục thật từ `GET /v1beta/models`, lọc theo `generateContent`.

        Google phân trang bằng `nextPageToken`; bỏ qua nó sẽ cắt mất model nằm
        ở trang sau.
        """
        models: list[ModelInfo] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"pageSize": 200}
            if page_token:
                params["pageToken"] = page_token

            response = await request_with_retry(
                self._client,
                "GET",
                f"{self.base_url}/v1beta/models",
                provider=self.provider,
                headers=self._headers(),
                params=params,
            )
            body = _json_object(response)
            for raw in body.get("models") or []:
                if isinstance(raw, dict) and _supports_generate_content(raw):
                    models.append(_model_info_from_wire(raw))

            page_token = body.get("nextPageToken")
            if not page_token:
                return models

    async def validate_key(self) -> bool:
        """Ping nhẹ để xác thực key **trước khi** ghi vào DB.

        Lưu key sai rồi để pipeline chết lúc 20h là kiểu lỗi tệ nhất: xảy ra khi
        không ai nhìn.
        """
        await self.list_models()
        return True

    async def health(self) -> GatewayHealth:
        started = time.perf_counter()
        try:
            models = await self.list_models()
        except GatewayError as exc:
            return GatewayHealth(
                provider="google_api_key",
                reachable=False,
                connected=False,
                detail=exc.message,
                latency_ms=_elapsed_ms(started),
            )
        return GatewayHealth(
            provider="google_api_key",
            reachable=True,
            connected=True,  # key hợp lệ gọi được danh mục → coi như đã kết nối
            account=f"••••{self._api_key[-4:]}",
            detail=f"Danh mục có {len(models)} model dùng được.",
            latency_ms=_elapsed_ms(started),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _supports_generate_content(raw: dict[str, Any]) -> bool:
    methods = raw.get("supportedGenerationMethods")
    if not isinstance(methods, list):
        # Thiếu field thì không suy đoán — giữ lại và để lỗi lộ ra lúc gọi, thay
        # vì lặng lẽ ẩn một model có thể dùng được.
        return True
    return REQUIRED_METHOD in methods


def _model_info_from_wire(raw: dict[str, Any]) -> ModelInfo:
    # `models/gemini-x` → `gemini-x`
    model_id = str(raw.get("name") or "").removeprefix("models/")
    return ModelInfo(
        id=model_id,
        display_name=str(raw.get("displayName") or model_id),
        # `models.list` của Google KHÔNG có cờ vision (I-06) → None = chưa biết.
        # Bịa False chặn oan model đọc được ảnh; bịa True làm bước vision chết
        # giữa pipeline. UI cảnh báo là cách trung thực duy nhất.
        supports_vision=None,
        input_token_limit=_as_int(raw.get("inputTokenLimit")),
        output_token_limit=_as_int(raw.get("outputTokenLimit")),
    )


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise GatewayUnavailable(
            detail=f"generativelanguage trả về phi-JSON: {response.text[:200]}"
        ) from exc
    if not isinstance(body, dict):
        raise GatewayUnavailable(detail=f"cần object JSON, nhận {type(body).__name__}")
    return body


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
