"""Đọc JSON do model trả về (plan.md §5.3–5.4).

Dù đã đặt `responseMimeType: application/json`, model vẫn có lúc bọc kết quả
trong khối ```json hoặc thêm một câu dẫn. Module này gỡ những thứ đó ra.

Nguyên tắc: **không cố vá JSON hỏng**. Vá bằng regex nghĩa là đoán ý model, và
một dấu phẩy sai có thể đổi hẳn nghĩa của dữ liệu về người thật. Hỏng thì báo
hỏng để vòng sinh lại chạy (D1.17).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.errors import GatewayBadResponse

# ```json … ``` hoặc ``` … ```
_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_object(text: str) -> dict[str, Any]:
    """Trả về object JSON từ phản hồi của model. Hỏng → `GatewayBadResponse`."""
    candidate = _strip_fence(text)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        # Thử lần hai: cắt từ `{` đầu tiên tới `}` cuối cùng. Chỉ *cắt*, không
        # sửa nội dung bên trong.
        sliced = _slice_outermost_object(candidate)
        if sliced is None:
            raise GatewayBadResponse(
                "Model không trả về JSON đọc được.",
                detail=f"JSONDecodeError: {exc.msg} | đầu phản hồi: {candidate[:200]}",
            ) from exc
        try:
            value = json.loads(sliced)
        except json.JSONDecodeError as exc2:
            raise GatewayBadResponse(
                "Model không trả về JSON đọc được.",
                detail=f"JSONDecodeError sau khi cắt: {exc2.msg} | {sliced[:200]}",
            ) from exc2

    if not isinstance(value, dict):
        raise GatewayBadResponse(
            "Model trả về JSON nhưng không phải object.",
            detail=f"kiểu nhận được: {type(value).__name__}",
        )
    return value


def parse_string_list(text: str, *, key: str) -> list[str]:
    """Đọc `{"<key>": ["…", "…"]}` → list chuỗi đã làm sạch.

    Nhận cả trường hợp model trả thẳng một mảng thay vì object bọc ngoài — đó
    là lệch *hình dạng*, không phải lệch *nội dung*, nên không cần sinh lại.
    """
    stripped = _strip_fence(text)
    if stripped.lstrip().startswith("["):
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, list):
            return _clean_items(raw, key=key)

    body = parse_object(text)
    raw = body.get(key)
    if not isinstance(raw, list):
        raise GatewayBadResponse(
            f"Model không trả về mảng `{key}`.",
            detail=f"các khoá nhận được: {sorted(body)}",
        )
    return _clean_items(raw, key=key)


def _clean_items(raw: list[Any], *, key: str) -> list[str]:
    items = [" ".join(str(item).split()).strip() for item in raw if isinstance(item, str)]
    items = [item for item in items if item]
    if not items:
        raise GatewayBadResponse(
            f"Mảng `{key}` không có phần tử chuỗi nào dùng được.",
            detail=f"{len(raw)} phần tử thô",
        )
    return items


def _strip_fence(text: str) -> str:
    match = _FENCE.match(text or "")
    return match.group(1) if match else (text or "").strip()


def _slice_outermost_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
