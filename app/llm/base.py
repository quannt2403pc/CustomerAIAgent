"""Trừu tượng hoá cổng model (plan.md §5.1.1).

Cả hai cổng đều nói **giao thức Gemini native v1beta**, nên chúng chỉ khác nhau
*base URL* + *header xác thực* + *nguồn danh mục model*. Phần dựng/đọc payload
nằm chung ở `gemini_wire.py` — không nhân bản.

Taxonomy lỗi ở `app/core/errors.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

ProviderName = Literal["antigravity", "google_api_key"]


@dataclass(frozen=True)
class ModelInfo:
    """Một model **thật** lấy từ danh mục của cổng đang chọn (luật L6).

    `supports_vision` cố ý cho phép `None` = *chưa biết*. Google `models.list`
    không trả cờ vision tường minh; bịa ra `False` sẽ chặn oan model đọc được
    ảnh, bịa ra `True` sẽ làm bước vision chết giữa pipeline. `None` nói đúng
    sự thật và để UI cảnh báo thay vì quyết định hộ.
    """

    id: str
    display_name: str = ""
    supports_vision: bool | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("ModelInfo.id không được rỗng")


@dataclass(frozen=True)
class GatewayHealth:
    """Ảnh chụp trạng thái cổng để UI hiện badge.

    `connected` và `reachable` là hai việc khác nhau: cổng sống nhưng chưa có
    credential thì `reachable=True, connected=False` — người vận hành cần biết
    phải bấm "Đăng nhập", không phải "thử lại sau" (plan.md §5.1.5).
    """

    provider: ProviderName
    reachable: bool
    connected: bool
    account: str | None = None  # email (cổng A) hoặc hint của key (cổng B)
    detail: str = ""
    latency_ms: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    """Kết quả đã bóc tách — tầng trên không bao giờ thấy JSON thô của model."""

    text: str
    model: str
    provider: ProviderName
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None


@runtime_checkable
class LLMGateway(Protocol):
    """Hợp đồng mà `antigravity.py` và `google_api_key.py` đều phải thoả."""

    provider: ProviderName

    async def generate_content(self, payload: dict, *, model: str) -> dict:
        """Gọi `:generateContent`, trả **JSON thô** của Gemini v1beta."""
        ...

    async def list_models(self) -> list[ModelInfo]:
        """Danh mục model thật của cổng này. Không bao giờ trả danh sách cứng."""
        ...

    async def health(self) -> GatewayHealth: ...

    async def aclose(self) -> None: ...
