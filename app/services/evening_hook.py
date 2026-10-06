"""Câu chuyện mồi 20h (plan.md §5.5, đề bài chức năng 3).

Hook đi qua **cả hai** validator y như chuỗi tin nhắn — nó cũng là nội dung gửi
cho người thật, nên không có lý gì được miễn kiểm duyệt.

`trigger_time` là hằng số `"20:00"`, không lấy từ cấu hình: đề bài nêu rõ mốc
giờ này, và để nó cấu hình được thì một thay đổi `.env` sẽ âm thầm làm output
lệch đặc tả.

Chống lặp ý: so với **7 hook gần nhất** của cùng profile (plan.md §5.5). Vừa
nêu chúng trong prompt để model tự tránh, vừa kiểm lại bằng code — prompt là
lời nhờ, còn đo độ tương tự thì chắc chắn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import GatewayError
from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.prompts import render as render_prompt
from app.services.json_reply import parse_object
from app.services.profiler import ProfileResult
from app.services.rapport import MAX_MESSAGE_CHARS, check_style
from app.services.validators import (
    GroundingReport,
    ZeroSalesReport,
    squash,
    validate_grounding,
    validate_zero_sales,
)

log = get_logger(__name__)

TRIGGER_TIME = "20:00"
RECENT_HOOKS_TO_AVOID = 7
HOOK_MAX_OUTPUT_TOKENS = 2048
MAX_REGENERATE_ATTEMPTS = 2

# Trùng ≥60% từ (sau khi bỏ dấu) với một hook cũ là lặp ý, dù câu chữ đã đổi.
SIMILARITY_THRESHOLD = 0.6
# Câu quá ngắn thì tỉ lệ trùng từ nhiễu rất mạnh — dưới mức này thì bỏ qua.
MIN_TOKENS_FOR_SIMILARITY = 5


@dataclass
class EveningHookResult:
    """Hook 20h đã qua kiểm duyệt — hoặc đã hết lượt mà vẫn chưa sạch."""

    passed: bool
    attempts: int
    message: str | None = None
    grounded_in: str | None = None
    sales_report: ZeroSalesReport | None = None
    grounding_report: GroundingReport | None = None
    rejected_reasons: list[str] = field(default_factory=list)

    @property
    def trigger_time(self) -> str:
        """Luôn `"20:00"` — đề bài nêu rõ mốc giờ này."""
        return TRIGGER_TIME

    def to_output_dict(self) -> dict[str, str | None]:
        return {"trigger_time": TRIGGER_TIME, "evening_hook_message": self.message}

    def report_for_db(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "passed": self.passed,
            "grounded_in": self.grounded_in,
            "grounding": self.grounding_report.to_dict() if self.grounding_report else None,
            "zero_sales": self.sales_report.to_dict() if self.sales_report else None,
            "rejected_reasons": self.rejected_reasons,
        }


def similarity(left: str, right: str) -> float:
    """Tỉ lệ từ dùng chung (Jaccard) sau khi bỏ dấu.

    Đủ để bắt "đổi từ ngữ nhưng cùng một ý" mà không cần embedding (plan.md
    §12.6 loại vector search khỏi phạm vi bản này).
    """
    left_tokens = {squash(word) for word in left.split() if squash(word)}
    right_tokens = {squash(word) for word in right.split() if squash(word)}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def find_repetition(candidate: str, recent: list[str]) -> str | None:
    """Trả hook cũ bị lặp ý, hoặc `None`."""
    if len(candidate.split()) < MIN_TOKENS_FOR_SIMILARITY:
        return None
    for previous in recent:
        if similarity(candidate, previous) >= SIMILARITY_THRESHOLD:
            return previous
    return None


async def generate_evening_hook(
    profile: ProfileResult,
    evidence_corpus: str,
    gateway: LLMGateway,
    *,
    model: str,
    empathy_angle: str | None = None,
    recent_hooks: list[str] | None = None,
    temperature: float = 0.9,
    max_attempts: int = MAX_REGENERATE_ATTEMPTS,
) -> EveningHookResult:
    """Sinh hook 20h, kiểm duyệt, sinh lại tối đa `max_attempts` lượt."""
    recent = (recent_hooks or [])[:RECENT_HOOKS_TO_AVOID]
    rejected: list[str] = []
    feedback = ""
    last_sales: ZeroSalesReport | None = None
    last_grounding: GroundingReport | None = None

    for attempt in range(1, max_attempts + 2):
        prompt = render_prompt(
            "evening_hook",
            empathy_angle=empathy_angle or "(chưa xác định — hãy chọn góc an toàn từ bằng chứng)",
            evidence=evidence_corpus or "(không có bằng chứng văn bản)",
            visual_context=profile.visual_context or "(không có mô tả ảnh)",
            recent_block=_recent_block(recent),
        )
        if feedback:
            prompt = f"{prompt}\n\nSỬA LỖI LƯỢT TRƯỚC — BẮT BUỘC:\n{feedback}"

        payload = wire.build_payload(
            [wire.text_part(prompt)],
            temperature=temperature,
            max_output_tokens=HOOK_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        )

        try:
            raw = await gateway.generate_content(payload, model=model)
            body = parse_object(wire.extract_text(raw))
        except GatewayError as exc:
            rejected.append(f"lượt {attempt}: gọi model thất bại — {exc.message}")
            feedback = ""
            continue

        message = _one_line(body.get("hook"))
        grounded_in = _one_line(body.get("grounded_in"))
        if not message:
            rejected.append(f"lượt {attempt}: model không trả về hook")
            continue

        problems: list[str] = []

        if len(message) > MAX_MESSAGE_CHARS:
            problems.append(f"Hook dài {len(message)} ký tự, tối đa {MAX_MESSAGE_CHARS}.")
        if style_issues := check_style([message]):
            problems.extend(str(issue) for issue in style_issues)

        grounding = validate_grounding([message], evidence_corpus)
        if not grounding.passed:
            problems.append(grounding.feedback())
        last_grounding = grounding

        sales = await validate_zero_sales([message], gateway, model=model)
        if not sales.passed:
            problems.append(sales.feedback() or sales.judge_reason)
        last_sales = sales

        if repeated := find_repetition(message, recent):
            problems.append(
                "Hook này lặp ý với một tin đã gửi gần đây, hãy đổi hẳn chủ đề: "
                f"“{repeated[:100]}”"
            )

        if not problems:
            log.info("Hook 20h qua kiểm duyệt ở lượt %d", attempt)
            return EveningHookResult(
                passed=True,
                attempts=attempt,
                message=message,
                grounded_in=grounded_in,
                sales_report=sales,
                grounding_report=grounding,
                rejected_reasons=rejected,
            )

        rejected.append(f"lượt {attempt}: " + " | ".join(p for p in problems if p))
        feedback = "\n".join(p for p in problems if p)
        log.warning("Hook 20h lượt %d không qua kiểm duyệt", attempt)

    # Hết lượt → KHÔNG trả nội dung chưa sạch.
    log.error("Hook 20h không qua kiểm duyệt sau %d lượt", max_attempts + 1)
    return EveningHookResult(
        passed=False,
        attempts=max_attempts + 1,
        message=None,
        sales_report=last_sales,
        grounding_report=last_grounding,
        rejected_reasons=rejected,
    )


async def fetch_recent_hooks(session, profile_id, *, limit: int = RECENT_HOOKS_TO_AVOID):
    """Đọc `limit` hook gần nhất của một profile, mới nhất trước.

    Tách thành hàm riêng để job 20h (D2.4) và CLI dùng cùng một truy vấn —
    hai chỗ đọc "7 hook gần nhất" theo hai cách khác nhau là mời lệch hành vi.
    """
    from sqlalchemy import select

    from app.models import EveningHook

    stmt = (
        select(EveningHook.message)
        .where(EveningHook.profile_id == profile_id)
        .order_by(EveningHook.generated_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _recent_block(recent: list[str]) -> str:
    if not recent:
        return "TIN 20H ĐÃ GỬI GẦN ĐÂY\n(chưa gửi lần nào)"
    lines = "\n".join(f"- {hook}" for hook in recent)
    return f"TIN 20H ĐÃ GỬI GẦN ĐÂY ({len(recent)} tin) — PHẢI KHÁC HẲN Ý những tin này\n{lines}"


def _one_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip().strip('"').strip("“”").strip()
    return text or None
