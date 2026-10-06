"""Khởi động API — dùng cho nhánh "chạy không Docker".

Tồn tại vì một lý do cụ thể: trên Windows phải đặt `WindowsSelectorEventLoopPolicy`
**trước khi** event loop đầu tiên được tạo, nhưng `uvicorn app.main:app` dựng
loop rồi mới import `app.main` — lúc đó đã muộn (xem app/core/eventloop.py và
task.md I-04).

    python run.py                 # tương đương uvicorn app.main:app --port 8000
    python run.py --reload        # dev
"""

from __future__ import annotations

import argparse

from app.core.eventloop import ensure_compatible_event_loop_policy


def main() -> None:
    ensure_compatible_event_loop_policy()

    parser = argparse.ArgumentParser(description="Chạy API Cỗ máy AI Profiler & Rapport")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="tự nạp lại khi sửa code")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # Tự cấu hình logging ở app/core/logging.py (ra stderr, che secret).
        log_config=None,
    )


if __name__ == "__main__":
    main()
