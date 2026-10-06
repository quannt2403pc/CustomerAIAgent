"""DB → gateway đang chọn (plan.md §5.1.4).

Đọc hàng `llm_settings` **mỗi lần gọi**, không cache: đổi cổng trên UI phải có
hiệu lực ở lần phân tích ngay sau đó, không cần restart app (task.md D1.10).

Hàng `llm_settings` chỉ có một (app một người vận hành — plan.md §12.1).
`provider` rỗng = *chưa chọn* → `GatewayNotConfigured`, UI buộc người dùng chọn.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import GatewayNoCredential, GatewayNotConfigured
from app.core.logging import get_logger
from app.llm.antigravity import AntigravityGateway
from app.llm.base import LLMGateway
from app.llm.google_api_key import GoogleApiKeyGateway
from app.models import LlmSettings
from app.services import credentials

log = get_logger(__name__)


@dataclass(frozen=True)
class ActiveConfig:
    """Lựa chọn hiện hành, đã đọc từ DB."""

    provider: str
    model: str
    temperature: float
    max_output_tokens: int

    @property
    def is_configured(self) -> bool:
        return bool(self.provider)


async def get_settings_row(session: AsyncSession) -> LlmSettings:
    """Lấy (hoặc tạo) hàng cấu hình duy nhất.

    Tạo với `provider=""` — tức *chưa chọn*. Cố ý không điền cổng mặc định:
    đoán hộ sẽ khiến người dùng tưởng đã cấu hình xong (plan.md §12.2).
    """
    row = (await session.execute(select(LlmSettings).limit(1))).scalar_one_or_none()
    if row is None:
        app_settings = get_settings()
        row = LlmSettings(
            provider=app_settings.llm_provider,
            model=app_settings.llm_model,
            temperature=app_settings.llm_temperature,
            max_output_tokens=app_settings.llm_max_output_tokens,
        )
        session.add(row)
        await session.flush()
    return row


async def get_active_config(session: AsyncSession) -> ActiveConfig:
    row = await get_settings_row(session)
    return ActiveConfig(
        provider=row.provider,
        model=row.model,
        temperature=row.temperature,
        max_output_tokens=row.max_output_tokens,
    )


async def set_provider(session: AsyncSession, provider: str) -> ActiveConfig:
    """Đổi cổng. **Xoá model đang chọn** vì danh mục hai cổng khác nhau.

    Giữ lại model cũ sẽ tạo ra một cấu hình trông hợp lệ mà gọi là lỗi; để rỗng
    thì UI buộc chọn lại — đúng điều cần xảy ra (plan.md §5.1.4).
    """
    row = await get_settings_row(session)
    if row.provider != provider:
        row.model = ""
    row.provider = provider
    await session.flush()
    log.info("Đã đổi cổng model sang %s", provider or "(chưa chọn)")
    return await get_active_config(session)


async def set_model(session: AsyncSession, model: str) -> ActiveConfig:
    row = await get_settings_row(session)
    row.model = model
    await session.flush()
    return await get_active_config(session)


async def resolve_gateway(
    session: AsyncSession,
    *,
    provider: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMGateway:
    """Trả gateway của cổng đang chọn trong DB.

    `provider` chỉ để CLI ghi đè bằng cờ `--provider`.
    """
    app_settings = get_settings()
    chosen = provider or (await get_active_config(session)).provider

    if not chosen:
        raise GatewayNotConfigured()

    if chosen == "antigravity":
        return AntigravityGateway(app_settings, client)

    if chosen == "google_api_key":
        key = await credentials.get_secret(session, credentials.KIND_GOOGLE_API_KEY)
        # Dự phòng cho CLI chạy thuần không DB: cho phép lấy key từ .env.
        key = key or app_settings.google_api_key.strip()
        if not key:
            raise GatewayNoCredential(
                "Chưa có Google API key. Vào Cài đặt → “Dùng Google API Key” để nhập, "
                "hoặc đặt GOOGLE_API_KEY trong .env khi chạy CLI."
            )
        return GoogleApiKeyGateway(key, app_settings, client)

    # CheckConstraint ở DB đã chặn, nhưng cờ --provider của CLI thì chưa.
    raise GatewayNotConfigured(
        f"Cổng `{chosen}` không tồn tại. Chỉ nhận `antigravity` hoặc `google_api_key`."
    )
