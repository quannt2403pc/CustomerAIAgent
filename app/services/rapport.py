"""Sinh chuỗi 5–10 tin nhắn tâm sự + `core_empathy_angle` (plan.md §5.4).

Module này **không** tự quyết `sales_mention_check`. Nó chỉ sinh nội dung; việc
đặt `ZERO_SALES_CONFIRMED` là độc quyền của `ZeroSalesValidator` (D1.17, luật
L2). Tách như vậy để không có đường nào đặt được cờ đó mà chưa qua kiểm duyệt.

Ràng buộc văn phong được kiểm tra **bằng code**, không chỉ nhờ prompt: model
nhớ 9 luật trong prompt là chuyện không chắc, còn đo độ dài thì luôn chắc.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from app.core.errors import GatewayBadResponse, GatewayError
from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.prompts import render as render_prompt
from app.services.json_reply import parse_object, parse_string_list
from app.services.profiler import ProfileResult

log = get_logger(__name__)

MIN_MESSAGES = 5
MAX_MESSAGES = 10
DEFAULT_MESSAGES = 10

MAX_MESSAGE_CHARS = 220
MAX_EMOJI_PER_MESSAGE = 1
MAX_QUESTION_MARKS = 1

# Hạn mức rộng: 10 tin × ~60 token + thinking token (I-16).
RAPPORT_MAX_OUTPUT_TOKENS = 8192
EMPATHY_MAX_OUTPUT_TOKENS = 2048

# Đại từ của người bán, không phải của một người bạn.
_SELLER_PRONOUNS = ("chúng tôi", "bên mình", "shop", "cửa hàng", "công ty")

# Khen sáo rỗng — không bắt nguồn từ bằng chứng nào.
_HOLLOW_PRAISE = (
    "xinh quá",
    "đẹp quá",
    "ngưỡng mộ",
    "tuyệt vời quá",
    "số một",
    "hoàn hảo",
)

_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\U0000fe0f"
    "\U00002b00-\U00002bff"
    "]",
    flags=re.UNICODE,
)


@dataclass
class StyleIssue:
    """Một vi phạm văn phong, kèm số thứ tự tin để sửa đúng chỗ."""

    seq: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"tin {self.seq}: {self.rule} ({self.detail})"


@dataclass
class RapportResult:
    """Chuỗi tin nhắn đã sinh. **Chưa** qua kiểm duyệt bán hàng/grounding."""

    messages: list[str]
    empathy_angle: str | None
    empathy_grounded_in: str | None = None
    style_issues: list[StyleIssue] = field(default_factory=list)
    latency_ms: int | None = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def style_ok(self) -> bool:
        return not self.style_issues


def clamp_message_count(value: int | None) -> int:
    """Đề bài cho 5–10 tin; ngoài khoảng là sai đặc tả nên kẹp lại."""
    if value is None:
        return DEFAULT_MESSAGES
    return max(MIN_MESSAGES, min(MAX_MESSAGES, value))


async def generate_empathy_angle(
    profile: ProfileResult,
    evidence_corpus: str,
    gateway: LLMGateway,
    *,
    model: str,
    temperature: float = 0.7,
) -> tuple[str | None, str | None]:
    """Trả `(core_empathy_angle, grounded_in)`. `(None, None)` nếu thất bại."""
    prompt = render_prompt(
        "empathy_angle",
        evidence=evidence_corpus or "(không có bằng chứng văn bản)",
        visual_context=profile.visual_context or "(không có mô tả ảnh)",
    )
    payload = wire.build_payload(
        [wire.text_part(prompt)],
        temperature=temperature,
        max_output_tokens=EMPATHY_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
    )
    try:
        raw = await gateway.generate_content(payload, model=model)
        body = parse_object(wire.extract_text(raw))
    except GatewayError as exc:
        log.warning("Không sinh được góc thấu cảm: %s", exc.code)
        return None, None

    angle = _one_line(body.get("core_empathy_angle"))
    grounded = _one_line(body.get("grounded_in"))
    return angle, grounded


async def generate_sequence(
    profile: ProfileResult,
    evidence_corpus: str,
    gateway: LLMGateway,
    *,
    model: str,
    n_messages: int | None = None,
    temperature: float = 0.9,
    empathy_angle: str | None = None,
    empathy_grounded_in: str | None = None,
    extra_instruction: str = "",
) -> RapportResult:
    """Sinh chuỗi tin nhắn.

    `extra_instruction` dành cho vòng sinh lại của D1.17: nêu đúng điều đã sai
    ở lượt trước (bị bắt chào bán, nhắc dữ kiện không có bằng chứng…).
    """
    count = clamp_message_count(n_messages)

    if empathy_angle is None:
        empathy_angle, empathy_grounded_in = await generate_empathy_angle(
            profile, evidence_corpus, gateway, model=model, temperature=temperature
        )

    prompt = render_prompt(
        "rapport_sequence",
        n_messages=count,
        empathy_angle=empathy_angle or "(chưa xác định — hãy chọn góc an toàn từ bằng chứng)",
        evidence=evidence_corpus or "(không có bằng chứng văn bản)",
        visual_context=profile.visual_context or "(không có mô tả ảnh)",
    )
    if extra_instruction:
        prompt = f"{prompt}\n\nSỬA LỖI LƯỢT TRƯỚC — BẮT BUỘC:\n{extra_instruction}"

    payload = wire.build_payload(
        [wire.text_part(prompt)],
        temperature=temperature,
        max_output_tokens=RAPPORT_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
    )

    started = time.perf_counter()
    raw = await gateway.generate_content(payload, model=model)
    latency_ms = int((time.perf_counter() - started) * 1000)

    messages = parse_string_list(wire.extract_text(raw), key="messages")
    messages = [_one_line(m) or "" for m in messages]
    messages = [m for m in messages if m]

    if len(messages) < MIN_MESSAGES:
        raise GatewayBadResponse(
            f"Model chỉ sinh được {len(messages)} tin, cần ít nhất {MIN_MESSAGES}.",
            detail=f"yêu cầu {count} tin",
        )
    # Thừa thì cắt; thiếu-nhưng-đủ-tối-thiểu thì nhận, vòng sinh lại sẽ lo.
    messages = messages[:count]

    return RapportResult(
        messages=messages,
        empathy_angle=empathy_angle,
        empathy_grounded_in=empathy_grounded_in,
        style_issues=check_style(messages),
        latency_ms=latency_ms,
        usage=wire.extract_usage(raw),
    )


def check_style(messages: list[str]) -> list[StyleIssue]:
    """Kiểm ràng buộc văn phong plan.md §5.4 **bằng code**.

    Prompt nhắc model 9 luật; code thì đo được. Hai thứ bổ sung cho nhau.
    """
    issues: list[StyleIssue] = []

    for seq, message in enumerate(messages, 1):
        if len(message) > MAX_MESSAGE_CHARS:
            issues.append(StyleIssue(seq, "dài quá 220 ký tự", f"{len(message)} ký tự"))

        emoji_count = len(_EMOJI.findall(message))
        if emoji_count > MAX_EMOJI_PER_MESSAGE:
            issues.append(StyleIssue(seq, "quá 1 emoji", f"{emoji_count} emoji"))

        question_marks = message.count("?") + message.count("？")
        if question_marks > MAX_QUESTION_MARKS:
            issues.append(
                StyleIssue(seq, "hỏi dồn nhiều câu trong một tin", f"{question_marks} dấu hỏi")
            )

        lowered = message.lower()
        for pronoun in _SELLER_PRONOUNS:
            if pronoun in lowered:
                issues.append(StyleIssue(seq, "xưng như người bán", f"“{pronoun}”"))
                break

        for praise in _HOLLOW_PRAISE:
            if praise in lowered:
                issues.append(StyleIssue(seq, "khen sáo rỗng", f"“{praise}”"))
                break

    return issues


def style_feedback(issues: list[StyleIssue]) -> str:
    """Biến vi phạm thành chỉ dẫn cho lượt sinh lại."""
    if not issues:
        return ""
    lines = "\n".join(f"- {issue}" for issue in issues)
    return f"Lượt trước vi phạm văn phong, hãy viết lại cho đúng:\n{lines}"


def _one_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    # Model hay bọc ngoặc kép quanh cả câu.
    text = text.strip('"').strip("“”").strip()
    return text or None
