"""Phiên hội thoại nhiều lượt với một khách (task.md X.3).

Khác `rapport_runs`/`rapport_messages` ở chỗ nào: kia là **một chuỗi 10 tin sinh
sẵn** theo đúng đề bài, sinh một lần rồi thôi. Ở đây là một **cuộc trò chuyện
thật đang diễn ra**: người vận hành gửi một tin, khách trả lời, và lượt gợi ý kế
tiếp phải đọc được phản hồi đó.

Hai bảng tách riêng có chủ đích:

- `conversation_messages` — những gì **đã thật sự xảy ra** (operator đã gửi,
  khách đã trả lời). Đây là lịch sử, không sửa.
- `conversation_suggestions` — những gì AI **đề xuất**. Phần lớn sẽ không bao
  giờ được gửi. Trộn chung một bảng thì không còn phân biệt được "đã gửi" với
  "mới chỉ gợi ý" — mà đó đúng là ranh giới luật L3 bảo vệ.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UuidPk

CONVERSATION_STATUSES = ("active", "closed")

#: `operator` = người vận hành (chính bạn). `customer` = khách trả lời.
#: Không có vai nào tên `system`/`bot`: mọi tin gửi đi đều do con người bấm gửi.
MESSAGE_ROLES = ("operator", "customer")


class Conversation(UuidPk, CreatedAt, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="status_known"),
        Index("ix_conversations_profile_created", "profile_id", "created_at"),
    )

    # **Nullable** có chủ đích (task.md X.6): tin đến qua webhook có thể từ một
    # người **chưa hề được phân tích** — họ nhắn Page trước. Bắt buộc phải có
    # profile thì hoặc ta chặn tin thật, hoặc ta bịa ra một profile rỗng.
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE")
    )
    #: Page-Scoped ID của người đang nói chuyện. Chỉ có khi họ đã nhắn Page —
    #: đó cũng chính là điều kiện để được phép gửi tin cho họ.
    psid: Mapped[str | None] = mapped_column(String(64), index=True)
    #: Tên hiển thị lấy **thật** từ Graph API. `None` khi chưa lấy được —
    #: không bao giờ điền giá trị suy đoán vào đây (luật L1).
    customer_label: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    closed_at: Mapped[datetime | None] = mapped_column()

    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.seq",
    )
    suggestions: Mapped[list[ConversationSuggestion]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationSuggestion.seq",
    )


class ConversationMessage(UuidPk, CreatedAt, Base):
    """Một lượt **đã xảy ra thật** trong cuộc trò chuyện."""

    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint("role IN ('operator', 'customer')", name="role_known"),
        # `seq` liên tục trong một hội thoại — thứ tự là ngữ cảnh, không được lộn.
        Index("ix_conversation_messages_seq", "conversation_id", "seq", unique=True),
        # `unique` để chống lặp là một **ràng buộc**, không phải một lần kiểm
        # trong code: hai webhook đến song song đều vượt qua được câu SELECT.
        Index("ix_conversation_messages_external", "external_id", unique=True),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    #: ID tin của Facebook (`mid`). Hai vai trò, cùng một cột:
    #:
    #: - tin **đến**: khoá chống xử lý lặp. Facebook gửi lại webhook khi ta trả
    #:   mã lỗi, nên cùng một tin có thể đến nhiều lần.
    #: - tin **đi**: bằng chứng tin đã thật sự đi qua Send API, phân biệt "đã
    #:   gửi" với "tưởng đã gửi".
    #:
    #: `None` cho tin ghi tay (đường thủ công, chưa kết nối Page).
    external_id: Mapped[str | None] = mapped_column(String(128))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ConversationSuggestion(UuidPk, CreatedAt, Base):
    """Một tin **AI đề xuất**. Chỉ thành tin thật khi người vận hành chọn và gửi."""

    __tablename__ = "conversation_suggestions"
    __table_args__ = (
        Index("ix_conversation_suggestions_round", "conversation_id", "round", "seq", unique=True),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    #: Lượt gợi ý thứ mấy (tăng sau mỗi lần khách trả lời).
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Người vận hành đã chọn gợi ý này để gửi hay chưa.
    chosen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Báo cáo kiểm duyệt của lượt sinh — truy vết cho L1/L2.
    report: Mapped[dict | None] = mapped_column(JSONB)

    conversation: Mapped[Conversation] = relationship(back_populates="suggestions")
