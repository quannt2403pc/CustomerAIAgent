"""Kết nối Facebook Page: PSID của hội thoại + nới `profile_id` thành nullable.

Revision ID: 0004
Revises: 0003

Viết **tay**, không `--autogenerate` (task.md I-48): autogenerate không biết bảng
`apscheduler_jobs` là do APScheduler tự tạo lúc chạy, nên nó sinh
`op.drop_table('apscheduler_jobs')` — chạy lên là **xoá luôn lịch 20h** đang lưu.

Hai thay đổi, đều phục vụ task.md X.6:

1. `conversations.psid` — Page-Scoped ID của người đang nói chuyện. Chỉ Facebook
   cấp, và chỉ khi họ đã chủ động nhắn Page. Có PSID = được phép gửi; không có =
   không được. Nó vừa là địa chỉ gửi, vừa là **bằng chứng đồng ý**.
2. `conversations.profile_id` → nullable. Tin đến qua webhook có thể từ người
   chưa hề được phân tích. Giữ `NOT NULL` thì chỉ còn hai lối: chặn tin thật, hay
   bịa một profile rỗng — cái sau vi phạm L1.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("psid", sa.String(length=64), nullable=True))
    # Tên hiển thị **lấy thật** từ Graph API (`GET /{psid}?fields=name`), không
    # suy đoán. Thiếu nó thì hội thoại đến từ webhook hiện ra vô danh.
    op.add_column(
        "conversations", sa.Column("customer_label", sa.String(length=120), nullable=True)
    )
    op.create_index("ix_conversations_psid", "conversations", ["psid"])
    op.alter_column("conversations", "profile_id", existing_type=sa.UUID(), nullable=True)

    op.add_column(
        "conversation_messages", sa.Column("external_id", sa.String(length=128), nullable=True)
    )
    # UNIQUE (không chỉ INDEX): chống lặp webhook phải là ràng buộc ở DB. Hai
    # webhook cùng tin đến song song đều vượt qua được một câu SELECT kiểm trước.
    # Postgres cho phép nhiều NULL trong cột UNIQUE, nên tin ghi tay không vướng.
    op.create_index(
        "ix_conversation_messages_external", "conversation_messages", ["external_id"], unique=True
    )

    # Thêm 'page_access_token' vào danh mục `kind` của `credentials`.
    # CHECK constraint không ALTER được — phải drop rồi tạo lại.
    op.drop_constraint(
        # `op.f()` = "tên này ĐÃ là tên cuối, đừng áp quy ước nữa". Thiếu nó,
        # NAMING_CONVENTION trong app/db/base.py bọc thêm một lần tiền tố và
        # Alembic đi tìm `ck_llm_credentials_ck_llm_credentials_kind_known`
        # (task.md I-53).
        op.f("ck_llm_credentials_kind_known"),
        "llm_credentials",
        type_="check",
    )
    op.create_check_constraint(
        "kind_known",
        "llm_credentials",
        "kind IN ('google_api_key', 'fb_cookie', 'page_access_token')",
    )


def downgrade() -> None:
    op.drop_constraint(
        # `op.f()` = "tên này ĐÃ là tên cuối, đừng áp quy ước nữa". Thiếu nó,
        # NAMING_CONVENTION trong app/db/base.py bọc thêm một lần tiền tố và
        # Alembic đi tìm `ck_llm_credentials_ck_llm_credentials_kind_known`
        # (task.md I-53).
        op.f("ck_llm_credentials_kind_known"),
        "llm_credentials",
        type_="check",
    )
    # Hàng 'page_access_token' phải đi trước, nếu không CHECK mới sẽ bị vi phạm.
    op.execute("DELETE FROM llm_credentials WHERE kind = 'page_access_token'")
    op.create_check_constraint(
        "kind_known", "llm_credentials", "kind IN ('google_api_key', 'fb_cookie')"
    )

    # Hội thoại không có profile không biểu diễn được ở lược đồ cũ → bỏ hẳn,
    # chứ không gán bừa cho một profile nào đó.
    op.execute("DELETE FROM conversations WHERE profile_id IS NULL")
    op.alter_column("conversations", "profile_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_conversation_messages_external", table_name="conversation_messages")
    op.drop_column("conversation_messages", "external_id")
    op.drop_column("conversations", "customer_label")
    op.drop_index("ix_conversations_psid", table_name="conversations")
    op.drop_column("conversations", "psid")
