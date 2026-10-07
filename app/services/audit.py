"""Ghi `audit_log` — ai làm gì với cái gì (plan.md §5.9, §7.2).

Quy tắc duy nhất nhưng tuyệt đối: **`meta` không được chứa secret.** Bảng này
đọc được bằng SQL và sẽ lên trang Nhật ký của UI; một API key lọt vào đây là lọt
vĩnh viễn. Vì vậy `record()` lọc theo **danh sách khoá cho phép** chứ không lọc
theo danh sách cấm — khoá mới thêm sau này sẽ bị loại theo mặc định, hướng an
toàn hơn là hướng tiện.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import AuditLog

log = get_logger(__name__)

# Chỉ những khoá này được phép vào `meta`. `hint` được phép vì nó đã là 4 ký tự
# cuối có chủ đích hiển thị cho người dùng; `api_key`, `code`, `state`, `cookie`
# thì không nằm trong danh sách nên tự động bị loại.
ALLOWED_META_KEYS = frozenset(
    {
        "provider",
        "model",
        "status",
        "hint",
        "count",
        "layers",
        "url_key",
        "job_name",
        "reason",
        "latency_ms",
        "refresh",
        "outbox_id",
    }
)


def safe_meta(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Giữ lại đúng những khoá trong danh sách cho phép."""
    if not raw:
        return {}
    return {k: v for k, v in raw.items() if k in ALLOWED_META_KEYS}


async def record(
    session: AsyncSession,
    action: str,
    *,
    target: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Thêm một dòng audit. Không `flush` — để transaction của request lo."""
    session.add(AuditLog(action=action, target=target, meta=safe_meta(meta) or None))
    log.info("audit: %s target=%s", action, target or "-")
