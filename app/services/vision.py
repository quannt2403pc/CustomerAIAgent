"""Bước vision — mô tả ảnh đại diện (plan.md §5.3).

Trả về `VisionResult` thay vì raise: bước này **được phép thất bại**.
`visual_context = None` là một câu trả lời hợp lệ và trung thực; bịa ra mô tả
cho một ảnh không đọc được là vi phạm luật L1 ở chỗ dễ lọt nhất.

Ba lý do khiến bước này trả `None`, và cả ba phải phân biệt được trong
`error_note` vì cách xử lý của người vận hành khác nhau:

1. Không có ảnh / không tải được → thử lớp dán tay.
2. Model đang chọn **không đọc được ảnh** → chọn model khác.
3. Model đọc nhưng nói "không nhìn rõ" → đó là sự thật về ảnh, không phải lỗi.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.collectors.avatar import NormalizedImage
from app.core.errors import GatewayError
from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.llm.catalog import ModelCatalog, get_catalog
from app.prompts import render as render_prompt

log = get_logger(__name__)

MAX_DESCRIPTION_CHARS = 400

# Mô tả chỉ cần ~40 từ (≈60 token), nhưng hạn mức phải rộng hơn NHIỀU.
#
# Đo thật 2026-10-06 (task.md I-16): với Gemini 3.x, **thinking token tính vào
# `maxOutputTokens`**. `gemini-3-flash-preview` với cap=256 dùng ~244 token để
# suy nghĩ, chỉ còn 8 token cho câu trả lời → `finishReason=MAX_TOKENS`, mô tả
# bị cắt giữa câu. Cùng prompt với cap=1024 → `STOP`, câu hoàn chỉnh.
VISION_MAX_OUTPUT_TOKENS = 1024

# Model nói thẳng là không nhìn rõ — giữ nguyên sự thật đó, không coi là lỗi.
_UNCLEAR_MARKERS = (
    "không nhìn rõ",
    "không rõ",
    "không thể xác định",
    "không xác định được",
    "cannot determine",
    "unclear",
)


@dataclass(frozen=True)
class VisionResult:
    """Kết quả bước vision. `description=None` nghĩa là **không có mô tả**."""

    description: str | None
    note: str = ""
    model: str = ""
    #: Số ảnh thật sự đã gửi lên model — truy vết cho `visual_context`.
    image_count: int = 0
    latency_ms: int | None = None
    usage: dict[str, int] | None = None

    @property
    def ok(self) -> bool:
        return self.description is not None


async def describe_avatar(
    avatar: NormalizedImage | None,
    gateway: LLMGateway,
    *,
    model: str,
    temperature: float = 0.4,
    catalog: ModelCatalog | None = None,
    public_photos: list[NormalizedImage] | None = None,
) -> VisionResult:
    """Mô tả ảnh đại diện **và** các ảnh công khai gần nhất (task X.1).

    Đề bài §1 nêu đích danh "ảnh đại diện (Avatar) **hoặc hình ảnh công khai gần
    nhất**". Gộp chúng vào **một** lần gọi thay vì mô tả từng ảnh rồi nối lại:
    model nhìn cả loạt mới nói được bối cảnh chung, còn nối ba mô tả rời sẽ ra
    một đoạn lặp và rời rạc.

    Không raise — mọi nhánh thất bại thành `note`.
    """
    images = [image for image in [avatar, *(public_photos or [])] if image is not None]
    if not images:
        return VisionResult(None, note="Không tải được ảnh đại diện nên không có mô tả hình ảnh.")

    catalog = catalog or get_catalog()

    # Hỏi danh mục **thật** xem model có đọc được ảnh không (luật L6).
    try:
        supports_vision = await catalog.supports_vision(gateway, model)
    except GatewayError as exc:
        return VisionResult(None, note=f"Không kiểm tra được năng lực của model: {exc.message}")

    if supports_vision is False:
        # Biết chắc là không → đừng tốn một lần gọi model để nhận lỗi.
        return VisionResult(
            None,
            note=(
                f"Model `{model}` không đọc được ảnh nên visual_context để trống. "
                "Hãy chọn một model có nhãn “đọc được ảnh” nếu cần mô tả hình ảnh."
            ),
            model=model,
        )
    if supports_vision is None:
        # Chưa biết (cổng Google API Key không khai báo cờ vision — task.md I-06).
        # Cứ thử: nếu model không đọc được ảnh, lỗi sẽ nói rõ.
        log.info("Danh mục không khai báo năng lực vision của model đang chọn — vẫn thử gọi")

    parts = [wire.image_part(image.data, mime_type=image.mime_type) for image in images]
    parts.append(
        wire.text_part(
            "Mô tả bối cảnh chung của loạt ảnh này."
            if len(images) > 1
            else "Mô tả bối cảnh ảnh đại diện này."
        )
    )
    payload = wire.build_payload(
        parts,
        temperature=temperature,
        max_output_tokens=VISION_MAX_OUTPUT_TOKENS,
        system_instruction=render_prompt("vision_describe", so_anh=len(images)),
    )

    started = time.perf_counter()
    try:
        raw = await gateway.generate_content(payload, model=model)
    except GatewayError as exc:
        return VisionResult(
            None,
            note=f"Bước mô tả ảnh thất bại: {exc.message}",
            model=model,
            latency_ms=_elapsed_ms(started),
        )

    latency_ms = _elapsed_ms(started)
    try:
        text = wire.extract_text(raw)
    except GatewayError as exc:
        return VisionResult(
            None,
            note=f"Model không trả về mô tả: {exc.message}",
            model=model,
            latency_ms=latency_ms,
        )

    description = _clean(text)
    if not description:
        return VisionResult(
            None, note="Model trả về mô tả rỗng.", model=model, latency_ms=latency_ms
        )

    note = ""
    if wire.extract_finish_reason(raw) == "MAX_TOKENS":
        # Có text nhưng bị cắt giữa câu. Trả về thì vẫn hơn mất hẳn, nhưng
        # phải nói rõ là chưa trọn — nếu không, một câu cụt sẽ bị đọc như một
        # mô tả đầy đủ (I-16).
        note = "Mô tả bị cắt vì vượt hạn mức token; hãy tăng max_output_tokens."
    if is_unclear(description):
        # Giữ nguyên câu của model: "không nhìn rõ" **là** thông tin đúng,
        # và nó phải xuất hiện trong output để người đọc biết ảnh không dùng được.
        note = "Model cho biết không nhìn rõ nội dung ảnh."

    return VisionResult(
        description,
        note=note,
        model=model,
        latency_ms=latency_ms,
        usage=wire.extract_usage(raw),
        image_count=len(images),
    )


def is_unclear(description: str) -> bool:
    lowered = description.lower()
    return any(marker in lowered for marker in _UNCLEAR_MARKERS)


def _clean(text: str) -> str:
    """Một câu, không ngoặc kép, không xuống dòng — đúng định dạng prompt yêu cầu."""
    value = " ".join(text.split()).strip().strip('"').strip("“”").strip()
    return value[:MAX_DESCRIPTION_CHARS]


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
