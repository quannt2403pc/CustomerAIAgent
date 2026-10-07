"""Cấu hình cổng model + credential đã mã hoá (plan.md §5.9)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UuidPk

PROVIDERS = ("antigravity", "google_api_key")
CREDENTIAL_KINDS = ("google_api_key", "fb_cookie", "page_access_token")


class LlmSettings(UuidPk, Base):
    """Cổng + model đang chọn.

    Chỉ có **một** hàng (app một người vận hành — plan.md §12.1). `provider`
    để rỗng nghĩa là *chưa chọn*: UI phải buộc người dùng chọn, không đoán hộ.
    """

    __tablename__ = "llm_settings"
    __table_args__ = (
        CheckConstraint(
            "provider = '' OR provider IN ('antigravity', 'google_api_key')",
            name="provider_known",
        ),
        CheckConstraint("temperature >= 0 AND temperature <= 2", name="temperature_range"),
    )

    provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    # Tên model KHÔNG có giá trị mặc định cứng — luật L6: danh mục lấy lúc chạy.
    model: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LlmCredential(UuidPk, CreatedAt, Base):
    """Secret người dùng cung cấp, **luôn** ở dạng Fernet ciphertext.

    `secret_enc` không bao giờ được trả ra API. Chỉ `hint` (4 ký tự cuối) được
    hiển thị, đủ để người dùng nhận ra mình đã nhập key nào (plan.md §5.1.3).
    """

    __tablename__ = "llm_credentials"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('google_api_key', 'fb_cookie', 'page_access_token')", name="kind_known"
        ),
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    secret_enc: Mapped[str] = mapped_column(String, nullable=False)
    hint: Mapped[str] = mapped_column(String(16), default="", nullable=False)
