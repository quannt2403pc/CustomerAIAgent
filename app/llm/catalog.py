"""Danh mục model — cache ngắn + tra năng lực vision.

Luật L6: **không hardcode danh mục model.** Module này không chứa tên model nào;
nó chỉ nhớ tạm thứ cổng vừa trả về.

Vì sao cần cache: dropdown model trên UI nạp lại mỗi lần vào trang Cài đặt, mà
`/model-definitions` phải đi qua CLIProxy. 10 phút là đủ ngắn để model mới xuất
hiện trong một phiên làm việc, đủ dài để không gọi lại mỗi lần bấm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.errors import GatewayModelInvalid
from app.core.logging import get_logger
from app.llm.base import LLMGateway, ModelInfo

log = get_logger(__name__)

CACHE_TTL_SECONDS = 600.0


@dataclass
class _CacheEntry:
    models: list[ModelInfo]
    fetched_at: float

    def is_fresh(self, now: float, ttl: float) -> bool:
        return (now - self.fetched_at) < ttl


class ModelCatalog:
    """Cache danh mục theo từng cổng.

    Khoá cache là `provider`, không phải instance gateway: đổi API key hay đăng
    nhập lại vẫn là cùng một cổng, và `refresh=True` lo phần làm mới.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS, clock=time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, _CacheEntry] = {}

    async def list_models(self, gateway: LLMGateway, *, refresh: bool = False) -> list[ModelInfo]:
        provider = gateway.provider
        now = self._clock()

        cached = self._cache.get(provider)
        if cached and not refresh and cached.is_fresh(now, self._ttl):
            return cached.models

        models = await gateway.list_models()
        self._cache[provider] = _CacheEntry(models=models, fetched_at=now)
        log.info("Đã nạp danh mục cổng %s: %d model", provider, len(models))
        return models

    async def find(self, gateway: LLMGateway, model_id: str) -> ModelInfo:
        """Tìm một model trong danh mục **hiện tại** của cổng.

        Không thấy → `GatewayModelInvalid` nêu rõ **tên model + tên cổng**. Đổi
        cổng mà model cũ không còn thì người dùng phải chọn lại, không đoán hộ.
        """
        models = await self.list_models(gateway)
        for model in models:
            if model.id == model_id:
                return model

        # Thử lại với danh mục mới: có thể cache đã cũ so với cổng.
        models = await self.list_models(gateway, refresh=True)
        for model in models:
            if model.id == model_id:
                return model

        raise GatewayModelInvalid(
            f"Model `{model_id}` không có trong cổng `{gateway.provider}`. "
            "Hãy chọn lại từ danh sách.",
            detail=f"danh mục hiện có {len(models)} model",
        )

    async def supports_vision(self, gateway: LLMGateway, model_id: str) -> bool | None:
        """`None` = **chưa biết**, và đó là một câu trả lời hợp lệ.

        Cổng A đọc được `supportedInputModalities` nên trả True/False thật.
        Cổng B không có cờ tương đương → `None`; UI phải cảnh báo
        "`visual_context` có thể là null" thay vì đoán hộ (luật L1, I-06).
        """
        return (await self.find(gateway, model_id)).supports_vision

    def invalidate(self, provider: str | None = None) -> None:
        if provider is None:
            self._cache.clear()
        else:
            self._cache.pop(provider, None)


# Một catalog dùng chung cho cả tiến trình.
_CATALOG = ModelCatalog()


def get_catalog() -> ModelCatalog:
    return _CATALOG
