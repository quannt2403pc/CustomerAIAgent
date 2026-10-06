"""Lớp Base khai báo + các mixin dùng chung cho mọi model SQLAlchemy."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Đặt tên ràng buộc theo quy ước → Alembic autogenerate sinh migration
# ổn định, không phụ thuộc tên ngẫu nhiên do Postgres tự đặt.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Mọi cột datetime đều lưu kèm timezone — mốc 20h Asia/Ho_Chi_Minh
    # mà lưu naive là mời lỗi lệch múi giờ.
    type_annotation_map: ClassVar[dict] = {datetime: DateTime(timezone=True)}


class UuidPk:
    """Khoá chính UUID.

    Dùng UUID thay vì serial để `GET /api/profiles/{id}` không thành danh bạ
    duyệt tuần tự được — dữ liệu ở đây là PII của người thật.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class CreatedAt:
    """`created_at` do server sinh — không tin đồng hồ của client."""

    # Không đặt index=True ở đây: bảng nào cần thì tự khai báo `Index` đúng
    # chiều / đúng tổ hợp cột, tránh index trùng lặp trên mọi bảng.
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
