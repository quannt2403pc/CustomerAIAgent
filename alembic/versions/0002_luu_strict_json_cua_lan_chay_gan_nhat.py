"""Lưu strict JSON của lần phân tích gần nhất vào `profiles.last_output`.

Vì sao cần (task.md I-39): DoD D2.3 đòi `GET /api/profiles/{id}/output.json` có
nội dung **giống hệt** CLI. Dựng lại từ các bảng con thì chỉ đúng chừng nào hai
đường code còn khớp — và nó đã lệch ngay ở ca đầu: `evening_hooks` không có
`run_id`, nên lượt chạy mà hook bị kiểm duyệt loại sẽ dựng lại được hook **cũ**
của lượt trước, biến `evening_hook_message: null` trung thực thành nội dung chưa
bao giờ được duyệt (vi phạm tinh thần L2).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("last_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("profiles", "last_output")
