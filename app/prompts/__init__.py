"""Nạp prompt từ file văn bản.

Prompt nằm ở file riêng, **không** nhúng chuỗi dài trong code (task.md D1.14):
chúng là nội dung cần đọc/sửa/so sánh phiên bản như văn bản, không phải như code.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache

PROMPT_DIR = pathlib.Path(__file__).parent


@lru_cache(maxsize=32)
def load(name: str) -> str:
    """Đọc `app/prompts/<name>.txt`. Thiếu file → lỗi nêu rõ tên mong đợi."""
    path = PROMPT_DIR / f"{name}.txt"
    if not path.is_file():
        available = sorted(p.stem for p in PROMPT_DIR.glob("*.txt"))
        raise FileNotFoundError(
            f"Không có prompt `{name}` tại {path}. Hiện có: {', '.join(available) or '(trống)'}"
        )
    return path.read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    """Nạp prompt rồi thay các chỗ giữ `{ten_bien}`.

    Dùng `str.format_map` với dict thiếu-thì-nổ: biến chưa truyền phải báo lỗi
    ngay, chứ không để chuỗi `{khach_ten}` lọt vào prompt gửi model.
    """
    template = load(name)
    try:
        return template.format(**values)
    except KeyError as exc:
        raise KeyError(f"Prompt `{name}` cần biến {exc} nhưng không được truyền") from exc
