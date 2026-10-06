"""Nhật ký vận hành: lượt chạy job + audit log (plan.md §5.9)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UuidPk


class JobRun(UuidPk, Base):
    """Một lượt chạy của job nền (lịch 20h, phân tích profile).

    `ok` để nullable: job đang chạy thì chưa biết kết quả — NULL nói đúng điều
    đó, trong khi `false` sẽ là một lời nói sai.
    """

    __tablename__ = "job_runs"

    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    ok: Mapped[bool | None] = mapped_column(Boolean)
    summary: Mapped[dict | None] = mapped_column(JSONB)


class AuditLog(UuidPk, CreatedAt, Base):
    """Ai làm gì với cái gì.

    `meta` tuyệt đối không chứa secret — bên ghi phải lọc trước (plan.md §7.2).
    """

    __tablename__ = "audit_log"

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
