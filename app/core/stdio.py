"""Ép stdout/stderr sang UTF-8 trước khi in bất cứ thứ gì.

**Vấn đề thật đã gặp (task.md I-61):** trên Windows, console mặc định dùng
`cp1252`. Mọi output của hệ thống này là tiếng Việt, nên lệnh đơn giản nhất
cũng nổ:

    python main.py --help
    UnicodeEncodeError: 'charmap' codec can't encode character '\\u1ea1'

Nghiêm trọng hơn `--help` nhiều: chính **đường ra JSON** cũng nổ ở
`sys.stdout.write`, tức hợp đồng cốt lõi của CLI — *"mọi nhánh đều in JSON hợp
lệ"* — bị phá trên đúng nền tảng dự án đang được phát triển.

Trong Docker (Linux, UTF-8 mặc định) không gặp, nên lỗi chỉ lộ ở nhánh "chạy
không Docker" của README — đúng nhánh người đánh giá có thể dùng. Cùng một kiểu
bẫy với `ensure_compatible_event_loop_policy` (I-04): môi trường chuẩn che mất
lỗi của môi trường thật.

Phải gọi **trước** mọi lần ghi ra stdout/stderr, nếu không dòng đầu tiên đã nổ
rồi mới tới lượt hàm này chạy.
"""

from __future__ import annotations

import sys


def force_utf8_stdio() -> None:
    """Đặt stdout/stderr về UTF-8. Không làm gì nếu chúng đã là UTF-8.

    Dùng `errors="replace"` cho **stderr**: log hỏng vài ký tự vẫn tốt hơn là
    làm sập cả tiến trình chỉ vì một dòng log. Nhưng **stdout giữ `strict`** —
    stdout là JSON nộp bài, và một ký tự bị thay bằng `?` ở đó là dữ liệu sai
    đi âm thầm, tệ hơn hẳn một lỗi nổ ra rõ ràng.
    """
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "replace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # Stream đã bị thay bằng thứ khác (test capture, pipe tuỳ biến).
            # Không ép — chủ sở hữu stream đó biết rõ hơn ta.
            continue
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
            continue
        reconfigure(encoding="utf-8", errors=errors)
