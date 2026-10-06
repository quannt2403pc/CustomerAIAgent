"""D1.17 — hai validator canh giữ luật L1 và L2.

Mục tiêu test: chứng minh **không có đường nào** đặt được
`ZERO_SALES_CONFIRMED` mà chưa qua cả ba lớp, và mọi dữ kiện bịa đều bị bắt.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import GatewayRateLimited
from app.services.validators import (
    SALES_CHECK_FAILED,
    ZERO_SALES_CONFIRMED,
    GroundingReport,
    ZeroSalesReport,
    check_blocklist,
    check_regex,
    squash,
    strip_diacritics,
    validate_grounding,
    validate_zero_sales,
)

EVIDENCE = (
    "Nguyễn Thị Lan\n"
    '<meta property="og:title" content="Nguyễn Thị Lan">\n'
    "Mẹ hai bé, bán hàng online tại Hà Nội.\n"
    "Một người trưởng thành bế một em bé bên bánh sinh nhật."
)

CLEAN_MESSAGES = [
    "Chào Lan, ảnh đại diện của bạn trông thật ấm áp.",
    "Nhìn ảnh là thấy nhà mình lúc nào cũng rộn ràng.",
    "Mình hiểu cảm giác vừa trông con vừa lo đơn hàng.",
    "Mình để tin ở đây, có gì cứ kể nhé.",
    "Chúc bạn buổi tối an lành.",
]


class JudgeGateway:
    """Gateway giả chỉ phục vụ LLM judge."""

    provider = "antigravity"

    def __init__(self, verdict: str = "NO", reason: str = "chỉ hỏi thăm", error=None):
        self._body = json.dumps({"verdict": verdict, "reason": reason}, ensure_ascii=False)
        self._error = error
        self.calls = 0
        self.prompts: list[str] = []

    async def generate_content(self, payload, *, model):
        self.calls += 1
        self.prompts.append(payload["contents"][0]["parts"][0]["text"])
        if self._error is not None:
            raise self._error
        return {"candidates": [{"content": {"parts": [{"text": self._body}]}}]}


# ===========================================================================
# Chuẩn hoá chuỗi — mấu chốt chống lách
# ===========================================================================
def test_strip_diacritics_handles_vietnamese() -> None:
    assert strip_diacritics("điều trị") == "dieu tri"
    assert strip_diacritics("Đỗ Quyên") == "Do Quyen"


@pytest.mark.parametrize(
    "variant",
    ["Dr.Bee", "dr bee", "DR BEE", "D r . B e e", "d-r-b-e-e", "DRBEE", "dR_bEe", "Dr . Bee"],
)
def test_all_brand_spellings_squash_to_one_token(variant: str) -> None:
    """Chèn ký tự phân cách là cách lách hiển nhiên nhất — squash vô hiệu hoá nó."""
    assert squash(variant) == "drbee"


# ===========================================================================
# Lớp 1 — danh sách chặn (DoD D1.17)
# ===========================================================================
@pytest.mark.parametrize(
    "message",
    [
        "Chị dùng Dr.Bee chưa ạ",
        "bên dr bee có sản phẩm này",
        "D r . B e e xin chào chị",
        "DRBEE kính chào",
        "sản phẩm dược mỹ phẩm rất tốt",
        "đang có khuyến mãi lớn",
        "chị mua ngay hôm nay nhé",
        "inbox để lại số em gọi lại",
        "để lại số điện thoại nhé chị",
        "liên hệ tư vấn miễn phí",
        "em tư vấn cho chị nhé",
        "cam kết hiệu quả sau 2 tuần",
        "chị bị rụng tóc nhiều không",
        "da đầu chị có bị ngứa không",
        "liệu trình điều trị này rất tốt",
        "giúp phục hồi tóc nhanh",
        "serum này dùng tốt lắm",
    ],
)
def test_blocklist_catches_sales_language(message: str) -> None:
    assert check_blocklist([message]), f"không bắt được: {message!r}"


@pytest.mark.parametrize("message", CLEAN_MESSAGES)
def test_blocklist_leaves_friendly_messages_alone(message: str) -> None:
    assert check_blocklist([message]) == []


def test_every_blocked_token_is_already_squashed() -> None:
    """Token chưa squash sẽ **không bao giờ** khớp — một luật chết, âm thầm vô dụng."""
    from app.services.validators import _BLOCKED_TOKENS

    dead = [token for token in _BLOCKED_TOKENS if squash(token) != token]
    assert not dead, f"token không ở dạng squash nên vô hiệu: {dead}"


# ===========================================================================
# Lớp 2 — regex (DoD D1.17)
# ===========================================================================
@pytest.mark.parametrize(
    "message, label",
    [
        ("giá chỉ 299k thôi chị", "đơn vị tiền"),
        ("chỉ 1.200.000 đồng", "đơn vị tiền"),
        ("khoảng 2 triệu nhé", "đơn vị tiền"),
        ("giá 500000 vnđ", "đơn vị tiền"),
        ("gọi em 0912345678 nhé", "số điện thoại"),
        ("số của em 0912 345 678", "số điện thoại"),
        ("xem tại https://shop.example.com", "link"),
        ("vào www.example.vn nha", "link"),
        ("truy cập example.com", "link"),
        ("chi phí thế nào ạ", "từ chỉ giá"),
        ("cái này bao nhiêu tiền", "từ chỉ giá"),
    ],
)
def test_regex_catches_phone_link_and_money(message: str, label: str) -> None:
    hits = check_regex([message])
    assert hits, f"không bắt được: {message!r}"
    assert hits[0].pattern == label


@pytest.mark.parametrize("message", CLEAN_MESSAGES)
def test_regex_leaves_friendly_messages_alone(message: str) -> None:
    assert check_regex([message]) == []


# ===========================================================================
# Ba lớp hợp lại — cửa duy nhất đặt ZERO_SALES_CONFIRMED
# ===========================================================================
async def test_all_three_layers_clean_gives_confirmed() -> None:
    gateway = JudgeGateway(verdict="NO")

    report = await validate_zero_sales(CLEAN_MESSAGES, gateway, model="m")

    assert report.passed is True
    assert report.sales_check == ZERO_SALES_CONFIRMED
    assert gateway.calls == 1


async def test_mechanical_layer_failure_skips_the_judge() -> None:
    """Bẩn rồi thì khỏi tốn một lần gọi model."""
    gateway = JudgeGateway(verdict="NO")

    report = await validate_zero_sales(["giá chỉ 299k"], gateway, model="m")

    assert report.passed is False
    assert report.sales_check == SALES_CHECK_FAILED
    assert gateway.calls == 0


async def test_judge_saying_yes_blocks_confirmation() -> None:
    gateway = JudgeGateway(verdict="YES", reason="gợi mở về vấn đề cần giải pháp")

    report = await validate_zero_sales(CLEAN_MESSAGES, gateway, model="m")

    assert report.passed is False
    assert any(hit.layer == "llm_judge" for hit in report.hits)


async def test_judge_unreachable_means_not_confirmed() -> None:
    """Không xác nhận được thì **không** được coi là đã xác nhận (luật L2)."""
    gateway = JudgeGateway(error=GatewayRateLimited())

    report = await validate_zero_sales(CLEAN_MESSAGES, gateway, model="m")

    assert report.passed is False
    assert report.sales_check == SALES_CHECK_FAILED


async def test_no_gateway_means_not_confirmed() -> None:
    """Gọi validator mà không truyền cổng cũng không được tự xác nhận."""
    report = await validate_zero_sales(CLEAN_MESSAGES)

    assert report.passed is False
    assert "KHÔNG xác nhận" in report.judge_reason


async def test_judge_with_unexpected_verdict_is_not_confirmed() -> None:
    gateway = JudgeGateway(verdict="CÓ THỂ")

    report = await validate_zero_sales(CLEAN_MESSAGES, gateway, model="m")

    assert report.passed is False
    assert "verdict lạ" in report.judge_reason


def test_empty_report_is_not_confirmed_by_default() -> None:
    """Mặc định của `ZeroSalesReport` phải là CHƯA xác nhận.

    Nếu mặc định là đã-xác-nhận thì một đường code quên gọi validator sẽ âm
    thầm đặt cờ sạch.
    """
    assert ZeroSalesReport().passed is False
    assert ZeroSalesReport().sales_check == SALES_CHECK_FAILED


async def test_feedback_names_the_offending_message() -> None:
    report = await validate_zero_sales(["ổn", "giá chỉ 299k", "ổn"])

    feedback = report.feedback()
    assert "tin 2" in feedback
    assert "299k" in feedback


async def test_judge_prompt_includes_numbered_messages() -> None:
    gateway = JudgeGateway(verdict="NO")

    await validate_zero_sales(CLEAN_MESSAGES, gateway, model="m")

    prompt = gateway.prompts[0]
    assert "1. " in prompt
    assert CLEAN_MESSAGES[0] in prompt
    # Khi không chắc thì phải trả YES — bỏ sót tệ hơn viết lại.
    assert "Trả YES" in prompt


# ===========================================================================
# GroundingValidator — luật L1 (DoD D1.17)
# ===========================================================================
def test_clean_messages_are_grounded() -> None:
    report = validate_grounding(CLEAN_MESSAGES, EVIDENCE)
    assert report.passed is True


def test_invented_child_is_caught() -> None:
    """DoD: nhắc "bé trai 3 tuổi" khi evidence không có → ungrounded_claims."""
    report = validate_grounding(["Bé trai 3 tuổi của bạn chắc nghịch lắm."], EVIDENCE)

    assert report.passed is False
    kinds = {claim.kind for claim in report.ungrounded_claims}
    assert "gia đình" in kinds


def test_invented_number_is_caught() -> None:
    report = validate_grounding(["Hai bạn cưới nhau 12 năm rồi nhỉ."], EVIDENCE)
    assert any(claim.kind == "con số" for claim in report.ungrounded_claims)


def test_invented_job_is_caught() -> None:
    report = validate_grounding(["Công việc ở công ty dạo này ổn không."], EVIDENCE)
    assert any(claim.kind == "nghề nghiệp" for claim in report.ungrounded_claims)


def test_invented_place_is_caught() -> None:
    report = validate_grounding(["Đà Nẵng dạo này trời thế nào."], EVIDENCE)
    assert any(claim.kind == "địa danh" for claim in report.ungrounded_claims)


def test_facts_present_in_evidence_are_allowed() -> None:
    """ "Hà Nội" và "bán hàng" CÓ trong evidence → không được bắt oan."""
    report = validate_grounding(
        ["Hà Nội dạo này trở lạnh rồi.", "Việc bán hàng của bạn dạo này thế nào."], EVIDENCE
    )
    assert report.passed is True


def test_family_term_present_in_evidence_is_allowed() -> None:
    report = validate_grounding(["Hai bé nhà bạn chắc lớn nhanh lắm."], EVIDENCE)
    assert report.passed is True


def test_generic_wishes_are_whitelisted() -> None:
    """plan.md §5.6.4: câu chung không ràng buộc dữ kiện được đi qua."""
    report = validate_grounding(
        ["Chúc bạn buổi tối an lành.", "Mình luôn ở đây, có gì cứ kể nhé."], EVIDENCE
    )
    assert report.passed is True


def test_report_says_which_message_and_what_term() -> None:
    report = validate_grounding(["ổn", "Con gái bạn học lớp mấy rồi."], EVIDENCE)

    claim = report.ungrounded_claims[0]
    assert claim.seq == 2
    assert "con gái" in claim.term


def test_grounding_feedback_lists_each_claim() -> None:
    report = validate_grounding(["Con trai bạn ở Đà Nẵng chắc vui."], EVIDENCE)

    feedback = report.feedback()
    assert "con trai" in feedback
    assert "đà nẵng" in feedback.lower()


def test_empty_evidence_flags_every_entity() -> None:
    report = validate_grounding(["Con gái bạn ở Hà Nội thế nào."], "")
    assert len(report.ungrounded_claims) >= 2


def test_empty_grounding_report_passes() -> None:
    """Ngược với ZeroSales: không có claim nào tức là không có gì bịa."""
    assert GroundingReport().passed is True


def test_reports_serialise_for_the_database() -> None:
    sales = ZeroSalesReport()
    grounding = validate_grounding(["Con gái bạn thế nào."], EVIDENCE)

    assert json.dumps(sales.to_dict(), ensure_ascii=False)
    assert json.dumps(grounding.to_dict(), ensure_ascii=False)
    assert grounding.to_dict()["ungrounded_claims"]


# ===========================================================================
# Vòng sinh lại ≤2 (DoD D1.17)
# ===========================================================================
class SequenceGateway:
    """Trả lần lượt: [angle, messages] cho mỗi lượt, rồi verdict cho judge."""

    provider = "antigravity"

    def __init__(self, rounds: list[list[str]], judge_verdict: str = "NO"):
        self._rounds = [list(r) for r in rounds]
        self._judge = json.dumps({"verdict": judge_verdict, "reason": "ok"})
        self.sequence_calls = 0
        self.judge_calls = 0
        self.instructions: list[str] = []

    async def generate_content(self, payload, *, model):
        prompt = payload["contents"][0]["parts"][0]["text"]
        if "người kiểm duyệt nội dung" in prompt:
            self.judge_calls += 1
            return {"candidates": [{"content": {"parts": [{"text": self._judge}]}}]}
        if "góc thấu cảm chính" in prompt:
            body = json.dumps(
                {"core_empathy_angle": "Ghi nhận sự tần tảo", "grounded_in": "Mẹ hai bé"},
                ensure_ascii=False,
            )
            return {"candidates": [{"content": {"parts": [{"text": body}]}}]}

        self.sequence_calls += 1
        self.instructions.append(prompt)
        messages = self._rounds.pop(0) if self._rounds else CLEAN_MESSAGES
        body = json.dumps({"messages": messages}, ensure_ascii=False)
        return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


DIRTY = [*CLEAN_MESSAGES[:4], "Chị dùng Dr.Bee chưa, giá chỉ 299k thôi."]
UNGROUNDED = [*CLEAN_MESSAGES[:4], "Bé trai 3 tuổi của bạn chắc nghịch lắm."]


async def test_clean_first_try_needs_no_regeneration(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([CLEAN_MESSAGES])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.passed is True
    assert result.attempts == 1
    assert result.sales_check == ZERO_SALES_CONFIRMED
    assert gateway.sequence_calls == 1


async def test_dirty_then_clean_passes_on_the_second_try(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, CLEAN_MESSAGES])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.passed is True
    assert result.attempts == 2
    assert result.messages == CLEAN_MESSAGES
    assert result.rejected_reasons  # lưu lại vì sao lượt 1 bị loại


async def test_regeneration_is_told_exactly_what_was_wrong(profile_fixture) -> None:
    """Sinh lại với prompt y nguyên chỉ là hy vọng vào xác suất."""
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, CLEAN_MESSAGES])

    await generate_validated_sequence(profile_fixture, EVIDENCE, gateway, model="m", n_messages=5)

    second_prompt = gateway.instructions[1]
    assert "SỬA LỖI LƯỢT TRƯỚC" in second_prompt
    assert "drbee" in second_prompt or "299k" in second_prompt


async def test_ungrounded_claim_triggers_regeneration(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([UNGROUNDED, CLEAN_MESSAGES])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.attempts == 2
    assert "bé trai" in gateway.instructions[1].lower()


async def test_three_dirty_rounds_fail_closed_with_no_content(profile_fixture) -> None:
    """DoD: hết 2 lượt sinh lại vẫn fail → FAILED_VALIDATION, KHÔNG trả nội dung bẩn."""
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, DIRTY, DIRTY])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.passed is False
    assert result.attempts == 3  # 1 lượt đầu + 2 lượt sinh lại
    assert result.messages == []  # nội dung bẩn KHÔNG rời khỏi pipeline
    assert result.sales_check == SALES_CHECK_FAILED
    assert len(result.rejected_reasons) == 3


async def test_dirty_content_is_not_reachable_through_the_report(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, DIRTY, DIRTY])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert "Dr.Bee" not in json.dumps(result.messages, ensure_ascii=False)
    assert "299k" not in json.dumps(result.messages, ensure_ascii=False)


async def test_attempt_count_never_exceeds_the_cap(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY] * 10)

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5, max_attempts=2
    )

    assert gateway.sequence_calls == 3
    assert result.attempts == 3


async def test_empathy_angle_is_reused_across_retries(profile_fixture) -> None:
    """Sinh lại chỉ cần sửa *cách viết*, không cần đổi *góc nhìn*."""
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, CLEAN_MESSAGES])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.empathy_angle == "Ghi nhận sự tần tảo"
    assert "Ghi nhận sự tần tảo" in gateway.instructions[1]


async def test_report_for_db_is_json_serialisable(profile_fixture) -> None:
    from app.services.pipeline import generate_validated_sequence

    gateway = SequenceGateway([DIRTY, CLEAN_MESSAGES])

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert json.dumps(result.report_for_db(), ensure_ascii=False)


@pytest.fixture
def profile_fixture():
    from app.services.profiler import Demographics, ProfileResult

    return ProfileResult(
        status="SUCCESS",
        customer_name="Nguyễn Thị Lan",
        visual_context="Một người trưởng thành bế một em bé bên bánh sinh nhật.",
        demographics=Demographics(gender="Nữ"),
    )


async def test_failed_sequence_never_claims_zero_sales(profile_fixture) -> None:
    """Đã gặp thật (I-21): chuỗi bị loại vì **grounding**, nhưng lượt cuối sạch
    về mặt bán hàng → cờ ra `ZERO_SALES_CONFIRMED` trong khi
    `dialogue_sequence_10` là `[]`.

    Xác nhận "0% chào bán" cho nội dung không tồn tại là vô nghĩa, và tệ hơn,
    nó làm người đọc tưởng nội dung đã được duyệt.
    """
    from app.services.pipeline import generate_validated_sequence

    # Ba lượt đều bịa dữ kiện (grounding fail), nhưng không chào bán.
    gateway = SequenceGateway([UNGROUNDED] * 3, judge_verdict="NO")

    result = await generate_validated_sequence(
        profile_fixture, EVIDENCE, gateway, model="m", n_messages=5
    )

    assert result.passed is False
    assert result.messages == []
    # Lớp bán hàng của lượt cuối SẠCH…
    assert result.sales_report.passed is True
    # …nhưng cờ tổng vẫn phải là FAILED.
    assert result.sales_check == SALES_CHECK_FAILED


async def test_empty_messages_never_claim_zero_sales(profile_fixture) -> None:
    from app.services.pipeline import ValidatedSequence
    from app.services.validators import ZeroSalesReport

    report = ZeroSalesReport(judge_ran=True)
    assert report.sales_check == ZERO_SALES_CONFIRMED

    # passed=True nhưng không có tin nào → vẫn không được xác nhận.
    assert (
        ValidatedSequence(passed=True, attempts=1, messages=[], sales_report=report).sales_check
        == SALES_CHECK_FAILED
    )
