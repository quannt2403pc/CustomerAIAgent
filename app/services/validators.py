"""Hai validator canh giữ luật L1 và L2 (plan.md §5.6).

`ZeroSalesValidator` là **cửa duy nhất** đặt được `ZERO_SALES_CONFIRMED`. Không
module nào khác được phép gán giá trị đó.

Về mức độ nghiêm ngặt: cả hai validator cố ý thà **bắt oan** hơn **bỏ sót**.
Bắt oan thì mất một lượt sinh lại; bỏ sót thì gửi cho khách một câu chào bán
hoặc một dữ kiện bịa — đúng hai thứ đề bài loại ngay.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.errors import GatewayError
from app.core.logging import get_logger
from app.llm import gemini_wire as wire
from app.llm.base import LLMGateway
from app.services.json_reply import parse_object

log = get_logger(__name__)

ZERO_SALES_CONFIRMED = "ZERO_SALES_CONFIRMED"
SALES_CHECK_FAILED = "FAILED"

JUDGE_MAX_OUTPUT_TOKENS = 2048


# ===========================================================================
# ZeroSalesValidator — luật L2
# ===========================================================================
# Lớp 1: danh sách chặn. Được so trên chuỗi đã **bỏ dấu + bỏ khoảng trắng**, nên
# "D r . B e e", "DR.BEE", "dr bee", "drbee" đều khớp cùng một mẫu.
_BLOCKED_TOKENS = (
    # Thương hiệu / sản phẩm
    "drbee",
    "doctorbee",
    "duocmypham",
    # Chào bán trực tiếp
    "khuyenmai",
    "uudai",
    "giamgia",
    "saleoff",
    "muangay",
    "dathang",
    "chotdon",
    # "inbox" là từ của người bán, không phải của người bạn tâm giao.
    "inbox",
    "delaiso",
    "lienhetuvan",
    "tuvanmienphi",
    "dangkytuvan",
    "tuvan",
    "freeship",
    "combo",
    "voucher",
    "camkethieuqua",
    "baohanh",
    # Bệnh lý / điều trị — đường gợi bán của ngành này
    "rungtoc",
    "hoitoc",
    "nangtoc",
    "dadau",
    "gaunggua",
    "dieutri",
    "phuchoitoc",
    "moctoc",
    "duoclieu",
    "thuockich",
    "serum",
    "daugoiduoc",
)

# Lớp 2: regex bắt số điện thoại, link, đơn vị tiền — chạy trên chuỗi GỐC.
_PHONE = re.compile(r"(?:\+?84|0)(?:[\s.\-]?\d){8,10}\b")
_LINK = re.compile(r"(?:https?://|www\.)\S+|\b[\w\-]+\.(?:com|vn|net|shop|store|me)\b", re.I)
_MONEY = re.compile(
    r"\d[\d.,]*\s*(?:k\b|nghìn|ngàn|tr\b|triệu|vnđ|vnd|đồng|đ\b)|giá\s*(?:chỉ|từ|là)?\s*\d",
    re.I,
)
_PRICE_WORD = re.compile(r"\b(?:giá|bao nhiêu tiền|mấy tiền|chi phí|phí)\b", re.I)


@dataclass
class SalesHit:
    """Một dấu hiệu chào bán, kèm chỗ tìm thấy."""

    seq: int
    layer: str  # "blocklist" | "regex" | "llm_judge"
    pattern: str
    excerpt: str

    def __str__(self) -> str:
        return f"tin {self.seq} [{self.layer}] “{self.pattern}” trong: {self.excerpt}"


@dataclass
class ZeroSalesReport:
    hits: list[SalesHit] = field(default_factory=list)
    judge_ran: bool = False
    judge_reason: str = ""

    @property
    def passed(self) -> bool:
        """Chỉ `True` khi **cả ba** lớp đều sạch (plan.md §5.6)."""
        return not self.hits and self.judge_ran

    @property
    def sales_check(self) -> str:
        return ZERO_SALES_CONFIRMED if self.passed else SALES_CHECK_FAILED

    def feedback(self) -> str:
        if not self.hits:
            return ""
        lines = "\n".join(f"- {hit}" for hit in self.hits)
        return (
            "Lượt trước có dấu hiệu chào bán. Viết lại, tuyệt đối không nhắc "
            f"thương hiệu, sản phẩm, giá, bệnh lý, điều trị, link hay số điện thoại:\n{lines}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "judge_ran": self.judge_ran,
            "judge_reason": self.judge_reason,
            "hits": [
                {"seq": h.seq, "layer": h.layer, "pattern": h.pattern, "excerpt": h.excerpt}
                for h in self.hits
            ],
        }


def strip_diacritics(text: str) -> str:
    """Bỏ dấu tiếng Việt: "điều trị" → "dieu tri"."""
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def squash(text: str) -> str:
    """Bỏ dấu, hạ chữ thường, **xoá mọi thứ không phải chữ/số**.

    Đây là mấu chốt bắt được "D r . B e e", "d-r-b-e-e", "DR_BEE": kẻ cố lách
    bằng cách chèn ký tự phân cách thì sau khi squash vẫn ra `drbee`.
    """
    return re.sub(r"[^a-z0-9]", "", strip_diacritics(text).lower())


def check_blocklist(messages: list[str]) -> list[SalesHit]:
    hits: list[SalesHit] = []
    for seq, message in enumerate(messages, 1):
        squashed = squash(message)
        for token in _BLOCKED_TOKENS:
            if token in squashed:
                hits.append(SalesHit(seq, "blocklist", token, _excerpt(message)))
                break  # một tin bẩn là đủ, không cần liệt kê hết
    return hits


def check_regex(messages: list[str]) -> list[SalesHit]:
    hits: list[SalesHit] = []
    for seq, message in enumerate(messages, 1):
        for label, pattern in (
            ("số điện thoại", _PHONE),
            ("link", _LINK),
            ("đơn vị tiền", _MONEY),
            ("từ chỉ giá", _PRICE_WORD),
        ):
            if match := pattern.search(message):
                hits.append(SalesHit(seq, "regex", label, _excerpt(message, match.group(0))))
                break
    return hits


async def judge_sales_with_llm(
    messages: list[str], gateway: LLMGateway, *, model: str
) -> tuple[bool, str]:
    """Lớp 3: hỏi model "đoạn này có ý bán hàng không?".

    Chạy **sau** hai lớp cơ học. Lỗi gọi model → trả `(False, …)`: không xác
    nhận được thì **không** được coi là đã xác nhận (luật L2).
    """
    from app.prompts import render as render_prompt

    numbered = "\n".join(f"{i}. {m}" for i, m in enumerate(messages, 1))
    payload = wire.build_payload(
        [wire.text_part(render_prompt("zero_sales_judge", messages=numbered))],
        temperature=0.0,
        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
    )
    try:
        raw = await gateway.generate_content(payload, model=model)
        body = parse_object(wire.extract_text(raw))
    except GatewayError as exc:
        return False, f"Không chạy được LLM judge: {exc.message}"

    verdict = str(body.get("verdict", "")).strip().upper()
    reason = " ".join(str(body.get("reason", "")).split())[:300]
    if verdict == "NO":
        return True, reason
    if verdict == "YES":
        return False, reason or "LLM judge cho rằng có ý bán hàng."
    return False, f"LLM judge trả verdict lạ: {verdict!r}"


async def validate_zero_sales(
    messages: list[str], gateway: LLMGateway | None = None, *, model: str = ""
) -> ZeroSalesReport:
    """Chạy cả ba lớp. `passed=True` chỉ khi cả ba sạch."""
    report = ZeroSalesReport()
    report.hits.extend(check_blocklist(messages))
    report.hits.extend(check_regex(messages))

    # Bẩn rồi thì khỏi tốn một lần gọi model.
    if report.hits:
        report.judge_reason = "Bỏ qua LLM judge vì đã bị hai lớp cơ học bắt."
        return report

    if gateway is None or not model:
        report.judge_reason = (
            "Chưa chạy LLM judge (thiếu cổng/model) nên KHÔNG xác nhận ZERO_SALES."
        )
        return report

    ok, reason = await judge_sales_with_llm(messages, gateway, model=model)
    report.judge_ran = ok
    report.judge_reason = reason
    if not ok:
        report.hits.append(SalesHit(0, "llm_judge", "có ý bán hàng", reason[:160]))
    return report


# ===========================================================================
# GroundingValidator — luật L1
# ===========================================================================
# Câu chung không ràng buộc dữ kiện — danh sách trắng (plan.md §5.6.4).
_GENERIC_WHITELIST = {
    squash(phrase)
    for phrase in (
        "buổi tối an lành",
        "ngày nhẹ nhàng",
        "ngủ ngon",
        "giữ sức khoẻ",
        "bình yên",
        "mình luôn ở đây",
        "có gì cứ kể nhé",
        "không cần trả lời ngay",
        "chúc bạn",
        "cảm ơn bạn",
    )
}

# Thực thể cần có bằng chứng: quan hệ gia đình, nghề, địa danh, con số.
_FAMILY_TERMS = (
    "con trai",
    "con gái",
    "con bé",
    "thằng bé",
    "bé trai",
    "bé gái",
    "các bé",
    "hai bé",
    "ba bé",
    "cháu",
    "chồng",
    "vợ",
    "bà ngoại",
    "bà nội",
    "ông ngoại",
    "ông nội",
    "mẹ chồng",
    "bố chồng",
)
_JOB_TERMS = (
    "công ty",
    "văn phòng",
    "giáo viên",
    "y tá",
    "bác sĩ",
    "kế toán",
    "kinh doanh",
    "bán hàng",
    "shop",
    "cửa hàng",
    "doanh nhân",
    "nhân viên",
    "quản lý",
    "giám đốc",
)
# Địa danh phổ biến ở Việt Nam — chỉ cần một mẫu đủ rộng để bắt việc bịa chỗ ở.
_PLACE_TERMS = (
    "hà nội",
    "sài gòn",
    "hồ chí minh",
    "đà nẵng",
    "hải phòng",
    "cần thơ",
    "nha trang",
    "huế",
    "đà lạt",
    "vũng tàu",
    "bình dương",
    "quê",
)
_NUMBER = re.compile(r"\b\d+\b")


@dataclass
class UngroundedClaim:
    seq: int
    kind: str  # "gia đình" | "nghề nghiệp" | "địa danh" | "con số"
    term: str
    excerpt: str

    def __str__(self) -> str:
        return f"tin {self.seq} nhắc {self.kind} “{self.term}” mà bằng chứng không có"


@dataclass
class GroundingReport:
    ungrounded_claims: list[UngroundedClaim] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.ungrounded_claims

    def feedback(self) -> str:
        if not self.ungrounded_claims:
            return ""
        lines = "\n".join(f"- {claim}" for claim in self.ungrounded_claims)
        return (
            "Lượt trước nhắc những dữ kiện KHÔNG có trong bằng chứng. Viết lại và "
            f"bỏ hẳn chúng, chỉ dùng đúng những gì bằng chứng nói:\n{lines}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "ungrounded_claims": [
                {"seq": c.seq, "kind": c.kind, "term": c.term, "excerpt": c.excerpt}
                for c in self.ungrounded_claims
            ],
        }


#: Cache regex cho mỗi term — dựng regex 44 lần cho mỗi tin nhắn là lãng phí.
_TERM_PATTERNS: dict[str, re.Pattern[str]] = {}


def _term_pattern(term: str) -> re.Pattern[str]:
    """Regex khớp `term` như **một từ trọn vẹn**, không phải chuỗi con.

    Vì sao không dùng `squash()` ở đây (task.md I-62, đo thật): `squash` **xoá cả
    dấu cách**, nên cả câu dính liền thành một chuỗi và mọi ranh giới từ biến
    mất. Hậu quả đo được:

        squash("vợ")                       -> "vo"
        squash("… trò chuyện với bạn.")    -> "…trochuyenvoiban"
        "vo" in "…voiban"                  -> True   ← BÁO ĐỘNG GIẢ

    Tức **mọi** tin nhắn chứa chữ "với" đều bị gán là nhắc "vợ". Đó là một trong
    những từ phổ biến nhất tiếng Việt, nên validator gần như luôn đỏ và cả
    pipeline rơi vào `FAILED_VALIDATION` dù nội dung hoàn toàn sạch.

    `squash` **vẫn đúng** cho blocklist chống lách ("D r . B e e" → "drbee") —
    ở đó xoá ranh giới từ chính là mục đích. Dùng lại nó cho việc đối chiếu thực
    thể mới là sai chỗ.

    Khớp trên bản **còn dấu**: tiếng Việt viết đúng luôn có dấu, và giữ dấu giúp
    phân biệt "vợ" với "vô"/"với". Ranh giới dùng lookaround trên ký tự chữ để
    "mẹ chồng" vẫn khớp được như một cụm.
    """
    cached = _TERM_PATTERNS.get(term)
    if cached is None:
        escaped = re.escape(term.lower().strip())
        cached = re.compile(rf"(?<![^\W\d_]){escaped}(?![^\W\d_])", re.IGNORECASE)
        _TERM_PATTERNS[term] = cached
    return cached


def mentions_term(text: str, term: str) -> bool:
    """`term` có xuất hiện trong `text` như một từ trọn vẹn không?"""
    return _term_pattern(term).search(text.lower()) is not None


def validate_grounding(messages: list[str], evidence_corpus: str) -> GroundingReport:
    """Mọi thực thể trong tin nhắn phải khớp một chuỗi trong bằng chứng.

    Chỉ soi bốn loại thực thể *kiểm chứng được*: quan hệ gia đình, nghề nghiệp,
    địa danh, con số. Soi mọi danh từ sẽ bắt oan gần hết câu tiếng Việt và vòng
    sinh lại không bao giờ dừng.
    """
    report = GroundingReport()

    for seq, message in enumerate(messages, 1):
        for kind, terms in (
            ("gia đình", _FAMILY_TERMS),
            ("nghề nghiệp", _JOB_TERMS),
            ("địa danh", _PLACE_TERMS),
        ):
            for term in terms:
                if mentions_term(message, term) and not mentions_term(evidence_corpus, term):
                    report.ungrounded_claims.append(
                        UngroundedClaim(seq, kind, term, _excerpt(message, term))
                    )

        for number in _NUMBER.findall(message):
            if number in evidence_corpus:
                continue
            if _is_in_whitelisted_phrase(message, number):
                continue
            report.ungrounded_claims.append(
                UngroundedClaim(seq, "con số", number, _excerpt(message, number))
            )

    return report


def _is_in_whitelisted_phrase(message: str, fragment: str) -> bool:
    squashed = squash(message)
    return any(phrase in squashed for phrase in _GENERIC_WHITELIST) and len(fragment) <= 2


def _excerpt(message: str, needle: str = "", *, width: int = 60) -> str:
    if not needle:
        return message[:width]
    index = message.lower().find(needle.lower())
    if index == -1:
        return message[:width]
    start = max(0, index - width // 2)
    return message[start : start + width]
