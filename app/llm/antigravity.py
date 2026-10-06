"""Cổng A — CLIProxy / Antigravity (OAuth Google). plan.md §5.1.2.

Gọi model **không cần header xác thực**: CLIProxy chạy trong mạng nội bộ Docker
với `api-keys: []`. Chỉ các route `/v0/management` mới cần management key, và
việc đó do `CliProxyAdmin` lo.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import GatewayError, GatewayUnavailable
from app.core.logging import get_logger
from app.llm.base import GatewayHealth, ModelInfo
from app.llm.cliproxy_admin import CliProxyAdmin
from app.llm.gemini_wire import request_with_retry

log = get_logger(__name__)


class AntigravityGateway:
    """Hiện thực `LLMGateway` cho cổng A."""

    provider = "antigravity"

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        admin: CliProxyAdmin | None = None,
    ):
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))
        # Gọi model mất hàng chục giây (prompt dài + ảnh) nên timeout đọc phải
        # rộng; connect thì ngắn để lỗi "cliproxy chết" lộ ra ngay.
        self._admin = admin or CliProxyAdmin(self._settings, self._client)

    @property
    def base_url(self) -> str:
        return self._settings.cliproxy_base_url.rstrip("/")

    async def generate_content(self, payload: dict, *, model: str) -> dict:
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        response = await request_with_retry(
            self._client,
            "POST",
            url,
            provider=self.provider,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        return _json_object(response)

    async def list_models(self) -> list[ModelInfo]:
        """Danh mục thật từ `/model-definitions/<channel>` (luật L6)."""
        return await self._admin.model_definitions()

    async def health(self) -> GatewayHealth:
        """`reachable` và `connected` là hai câu trả lời khác nhau.

        Cổng sống nhưng chưa đăng nhập → người vận hành cần bấm "Đăng nhập
        Google", không phải "thử lại sau". Gộp hai thứ này là đẩy họ đi sai hướng.
        """
        started = time.perf_counter()
        try:
            files = await self._admin.auth_files()
        except GatewayError as exc:
            return GatewayHealth(
                provider="antigravity",
                reachable=False,
                connected=False,
                detail=exc.message,
                latency_ms=_elapsed_ms(started),
            )

        account = next((f.account for f in files if f.account), None)
        return GatewayHealth(
            provider="antigravity",
            reachable=True,
            connected=bool(files),
            account=account,
            detail="" if files else "Chưa có tài khoản Google nào được kết nối.",
            latency_ms=_elapsed_ms(started),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise GatewayUnavailable(detail=f"cliproxy trả về phi-JSON: {response.text[:200]}") from exc
    if not isinstance(body, dict):
        raise GatewayUnavailable(detail=f"cliproxy trả về {type(body).__name__}, cần object")
    return body


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
