"""`/api/outbox/*` — nháp hook 20h chờ người vận hành **tự gửi tay**.

**Luật thép L3 định hình toàn bộ router này.** Không có endpoint nào gửi tin.
`mark-sent` không gửi gì cả: nó ghi lại việc **con người đã tự gửi** ở nơi khác.
Tên `mark-sent` (đánh dấu đã gửi) chứ không phải `send` là có chủ đích — một
endpoint tên `send` là một lời mời hiện thực việc gửi.

Trạng thái: `draft` → `sent_manually` (người vận hành đã gửi) hoặc `discarded`
(bỏ, không gửi). Không có trạng thái nào mang nghĩa "hệ thống đã gửi".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models import EveningHook, OutboxItem, Profile
from app.routers.deps import SessionDep
from app.scheduler import runner as scheduler_runner
from app.schemas.api import ActionResultOut, OutboxItemOut, OutboxListOut
from app.services import audit

log = get_logger(__name__)

router = APIRouter(prefix="/api/outbox", tags=["outbox"])

# Trạng thái mà người vận hành còn phải làm gì đó.
OPEN_STATUSES = ("draft", "approved")


@router.get("", response_model=OutboxListOut)
async def list_outbox(
    session: SessionDep,
    status: str | None = Query(
        default=None, description="draft | approved | sent_manually | discarded"
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> OutboxListOut:
    """Nháp hook 20h. Mặc định: tất cả, mới nhất trước."""
    if status is not None and status not in ("draft", "approved", "sent_manually", "discarded"):
        raise NotFoundError(f"Trạng thái `{status}` không tồn tại.")

    base = (
        select(OutboxItem, EveningHook.message, Profile.customer_name, Profile.facebook_url)
        .join(Profile, Profile.id == OutboxItem.profile_id)
        .outerjoin(EveningHook, EveningHook.id == OutboxItem.hook_id)
    )
    count_stmt = select(func.count()).select_from(OutboxItem)
    if status:
        base = base.where(OutboxItem.status == status)
        count_stmt = count_stmt.where(OutboxItem.status == status)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            base.order_by(OutboxItem.scheduled_for.desc()).limit(limit).offset(offset)
        )
    ).all()

    return OutboxListOut(
        items=[
            OutboxItemOut(
                id=str(item.id),
                profile_id=str(item.profile_id),
                customer_name=name,
                facebook_url=url,
                message=message,
                status=item.status,
                scheduled_for=item.scheduled_for,
                acted_at=item.acted_at,
                created_at=item.created_at,
            )
            for item, message, name, url in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{item_id}/mark-sent", response_model=ActionResultOut)
async def mark_sent(item_id: uuid.UUID, session: SessionDep) -> ActionResultOut:
    """Người vận hành đã **tự** gửi tin ở Messenger rồi bấm nút này.

    Endpoint này **không gửi gì** (luật L3). Nó chỉ ghi lại một việc đã xảy ra
    bên ngoài hệ thống, để nháp đó không hiện lại ở danh sách chờ.
    """
    item = await _get_open_item(session, item_id)
    item.status = "sent_manually"
    item.acted_at = datetime.now(UTC)
    await audit.record(session, "outbox.mark_sent", target=str(item_id))
    return ActionResultOut(message="Đã đánh dấu là bạn tự gửi tay.")


@router.post("/{item_id}/discard", response_model=ActionResultOut)
async def discard(item_id: uuid.UUID, session: SessionDep) -> ActionResultOut:
    """Bỏ nháp này — không gửi."""
    item = await _get_open_item(session, item_id)
    item.status = "discarded"
    item.acted_at = datetime.now(UTC)
    await audit.record(session, "outbox.discard", target=str(item_id))
    return ActionResultOut(message="Đã bỏ nháp này.")


@router.post("/run-now", response_model=ActionResultOut)
async def run_now(session: SessionDep) -> ActionResultOut:
    """Chạy lượt 20h ngay, không chờ cron.

    Có hai lý do thật: kiểm chứng lịch mà không phải chờ tới 20h (task.md D2.4),
    và chạy lại khi lượt tối hôm trước bị bỏ vì máy tắt. Đi **đúng một đường
    code** với lượt theo lịch — một đường "chạy tay" riêng là một đường chưa ai kiểm.
    """
    await audit.record(session, "outbox.run_now", target="evening_cadence_20pm")
    await session.commit()
    await scheduler_runner.trigger_now()
    return ActionResultOut(message="Đã chạy lượt sinh hook 20h. Xem danh sách nháp bên dưới.")


async def _get_open_item(session: AsyncSession, item_id: uuid.UUID) -> OutboxItem:
    item = await session.get(OutboxItem, item_id)
    if item is None:
        raise NotFoundError("Không tìm thấy nháp này.")
    if item.status not in OPEN_STATUSES:
        # Bấm hai lần không được âm thầm ghi đè `acted_at` — mốc thời gian đó là
        # bằng chứng vận hành.
        raise ConflictError(f"Nháp này đã ở trạng thái `{item.status}`, không thể đổi nữa.")
    return item
