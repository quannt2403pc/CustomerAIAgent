"""Lượt sinh nội dung: chuỗi tin nhắn tâm sự + hook 20h (plan.md §5.9)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UuidPk

SALES_CHECKS = ("ZERO_SALES_CONFIRMED", "FAILED")


class RapportRun(UuidPk, CreatedAt, Base):
    """Một lần gọi model để sinh nội dung — lưu cả bằng chứng kiểm duyệt."""

    __tablename__ = "rapport_runs"
    __table_args__ = (
        CheckConstraint(
            "sales_check IN ('ZERO_SALES_CONFIRMED', 'FAILED')", name="sales_check_known"
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    # Ghi lại cổng + model **đã thật sự dùng**: đổi cổng giữa hai lần chạy mà
    # không ghi lại thì sau này không giải thích được chênh lệch chất lượng.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    empathy_angle: Mapped[str | None] = mapped_column(Text)
    sales_check: Mapped[str] = mapped_column(String(32), nullable=False)
    # Báo cáo của GroundingValidator: ungrounded_claims[], số lượt sinh lại…
    grounding_report: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)

    messages: Mapped[list[RapportMessage]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RapportMessage.seq",
    )


class RapportMessage(UuidPk, Base):
    __tablename__ = "rapport_messages"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="run_seq_unique"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("rapport_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[RapportRun] = relationship(back_populates="messages")


class EveningHook(UuidPk, Base):
    """Câu chuyện mồi 20h.

    Giữ lịch sử thay vì ghi đè: job 20h phải so với 7 hook gần nhất để không
    lặp ý (plan.md §5.5).
    """

    __tablename__ = "evening_hooks"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )
    # Evidence nào đã dùng để sinh hook này — truy vết cho luật L1.
    based_on: Mapped[dict | None] = mapped_column(JSONB)
