"""Sinh gợi ý tin nhắn **theo ngữ cảnh hội thoại đang diễn ra** (task.md X.3).

Khác `rapport.generate_sequence` ở điểm cốt lõi: kia sinh một chuỗi 10 tin
**một lần, không biết người kia sẽ nói gì**. Ở đây mỗi lượt gợi ý đọc được toàn
bộ những gì đã xảy ra — kể cả câu khách vừa trả lời — nên tin tiếp theo mới bám
được vào đúng điều họ vừa mở lòng.

**Luật L3 không đổi.** Module này không gửi gì cả; nó chỉ đề xuất. Việc gửi do
con người bấm, ở Messenger, bằng tay.

Kiểm duyệt giữ nguyên hai lớp như chuỗi tĩnh: `GroundingValidator` (L1) và
`ZeroSalesValidator` (L2). Một gợi ý không qua được thì **bị loại khỏi danh
sách**, không hiện ra cho người vận hành chọn — cùng lý lẽ với I-23: nội dung
chưa duyệt mà hiện ra là mời người ta copy đi gửi.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.prompts import render as render_prompt
from app.services.json_reply import parse_object
from app.services.rapport import MAX_MESSAGE_CHARS, check_style
from app.services.validators import (
    GroundingReport,
    ZeroSalesReport,
    validate_grounding,
    validate_zero_sales,
)

log = get_logger(__name__)

#: Ba phương án là đủ để có lựa chọn mà không làm người vận hành tê liệt vì
#: quá nhiều thứ phải cân nhắc giữa lúc đang trò chuyện.
DEFAULT_SUGGESTIONS = 3
MAX_SUGGESTIONS = 5

#: Cửa sổ lịch sử đưa vào prompt. Cả cuộc trò chuyện có thể rất dài; 20 lượt gần
#: nhất đủ để bám mạch mà không đốt token vô ích.
HISTORY_WINDOW = 20

SUGGEST_MAX_OUTPUT_TOKENS = 2048

ROLE_LABEL = {"operator": "BẠN", "customer": "KHÁCH"}


@dataclass
class SuggestionRound:
    """Kết quả một lượt sinh gợi ý."""

    suggestions: list[str] = field(default_factory=list)
    attempts: int = 0
    rejected: list[str] = field(default_factory=list)
    grounding_report: GroundingReport | None = None
    sales_report: ZeroSalesReport | None = None

    @property
    def passed(self) -> bool:
        return bool(self.suggestions)

    def report_for_db(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "rejected": self.rejected,
            "grounding": self.grounding_report.to_dict() if self.grounding_report else None,
            "zero_sales": self.sales_report.to_dict() if self.sales_report else None,
        }


def format_history(messages: list[tuple[str, str]]) -> str:
    """`[(role, text)]` → khối văn bản cho prompt, mới nhất ở cuối.

    Nhãn tiếng Việt (`BẠN` / `KHÁCH`) chứ không phải `operator`/`customer`: model
    đọc prompt tiếng Việt, nhãn tiếng Anh giữa khối tiếng Việt làm nó dễ nhầm vai.
    """
    if not messages:
        return "(chưa có lượt nào — đây là tin mở đầu)"
    recent = messages[-HISTORY_WINDOW:]
    return "\n".join(f"{ROLE_LABEL.get(role, role)}: {text}" for role, text in recent)


def format_captions(captions: list[str]) -> str:
    """Tiêu đề/nội dung bài đăng đọc được.

    Rỗng là chuyện **bình thường**, không phải lỗi: đo thật (task.md I-31, I-33)
    cho thấy Facebook che caption với khách chưa đăng nhập, kể cả bài Công khai.
    Nói thẳng điều đó trong prompt để model chuyển sang hướng hỏi mở bám ảnh
    (X.5) thay vì bịa ra một caption không có.
    """
    if not captions:
        return (
            "(không đọc được tiêu đề/nội dung bài đăng nào — hãy dựa vào MÔ TẢ ẢNH "
            "và đặt câu hỏi mở để chính khách kể ra)"
        )
    return "\n".join(f"- {caption}" for caption in captions)


async def generate_suggestions(
    gateway: LLMGateway,
    *,
    model: str,
    evidence_corpus: str,
    visual_context: str | None,
    captions: list[str],
    history: list[tuple[str, str]],
    n_suggestions: int = DEFAULT_SUGGESTIONS,
    temperature: float = 0.9,
    max_attempts: int = 2,
) -> SuggestionRound:
    """Sinh → kiểm duyệt → sinh lại. Trả về **chỉ những gợi ý đã sạch**."""
    n = max(1, min(n_suggestions, MAX_SUGGESTIONS))
    rejected: list[str] = []
    feedback = ""
    last_grounding: GroundingReport | None = None
    last_sales: ZeroSalesReport | None = None

    for attempt in range(1, max_attempts + 2):
        prompt = render_prompt(
            "conversation_suggest",
            n_suggestions=n,
            evidence=evidence_corpus or "(không có bằng chứng văn bản)",
            visual_context=visual_context or "(không có mô tả ảnh)",
            post_captions=format_captions(captions),
            history=format_history(history),
        )
        if feedback:
            prompt = f"{prompt}\n\nSỬA LỖI LƯỢT TRƯỚC — BẮT BUỘC:\n{feedback}"

        payload = wire.build_payload(
            [wire.text_part(prompt)],
            temperature=temperature,
            max_output_tokens=SUGGEST_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        )
        raw = await gateway.generate_content(payload, model=model)
        body = parse_object(wire.extract_text(raw))

        candidates = [
            text.strip()
            for text in (body.get("suggestions") or [])
            if isinstance(text, str) and text.strip()
        ]
        if not candidates:
            rejected.append(f"lượt {attempt}: model không trả về gợi ý nào")
            continue

        # Kiểm **cả lô** một lần: `validate_zero_sales` có LLM judge nên gọi
        # từng câu một sẽ nhân số lượt gọi model lên gấp n.
        grounding = validate_grounding(candidates, evidence_corpus)
        sales = await validate_zero_sales(candidates, gateway, model=model)
        last_grounding, last_sales = grounding, sales

        clean = _keep_clean(candidates, grounding, sales)
        if clean:
            log.info(
                "Gợi ý hội thoại: %d/%d câu sạch ở lượt %d",
                len(clean),
                len(candidates),
                attempt,
            )
            return SuggestionRound(
                suggestions=clean,
                attempts=attempt,
                rejected=rejected,
                grounding_report=grounding,
                sales_report=sales,
            )

        problems = [part for part in (grounding.feedback(), sales.feedback()) if part]
        summary = " | ".join(problems or ["không câu nào qua kiểm duyệt"])
        rejected.append(f"lượt {attempt}: {summary}")
        feedback = "\n\n".join(problems)
        log.warning("Lượt gợi ý %d không có câu nào sạch, sinh lại", attempt)

    log.error("Hết lượt mà không có gợi ý nào qua kiểm duyệt")
    return SuggestionRound(
        suggestions=[],
        attempts=max_attempts + 1,
        rejected=rejected,
        grounding_report=last_grounding,
        sales_report=last_sales,
    )


def _keep_clean(
    candidates: list[str], grounding: GroundingReport, sales: ZeroSalesReport
) -> list[str]:
    """Giữ lại những câu **không** bị bất kỳ lớp nào đánh dấu.

    Hai mức khác nhau, không được trộn:

    - **Lớp chào bán (L2) phán trên cả lô.** `validate_zero_sales` chạy LLM judge
      cho *toàn bộ* danh sách; judge báo bẩn thì nó thêm một `SalesHit(seq=0)` —
      `seq = 0` nghĩa là "cả lô", không chỉ được câu nào. Và khi hai lớp cơ học
      đã bắt được thì judge **bị bỏ qua** (`judge_ran = False`), nên những câu
      còn lại chưa từng được judge chấm. Trong cả hai trường hợp, cách duy nhất
      trung thực là **bỏ cả lô và sinh lại** — nhặt ra vài câu rồi gọi chúng là
      "0% chào bán" là xác nhận một điều chưa ai kiểm (luật L2).
    - **Lớp grounding (L1) phán từng câu.** Nó thuần cơ học, `seq` trỏ đúng vị
      trí, nên loại đúng câu bịa và giữ phần còn lại là hợp lệ — và phần còn lại
      đó *đã* nằm trong lô mà judge chấm sạch.
    """
    # Lô chưa sạch về chào bán → không nhặt gì cả.
    if not sales.passed:
        return []

    # `seq` của `UngroundedClaim` đánh số **từ 1** theo vị trí trong lô.
    bad_indexes = {
        claim.seq - 1 for claim in grounding.ungrounded_claims if 1 <= claim.seq <= len(candidates)
    }

    clean: list[str] = []
    for index, text in enumerate(candidates):
        if index in bad_indexes:
            continue
        if len(text) > MAX_MESSAGE_CHARS:
            continue
        if check_style([text]):
            continue
        clean.append(text)
    return clean
