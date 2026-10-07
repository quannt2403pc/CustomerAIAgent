"""Nối `app.messenger` với DB: lấy token, dựng client, xử lý tin đến.

Vì sao tách khỏi router: logic "tin đến thì làm gì" phải dùng được cả từ webhook
và từ test, mà không dựng cả FastAPI. Và vì sao tách khỏi `app.messenger`: tầng
kia **thuần giao thức** (HTTP + chữ ký), không biết gì về bảng biểu.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import MessengerDisabled
from app.core.logging import get_logger
from app.messenger import InboundMessage, PageMessenger
from app.models import Conversation, ConversationMessage
from app.services import credentials

log = get_logger(__name__)


async def build_messenger(session: AsyncSession) -> PageMessenger:
    """Dựng client từ token đã lưu. Chưa có token → `MessengerDisabled` (409)."""
    settings = get_settings()
    token = await credentials.get_secret(session, credentials.KIND_PAGE_ACCESS_TOKEN)
    if not token:
        raise MessengerDisabled
    return PageMessenger(
        page_access_token=token,
        base_url=settings.graph_api_base_url,
        api_version=settings.graph_api_version,
        use_human_agent_tag=settings.messenger_human_agent_tag,
        timeout=settings.collector_timeout_seconds,
    )


async def already_handled(session: AsyncSession, message_id: str) -> bool:
    """Tin này đã ghi chưa?

    Facebook **gửi lại** webhook khi ta trả về mã lỗi, nên cùng một tin đến
    nhiều lần là chuyện thường. Không chống lặp thì lịch sử trò chuyện nhân bản
    và mỗi bản lại kích một lượt gọi model — vừa sai ngữ cảnh vừa tốn tiền.
    """
    found = await session.scalar(
        select(ConversationMessage.id).where(ConversationMessage.external_id == message_id).limit(1)
    )
    return found is not None


async def conversation_for(
    session: AsyncSession, inbound: InboundMessage, *, display_name: str | None
) -> Conversation:
    """Hội thoại đang mở của `psid`; chưa có thì tạo mới.

    Thứ tự tìm có chủ đích:

    1. Hội thoại **đang mở** đã gắn đúng `psid` này.
    2. Hội thoại **đang mở** của một profile mà người vận hành vừa mở để nhắn,
       nhưng chưa có `psid` — ghép vào đó thay vì tạo thread thứ hai. Không làm
       bước này thì operator bắt đầu phiên với khách A, khách A trả lời, và câu
       trả lời rơi vào một hội thoại **khác** — họ sẽ không bao giờ thấy nó cạnh
       gợi ý của mình.
    3. Tạo mới, không profile.
    """
    existing = await session.scalar(
        select(Conversation)
        .where(Conversation.psid == inbound.psid, Conversation.status == "active")
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        if display_name and not existing.customer_label:
            existing.customer_label = display_name
        return existing

    created = Conversation(psid=inbound.psid, status="active", customer_label=display_name)
    session.add(created)
    await session.flush()
    return created


async def link_psid(session: AsyncSession, conversation_id: uuid.UUID, psid: str) -> None:
    """Gắn `psid` vào một hội thoại đã có (khi operator nhận ra đây là ai)."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is not None and not conversation.psid:
        conversation.psid = psid
        await session.flush()
