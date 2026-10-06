"""Profiler — ghép evidence + vision + demographics thành `profile_data`.

Đây là chỗ luật L1 được **thi hành**, không chỉ được mong đợi:

- Mỗi field của `profile_data` chỉ có giá trị khi có một `EvidenceField` hoặc
  một mô tả vision thật đứng sau. Không có → `None`.
- `status` được *hạ* theo đúng mức độ đọc được, và `error_note` nói thẳng đọc
  được tới đâu. Trả `SUCCESS` cho một profile rỗng là nói dối.
- `estimated_age_range` luôn là **khoảng**; model trả một con số thì ở đây
  chuyển thành khoảng hoặc bỏ, không in nguyên con số ra output.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.collectors.avatar import NormalizedImage
from app.collectors.evidence import EvidenceBundle
from app.core.errors import GatewayError
from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.llm.catalog import ModelCatalog
from app.prompts import render as render_prompt
from app.services.json_reply import parse_object
from app.services.vision import VisionResult, describe_avatar

log = get_logger(__name__)

STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL_OR_PRIVATE"

DEMOGRAPHICS_MAX_OUTPUT_TOKENS = 2048  # thinking token ăn vào hạn mức này (I-16)

# Đề bài chỉ cho hai giá trị. Model trả gì khác → `None`, không ánh xạ bừa.
ALLOWED_GENDERS: dict[str, str] = {
    "Nữ": "Nữ",
    "Nam": "Nam",
    "Female": "Nữ",
    "Male": "Nam",
}


@dataclass
class Demographics:
    """Ước lượng nhân khẩu học. Mỗi trường đi kèm `basis` để truy vết."""

    gender: str | None = None
    estimated_age_range: str | None = None
    apparent_lifestyle: str | None = None
    basis: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any((self.gender, self.estimated_age_range, self.apparent_lifestyle))

    def to_output_dict(self) -> dict[str, str | None]:
        """Dạng đưa vào strict JSON — **không** gồm `basis` (chỉ lưu DB)."""
        return {
            "gender": self.gender,
            "estimated_age_range": self.estimated_age_range,
            "apparent_lifestyle": self.apparent_lifestyle,
        }


@dataclass
class ProfileResult:
    """Kết quả bước profiler."""

    status: str
    customer_name: str | None
    visual_context: str | None
    demographics: Demographics
    error_note: str | None = None
    notes: list[str] = field(default_factory=list)
    vision: VisionResult | None = None
    latency_ms: int | None = None

    @property
    def is_usable_for_rapport(self) -> bool:
        """Có đủ dữ kiện để sinh tin nhắn tâm sự *có căn cứ* hay không.

        Không có tên lẫn không có mô tả ảnh thì mọi tin nhắn sẽ là lời chung
        chung — đúng thứ đề bài gọi là "câu từ vô hồn của bot".
        """
        return bool(self.customer_name or self.visual_context)

    def to_profile_data(self) -> dict[str, object]:
        return {
            "customer_name": self.customer_name,
            "visual_context": self.visual_context,
            "estimated_demographics": self.demographics.to_output_dict(),
        }


async def build_profile(
    bundle: EvidenceBundle,
    gateway: LLMGateway,
    *,
    model: str,
    avatar: NormalizedImage | None = None,
    public_photos: list[NormalizedImage] | None = None,
    temperature: float = 0.4,
    catalog: ModelCatalog | None = None,
) -> ProfileResult:
    """Dựng `profile_data` từ bundle. Không raise — mọi thất bại thành `notes`."""
    started = time.perf_counter()
    notes: list[str] = []

    customer_name = bundle.value_of("customer_name")

    vision = await describe_avatar(
        avatar, gateway, model=model, catalog=catalog, public_photos=public_photos
    )
    if vision.note:
        notes.append(vision.note)

    # Mô tả ảnh **là** bằng chứng: nó đến từ ảnh đã tải thật, có sha256 truy vết
    # được. Đưa nó vào bundle thay vì giữ riêng để `evidence_corpus()` — thứ
    # `GroundingValidator` đối chiếu — nhìn thấy nó. Không làm vậy thì một tin
    # nhắn nhắc đúng điều trong ảnh vẫn bị coi là "không có bằng chứng".
    if vision.description:
        _record_vision_evidence(bundle, vision, avatar, public_photos)

    demographics = Demographics()
    if customer_name or vision.description or not bundle.is_empty:
        demographics, demo_note = await _infer_demographics(
            bundle, vision, gateway, model=model, temperature=temperature
        )
        if demo_note:
            notes.append(demo_note)
    else:
        notes.append("Không có dữ kiện nào nên không ước lượng nhân khẩu học.")

    status, error_note = decide_status(
        bundle, customer_name=customer_name, visual_context=vision.description, notes=notes
    )

    return ProfileResult(
        status=status,
        customer_name=customer_name,
        visual_context=vision.description,
        demographics=demographics,
        error_note=error_note,
        notes=notes,
        vision=vision,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _record_vision_evidence(
    bundle: EvidenceBundle,
    vision: VisionResult,
    avatar: NormalizedImage | None,
    public_photos: list[NormalizedImage] | None,
) -> None:
    """Ghi mô tả ảnh vào bundle, kèm sha256 của **đúng** những ảnh đã mô tả."""
    images = [image for image in [avatar, *(public_photos or [])] if image is not None]
    digests = ", ".join(image.sha256[:12] for image in images)
    bundle.add_field(
        "visual_context",
        vision.description,
        source="vision_avatar",
        evidence=(
            f"mô tả do model `{vision.model or 'không rõ'}` sinh từ {len(images)} ảnh "
            f"đã tải (sha256: {digests}): {vision.description}"
        ),
        # Thấp hơn dữ kiện văn bản đọc trực tiếp: đây là *diễn giải* một bức ảnh,
        # dù diễn giải đó bị prompt ràng chỉ được nói cái nhìn thấy.
        confidence=0.7,
    )


def decide_status(
    bundle: EvidenceBundle,
    *,
    customer_name: str | None,
    visual_context: str | None,
    notes: list[str] | None = None,
) -> tuple[str, str | None]:
    """Quy tắc hạ status (plan.md §5.7, đề bài §4).

    `SUCCESS` chỉ khi có **cả** tên **và** mô tả ảnh. Thiếu một trong hai nghĩa
    là bức tranh về khách còn khuyết — đó đúng nghĩa `PARTIAL_OR_PRIVATE`, và
    đề bài tính điểm cho việc nói thật chỗ này.
    """
    notes = notes or []

    if customer_name and visual_context:
        return STATUS_SUCCESS, None

    missing: list[str] = []
    if not customer_name:
        missing.append("tên hiển thị")
    if not visual_context:
        missing.append("bối cảnh ảnh đại diện")

    parts = [f"Không đọc được: {', '.join(missing)}.", bundle.describe_coverage()]
    parts.extend(note for note in notes if note)
    return STATUS_PARTIAL, " ".join(part for part in parts if part).strip()


async def _infer_demographics(
    bundle: EvidenceBundle,
    vision: VisionResult,
    gateway: LLMGateway,
    *,
    model: str,
    temperature: float,
) -> tuple[Demographics, str]:
    prompt = render_prompt(
        "infer_demographics",
        evidence=bundle.evidence_corpus() or "(không có bằng chứng văn bản)",
        visual_context=vision.description or "(không có mô tả ảnh)",
    )
    payload = wire.build_payload(
        [wire.text_part(prompt)],
        temperature=temperature,
        max_output_tokens=DEMOGRAPHICS_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
    )

    try:
        raw = await gateway.generate_content(payload, model=model)
        body = parse_object(wire.extract_text(raw))
    except GatewayError as exc:
        return Demographics(), f"Không ước lượng được nhân khẩu học: {exc.message}"

    return _demographics_from_reply(body), ""


def _demographics_from_reply(body: dict[str, object]) -> Demographics:
    basis_raw = body.get("basis")
    basis = {str(k): str(v) for k, v in basis_raw.items()} if isinstance(basis_raw, dict) else {}
    return Demographics(
        gender=_clean_gender(body.get("gender")),
        estimated_age_range=normalize_age_range(body.get("estimated_age_range")),
        apparent_lifestyle=_clean_text(body.get("apparent_lifestyle"), limit=80),
        basis=basis,
    )


def _clean_gender(value: object) -> str | None:
    """Chỉ nhận đúng "Nữ"/"Nam". Chuỗi lạ → `None`, không cố ánh xạ.

    Model có thể trả "Female", "không rõ", "N/A". Ánh xạ bừa là tự bịa thêm
    một tầng suy luận không ai kiểm tra được.
    """
    text = _clean_text(value, limit=16)
    if text is None:
        return None
    return ALLOWED_GENDERS.get(text.strip().capitalize())


_AGE_RANGE = re.compile(r"(\d{1,2})\s*(?:-|–|—|đến|tới|to)\s*(\d{1,3})")
_SINGLE_AGE = re.compile(r"^\D*(\d{1,2})\D*$")


def normalize_age_range(value: object) -> str | None:
    """Luôn trả **khoảng**, không bao giờ một con số (task.md D1.15 DoD).

    Model trả "32 tuổi" → đổi thành "27 - 37 tuổi" (±5). Đây là làm cho output
    nói đúng mức độ chắc chắn thật của một ước lượng, chứ không phải làm đẹp.
    """
    text = _clean_text(value, limit=40)
    if text is None:
        return None

    if match := _AGE_RANGE.search(text):
        low, high = int(match.group(1)), int(match.group(2))
        if low > high:
            low, high = high, low
        if not (1 <= low <= 120 and 1 <= high <= 120):
            return None
        return f"{low} - {high} tuổi"

    if match := _SINGLE_AGE.match(text):
        age = int(match.group(1))
        if not 1 <= age <= 120:
            return None
        low = max(1, age - 5)
        return f"{low} - {age + 5} tuổi"

    return None


def _clean_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip().strip('"').strip("“”")
    if not text:
        return None
    # Model hay trả chuỗi "null"/"không rõ" thay vì JSON null.
    if text.lower() in {"null", "none", "n/a", "không rõ", "khong ro", "unknown", "-"}:
        return None
    return text[:limit]
