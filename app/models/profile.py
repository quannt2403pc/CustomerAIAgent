"""Profile khách + bằng chứng thu thập được (plan.md §5.9).

Bằng chứng tách thành bảng riêng vì nó là **trụ của luật L1**: mọi khẳng định
trong output phải truy vết về một dòng trong `profile_evidence.bundle`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UuidPk

PROFILE_STATUSES = ("SUCCESS", "PARTIAL_OR_PRIVATE", "FAILED_VALIDATION", "ERROR")


class Profile(UuidPk, CreatedAt, Base):
    __tablename__ = "profiles"
    __table_args__ = (
        # Bảng Dashboard luôn sort theo thời gian giảm dần (task.md D1.4).
        Index("ix_profiles_created_at_desc", text("created_at DESC")),
    )

    facebook_url: Mapped[str] = mapped_column(Text, nullable=False)
    # `url_key` là dạng chuẩn hoá của URL (app/collectors/url.py). Unique để
    # cùng một người không bị tạo hai profile chỉ vì URL khác tham số rác.
    url_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Mọi field dưới đây đều được phép NULL — không có evidence thì để NULL,
    # KHÔNG đoán (luật L1).
    customer_name: Mapped[str | None] = mapped_column(String(255))
    visual_context: Mapped[str | None] = mapped_column(Text)
    demographics: Mapped[dict | None] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    error_note: Mapped[str | None] = mapped_column(Text)

    # Strict JSON **nguyên văn** của lần phân tích gần nhất (task.md I-39).
    #
    # Có vẻ dư thừa vì mọi field đều dựng lại được từ các bảng khác, nhưng DoD
    # D2.3 đòi `GET /api/profiles/{id}/output.json` **giống hệt** CLI. Dựng lại
    # thì điều đó chỉ đúng *chừng nào* hai đường code còn khớp nhau — và nó đã
    # không khớp ngay ở ca đầu tiên thử: hook 20h không có `run_id`, nên lượt
    # chạy có hook bị loại vì kiểm duyệt sẽ "dựng lại" được hook **cũ** của lượt
    # trước, biến một output trung thực (`evening_hook_message: null`) thành một
    # output có nội dung chưa bao giờ được duyệt. Lưu nguyên văn thì đúng **theo
    # cấu trúc**, không phải theo lời hứa.
    last_output: Mapped[dict | None] = mapped_column(JSONB)

    evidence: Mapped[list[ProfileEvidence]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class ProfileEvidence(UuidPk, CreatedAt, Base):
    __tablename__ = "profile_evidence"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    # Toàn bộ `EvidenceBundle` (plan.md §5.2) — fields/images/attempts/blocked_reason.
    bundle: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collector_layers: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    screenshot_path: Mapped[str | None] = mapped_column(Text)

    profile: Mapped[Profile] = relationship(back_populates="evidence")
