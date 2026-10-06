"""Collector L4 — người vận hành dán nội dung tay (plan.md §5.2).

Đường cuối cùng và **đáng tin nhất**: con người mở trang, đọc, rồi dán lại
những gì họ thật sự nhìn thấy. Vì vậy `confidence = 1.0`.

Đo thật 2026-10-06 cho thấy L2 `mbasic` là login wall và L1 chỉ cho tên +
avatar (task.md I-14), nên lớp này không phải "đường dự phòng cho vui" — nó là
cách chính để có bio/bài viết, và là cách duy nhất chạy được pipeline **không
cần mạng** (`python main.py --profile-file …`).

Hai dạng đầu vào:

1. **Có nhãn** — chính xác nhất, người dùng chỉ rõ đâu là gì:

       Tên: Nguyễn Thị Lan
       Tiểu sử: Mẹ hai bé, bán hàng online
       Bài viết: Hôm nay con bé đi học về kể...

2. **Văn bản thô** — dán cả đoạn. Toàn bộ vào `post_text`; **không** cố đoán
   đâu là tên (đoán sai là bịa — luật L1).
"""

from __future__ import annotations

import hashlib
import pathlib
import re

from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceImage
from app.core.config import get_settings
from app.core.errors import CollectorError
from app.core.logging import get_logger

log = get_logger(__name__)

LAYER = "manual"
SOURCE = "manual_paste"

# Nhãn → khoá field. Người vận hành là người Việt nên nhận cả hai ngôn ngữ.
_LABEL_MAP: dict[str, str] = {
    "tên": "customer_name",
    "ten": "customer_name",
    "họ tên": "customer_name",
    "name": "customer_name",
    "tiểu sử": "bio",
    "tieu su": "bio",
    "giới thiệu": "bio",
    "bio": "bio",
    "about": "bio",
    "bài viết": "post_text",
    "bai viet": "post_text",
    "post": "post_text",
    "posts": "post_text",
    "nơi ở": "location",
    "noi o": "location",
    "sống tại": "location",
    "location": "location",
    "công việc": "work",
    "cong viec": "work",
    "làm việc tại": "work",
    "work": "work",
    "học vấn": "education",
    "hoc van": "education",
    "education": "education",
    "quan hệ": "relationship",
    "tình trạng": "relationship",
    "relationship": "relationship",
}

_LABEL_LINE = re.compile(r"^\s*([^:\n]{1,24})\s*:\s*(.+)$")

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def collect_from_text(text: str, bundle: EvidenceBundle) -> EvidenceBundle:
    """Nạp nội dung người vận hành dán vào `bundle`."""
    raw = (text or "").strip()
    if not raw:
        bundle.add_attempt(
            CollectAttempt(layer=LAYER, ok=False, note="người vận hành chưa dán nội dung nào")
        )
        return bundle

    labelled = _parse_labelled(raw)
    found_anything = False

    if labelled:
        for key, value in labelled.items():
            found_anything |= bundle.add_field(
                key,
                value,
                source=SOURCE,
                # Evidence là **đúng dòng người dùng dán**, không phải diễn giải.
                evidence=f"người vận hành dán: {key} = {value}",
                confidence=1.0,
            )

    # Phần không có nhãn (hoặc toàn bộ nếu không có nhãn nào) → post_text.
    leftover = _unlabelled_part(raw) if labelled else raw
    if leftover and len(leftover) >= 10:
        found_anything |= bundle.add_field(
            "post_text",
            leftover,
            source=SOURCE,
            evidence=f"người vận hành dán nguyên văn:\n{leftover}",
            confidence=1.0,
        )

    bundle.add_attempt(
        CollectAttempt(
            layer=LAYER,
            ok=found_anything,
            note=(
                f"nhận {len(labelled)} field có nhãn"
                if labelled
                else "nhận văn bản thô, không đoán tên (luật L1)"
            ),
        )
    )
    return bundle


def save_uploaded_avatar(
    data: bytes, bundle: EvidenceBundle, *, mime_type: str, upload_dir: str | None = None
) -> EvidenceImage:
    """Lưu ảnh người vận hành tải lên, đặt tên bằng sha256.

    Đặt tên bằng sha256 chứ không giữ tên gốc: tên file do người ngoài đặt là
    một đường path-traversal, và băm thì tự khử trùng lặp (plan.md §7.4).
    """
    if mime_type not in ALLOWED_IMAGE_MIME:
        raise CollectorError(
            f"Định dạng ảnh `{mime_type}` không được nhận. Chỉ nhận JPEG, PNG, WebP."
        )
    if not data:
        raise CollectorError("Tệp ảnh rỗng.")
    if len(data) > MAX_IMAGE_BYTES:
        raise CollectorError(f"Ảnh lớn hơn giới hạn {MAX_IMAGE_BYTES // (1024 * 1024)}MB.")

    digest = hashlib.sha256(data).hexdigest()
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime_type]

    target_dir = pathlib.Path(upload_dir or get_settings().upload_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{digest}{suffix}"
    path.write_bytes(data)

    image = EvidenceImage(
        role="avatar", url=f"manual://{digest}", local_path=str(path), sha256=digest
    )
    bundle.add_image(image)
    bundle.add_attempt(
        CollectAttempt(layer=LAYER, ok=True, note="người vận hành tải ảnh đại diện lên")
    )
    return image


def _parse_labelled(raw: str) -> dict[str, str]:
    """Bóc các dòng `Nhãn: giá trị`. Nhãn lạ thì bỏ qua, không đoán."""
    found: dict[str, str] = {}
    for line in raw.splitlines():
        match = _LABEL_LINE.match(line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        key = _LABEL_MAP.get(label)
        if key is None:
            continue
        value = match.group(2).strip()
        if not value:
            continue
        # Nhiều dòng cùng nhãn (vd nhiều "Bài viết:") → nối lại, không ghi đè.
        found[key] = f"{found[key]}\n{value}" if key in found else value
    return found


def _unlabelled_part(raw: str) -> str:
    """Các dòng **không** khớp nhãn nào — vẫn là nội dung thật, đừng bỏ."""
    kept = [
        line
        for line in raw.splitlines()
        if not ((match := _LABEL_LINE.match(line)) and match.group(1).strip().lower() in _LABEL_MAP)
    ]
    return "\n".join(kept).strip()
