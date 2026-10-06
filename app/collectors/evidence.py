"""`EvidenceBundle` — trụ của luật L1 (plan.md §5.2).

Mọi khẳng định về khách trong output phải truy vết được về một `EvidenceField`
trong bundle này. Không có field → giá trị là `None`, **không đoán**.

Thiết kế có chủ đích:

- `attempts[]` ghi **cả lần thất bại**. "Đọc được tới đâu" là thông tin người
  vận hành cần, và `error_note` của nhánh `PARTIAL_OR_PRIVATE` được dựng từ đây.
- Collector **không raise** khi bị chặn: login wall là *sự thật về trang đó*,
  không phải lỗi hệ thống. Nó được ghi vào `blocked_reason`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceName = Literal["og_meta", "mbasic_html", "playwright_dom", "vision_avatar", "manual_paste"]

# Khoá field được phép — bảng tên đóng để không ai lặng lẽ thêm field bịa.
FieldKey = Literal[
    "customer_name",
    "bio",
    "post_text",
    "avatar_url",
    "page_description",
    # Mô tả ảnh do bước vision sinh ra. Là bằng chứng thật vì nó gắn với ảnh đã
    # tải + sha256, nên `GroundingValidator` được phép đối chiếu với nó.
    "visual_context",
    "location",
    "work",
    "education",
    "relationship",
]


@dataclass(frozen=True)
class EvidenceField:
    """Một dữ kiện + bằng chứng của nó.

    `evidence` phải là **đoạn thật** đã đọc được (thẻ meta, câu trong HTML…),
    không phải diễn giải. Đó là thứ `GroundingValidator` đối chiếu.
    """

    key: str
    value: str
    source: SourceName
    evidence: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError(f"EvidenceField {self.key!r} không được có value rỗng — dùng None.")
        if not self.evidence:
            raise ValueError(
                f"EvidenceField {self.key!r} thiếu `evidence`. Không có bằng chứng "
                "thì không được tạo field (luật L1)."
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence phải trong [0, 1], nhận {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class EvidenceImage:
    role: Literal["avatar", "public_photo"]
    url: str
    local_path: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "url": self.url,
            "local_path": self.local_path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class CollectAttempt:
    """Một lần thử của một lớp collector — kể cả khi thất bại."""

    layer: str
    ok: bool
    http_status: int | None = None
    note: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "ok": self.ok,
            "http_status": self.http_status,
            "note": self.note,
            "skipped": self.skipped,
        }


@dataclass
class EvidenceBundle:
    """Tất cả những gì đã **thật sự** đọc được về một URL."""

    url_key: str
    facebook_url: str
    fields: list[EvidenceField] = field(default_factory=list)
    images: list[EvidenceImage] = field(default_factory=list)
    attempts: list[CollectAttempt] = field(default_factory=list)
    blocked_reason: str | None = None
    # Ảnh chụp toàn trang do lớp L3 tạo — bằng chứng cho `visual_context` và
    # cho cả câu "đọc được tới đâu". Đi vào `profile_evidence.screenshot_path`.
    screenshot_path: str | None = None

    # -- Ghi ---------------------------------------------------------------
    def add_field(
        self,
        key: str,
        value: str | None,
        *,
        source: SourceName,
        evidence: str,
        confidence: float,
    ) -> bool:
        """Thêm một dữ kiện. Trả `False` nếu bị bỏ qua.

        Bỏ qua khi: value rỗng, hoặc đã có field cùng `key` với confidence
        cao hơn/bằng. Lớp sau không được ghi đè dữ kiện chắc chắn hơn của lớp trước.
        """
        cleaned = (value or "").strip()
        if not cleaned or not evidence.strip():
            return False

        existing = self.get_field(key)
        if existing is not None:
            if existing.confidence >= confidence:
                return False
            self.fields = [f for f in self.fields if f.key != key]

        self.fields.append(
            EvidenceField(
                key=key,
                value=cleaned,
                source=source,
                evidence=evidence.strip()[:2000],
                confidence=confidence,
            )
        )
        return True

    def add_image(self, image: EvidenceImage) -> None:
        if not any(existing.url == image.url for existing in self.images):
            self.images.append(image)

    def add_attempt(self, attempt: CollectAttempt) -> None:
        self.attempts.append(attempt)

    def mark_blocked(self, reason: str) -> None:
        """Ghi nhận bị chặn. Giữ lý do **đầu tiên** — nó gần nguyên nhân gốc nhất."""
        if self.blocked_reason is None:
            self.blocked_reason = reason

    # -- Đọc ---------------------------------------------------------------
    def get_field(self, key: str) -> EvidenceField | None:
        return next((f for f in self.fields if f.key == key), None)

    def value_of(self, key: str) -> str | None:
        """Giá trị của một dữ kiện, hoặc `None`. Không có nghĩa là không có."""
        found = self.get_field(key)
        return found.value if found else None

    @property
    def is_empty(self) -> bool:
        """Không đọc được dữ kiện nào → nhánh `PARTIAL_OR_PRIVATE`."""
        return not self.fields

    @property
    def has_avatar(self) -> bool:
        return any(image.role == "avatar" for image in self.images)

    @property
    def avatar(self) -> EvidenceImage | None:
        return next((image for image in self.images if image.role == "avatar"), None)

    @property
    def layers_used(self) -> list[str]:
        """Các lớp đã đóng góp ít nhất một dữ kiện."""
        contributing = {f.source for f in self.fields}
        return [a.layer for a in self.attempts if a.ok and a.layer in contributing]

    def evidence_corpus(self) -> str:
        """Toàn bộ văn bản bằng chứng, nối lại.

        `GroundingValidator` đối chiếu thực thể trong output với chuỗi này.
        """
        parts = [f"{f.value}\n{f.evidence}" for f in self.fields]
        return "\n".join(parts)

    def describe_coverage(self) -> str:
        """Câu tiếng Việt "đọc được tới đâu" cho `error_note`.

        Nói thật, không trang trí: đây chính là tiêu chí §4 của đề bài.
        """
        if self.fields:
            keys = ", ".join(sorted({f.key for f in self.fields}))
            sentence = f"Chỉ thu thập được: {keys}."
        else:
            sentence = "Không thu thập được dữ kiện công khai nào."

        failed = [a for a in self.attempts if not a.ok and not a.skipped]
        if failed:
            detail = "; ".join(
                f"{a.layer}"
                + (f" (HTTP {a.http_status})" if a.http_status else "")
                + (f": {a.note}" if a.note else "")
                for a in failed
            )
            sentence += f" Các lớp không đọc được: {detail}."
        if self.blocked_reason:
            sentence += f" {self.blocked_reason}"
        return sentence

    # -- Lưu trữ -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Dạng JSONB lưu vào `profile_evidence.bundle`."""
        return {
            "url_key": self.url_key,
            "facebook_url": self.facebook_url,
            "fields": [f.to_dict() for f in self.fields],
            "images": [i.to_dict() for i in self.images],
            "attempts": [a.to_dict() for a in self.attempts],
            "blocked_reason": self.blocked_reason,
            "screenshot_path": self.screenshot_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceBundle:
        bundle = cls(url_key=data["url_key"], facebook_url=data["facebook_url"])
        bundle.fields = [EvidenceField(**f) for f in data.get("fields", [])]
        bundle.images = [EvidenceImage(**i) for i in data.get("images", [])]
        bundle.attempts = [CollectAttempt(**a) for a in data.get("attempts", [])]
        bundle.blocked_reason = data.get("blocked_reason")
        bundle.screenshot_path = data.get("screenshot_path")
        return bundle
