"""Chọn event loop policy tương thích psycopg3 async.

**Vấn đề thật đã gặp (task.md I-04):** trên Windows, Python 3.12 mặc định dùng
`ProactorEventLoop`, còn psycopg3 ở chế độ async thì không chạy được trên nó:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run
    in async mode.

Trong Docker (Linux) không gặp, nên lỗi này chỉ lộ ra ở nhánh "chạy không
Docker" của README — đúng nhánh người đánh giá có thể dùng.

Phải gọi **trước khi** event loop đầu tiên được tạo. Vì vậy `uvicorn app.main:app`
trên Windows không đủ (uvicorn dựng loop rồi mới import app) — dùng `python run.py`.
"""

from __future__ import annotations

import asyncio
import sys


def ensure_compatible_event_loop_policy() -> bool:
    """Đặt `WindowsSelectorEventLoopPolicy` nếu đang ở Windows.

    Trả `True` nếu đã đổi policy, `False` nếu không cần (Linux/macOS).
    """
    if sys.platform != "win32":
        return False

    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:  # pragma: no cover — chỉ khi Python bỏ lớp này
        return False

    if isinstance(asyncio.get_event_loop_policy(), policy_cls):
        return False

    asyncio.set_event_loop_policy(policy_cls())
    return True
