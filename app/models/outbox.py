"""Outbox — nháp chờ người vận hành tự gửi tay.

Luật thép L3: hệ thống **không** gửi tin cho người thật. Bảng này cố ý không
có trạng thái nào mang nghĩa "đã gửi tự động"; `sent_manually` chỉ do con người
bấm sau khi họ tự gửi.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UuidPk

OUTBOX_STATUSES = ("draft", "approved", "sent_manually", "discarded")


class OutboxItem(UuidPk, CreatedAt, Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'sent_manually', 'discarded')",
            name="status_known",
        ),
        # Trang Outbox luôn truy vấn "nháp đến hạn" → index đúng cặp cột đó.
        Index("ix_outbox_status_scheduled_for", "status", "scheduled_for"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    hook_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("evening_hooks.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    scheduled_for: Mapped[datetime] = mapped_column(nullable=False)
    acted_at: Mapped[datetime | None] = mapped_column()
