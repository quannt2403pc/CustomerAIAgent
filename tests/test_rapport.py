"""D1.16 — sinh chuỗi 5–10 tin nhắn + góc thấu cảm.

Ràng buộc văn phong (plan.md §5.4) được kiểm **bằng code** chứ không chỉ nhờ
prompt — đó là điều test ở đây canh gác.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import GatewayBadResponse, GatewayRateLimited
from app.services.profiler import Demographics, ProfileResult
from app.services.rapport import (
    DEFAULT_MESSAGES,
    MAX_MESSAGES,
    MIN_MESSAGES,
    check_style,
    clamp_message_count,
    generate_empathy_angle,
    generate_sequence,
    style_feedback,
)

EVIDENCE = (
    'Nguyễn Thị Lan\n<meta property="og:title" content="Nguyễn Thị Lan">\n'
    "Mẹ hai bé, bán hàng online tại Hà Nội."
)

ANGLE_REPLY = json.dumps(
    {
        "core_empathy_angle": "Ghi nhận sự tần tảo của một người mẹ vừa chăm con vừa buôn bán.",
        "grounded_in": "Mẹ hai bé, bán hàng online tại Hà Nội.",
    },
    ensure_ascii=False,
)


def good_messages(n: int = 10) -> list[str]:
    base = [
        "Chào Lan, mình thấy ảnh đại diện của bạn trông thật ấm áp.",
        "Nhìn ảnh là đoán được nhà mình lúc nào cũng rộn ràng tiếng trẻ con.",
        "Mình hiểu cái cảm giác vừa trông con vừa lo đơn hàng, đầu lúc nào cũng chạy.",
        "Những ngày như vậy mà vẫn giữ được nét tươi tỉnh là đáng quý lắm.",
        "Mình cũng từng có quãng vừa làm vừa trông cháu, tối nào cũng gục xuống là ngủ.",
        "Hồi đó mình học được một điều: cứ cho mình nghỉ mười phút là lại đi tiếp được.",
        "Hôm nay của bạn thế nào rồi.",
        "Bạn thường xả hơi bằng cách gì sau một ngày dài.",
        "Mình để tin ở đây, có gì cứ kể nhé.",
        "Không cần trả lời ngay đâu, lúc nào rảnh thì nhắn lại cũng được.",
    ]
    return base[:n]


class ScriptedGateway:
    provider = "antigravity"

    def __init__(self, replies: list[str | Exception]):
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def generate_content(self, payload, *, model):
        self.prompts.append(payload["contents"][0]["parts"][0]["text"])
        reply = self._replies.pop(0) if self._replies else ""
        if isinstance(reply, Exception):
            raise reply
        return {
            "candidates": [{"content": {"parts": [{"text": reply}]}}],
            "usageMetadata": {"promptTokenCount": 900, "totalTokenCount": 1600},
        }


@pytest.fixture
def profile() -> ProfileResult:
    return ProfileResult(
        status="SUCCESS",
        customer_name="Nguyễn Thị Lan",
        visual_context="Một người trưởng thành bế một em bé bên bánh sinh nhật.",
        demographics=Demographics(gender="Nữ", estimated_age_range="28 - 38 tuổi"),
    )


def messages_reply(items: list[str]) -> str:
    return json.dumps({"messages": items}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Số lượng tin
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "asked, expected",
    [(None, DEFAULT_MESSAGES), (10, 10), (5, 5), (7, 7), (1, MIN_MESSAGES), (99, MAX_MESSAGES)],
)
def test_message_count_is_clamped_to_the_brief_range(asked, expected) -> None:
    assert clamp_message_count(asked) == expected


async def test_generates_exactly_the_requested_count(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(good_messages(7))])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m", n_messages=7)

    assert len(result.messages) == 7


async def test_default_is_ten_to_match_dialogue_sequence_10(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(good_messages(10))])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m")

    assert len(result.messages) == 10


async def test_extra_messages_are_trimmed(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply([*good_messages(10), "thừa"])])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m", n_messages=10)

    assert len(result.messages) == 10
    assert "thừa" not in result.messages


async def test_too_few_messages_is_an_error_not_a_silent_pass(profile) -> None:
    """Đề bài yêu cầu 5–10 tin. Trả 3 tin là không đạt đặc tả, phải nổ."""
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(good_messages(3))])

    with pytest.raises(GatewayBadResponse, match="ít nhất"):
        await generate_sequence(profile, EVIDENCE, gateway, model="m")


# ---------------------------------------------------------------------------
# Góc thấu cảm
# ---------------------------------------------------------------------------
async def test_empathy_angle_comes_with_its_grounding(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY])

    angle, grounded = await generate_empathy_angle(profile, EVIDENCE, gateway, model="m")

    assert "tần tảo" in angle
    assert grounded in EVIDENCE  # trích đúng đoạn bằng chứng thật


async def test_empathy_failure_does_not_block_the_sequence(profile) -> None:
    """Thiếu góc thấu cảm vẫn phải sinh được tin — prompt có nhánh dự phòng."""
    gateway = ScriptedGateway([GatewayRateLimited(), messages_reply(good_messages())])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m")

    assert result.empathy_angle is None
    assert len(result.messages) == 10


async def test_angle_is_passed_into_the_sequence_prompt(profile) -> None:
    gateway = ScriptedGateway([messages_reply(good_messages())])

    await generate_sequence(
        profile,
        EVIDENCE,
        gateway,
        model="m",
        empathy_angle="Góc thấu cảm đã chọn trước",
    )

    assert "Góc thấu cảm đã chọn trước" in gateway.prompts[0]


# ---------------------------------------------------------------------------
# Văn phong — kiểm bằng code
# ---------------------------------------------------------------------------
def test_clean_messages_have_no_issues() -> None:
    assert check_style(good_messages()) == []


def test_message_over_220_chars_is_flagged() -> None:
    issues = check_style(["a" * 221])
    assert len(issues) == 1
    assert "220" in issues[0].rule
    assert issues[0].seq == 1


def test_message_at_exactly_220_chars_is_fine() -> None:
    assert check_style(["a" * 220]) == []


def test_two_emoji_in_one_message_is_flagged() -> None:
    issues = check_style(["Chào bạn nhé 🌸🌼"])
    assert any("emoji" in i.rule for i in issues)


def test_one_emoji_is_allowed() -> None:
    assert check_style(["Chào bạn nhé 🌸"]) == []


def test_two_questions_in_one_message_is_flagged() -> None:
    """plan.md §5.4: không hỏi dồn 2 câu hỏi trong 1 tin."""
    issues = check_style(["Hôm nay bạn thế nào? Có mệt không?"])
    assert any("hỏi dồn" in i.rule for i in issues)


def test_one_question_is_allowed() -> None:
    assert check_style(["Hôm nay của bạn thế nào?"]) == []


@pytest.mark.parametrize("pronoun", ["chúng tôi", "bên mình", "shop", "cửa hàng", "công ty"])
def test_seller_pronouns_are_flagged(pronoun: str) -> None:
    issues = check_style([f"Chào bạn, {pronoun} rất vui được nói chuyện."])
    assert any("người bán" in i.rule for i in issues)


@pytest.mark.parametrize("praise", ["xinh quá", "đẹp quá", "ngưỡng mộ", "hoàn hảo"])
def test_hollow_praise_is_flagged(praise: str) -> None:
    issues = check_style([f"Ôi bạn {praise} đi."])
    assert any("sáo rỗng" in i.rule for i in issues)


def test_issue_reports_which_message_is_wrong() -> None:
    issues = check_style(["ổn", "a" * 300, "ổn"])
    assert [i.seq for i in issues] == [2]


async def test_style_issues_are_reported_not_hidden(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(["x" * 300, *good_messages(9)])])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m")

    assert result.style_ok is False
    assert result.style_issues[0].seq == 1


def test_style_feedback_names_each_violation() -> None:
    issues = check_style(["a" * 300, "Chào bạn, shop rất vui."])
    feedback = style_feedback(issues)
    assert "tin 1" in feedback
    assert "tin 2" in feedback


def test_style_feedback_is_empty_when_clean() -> None:
    assert style_feedback([]) == ""


# ---------------------------------------------------------------------------
# Không tự đặt cờ zero-sales
# ---------------------------------------------------------------------------
async def test_rapport_result_has_no_sales_check_field(profile) -> None:
    """Chỉ `ZeroSalesValidator` được đặt `ZERO_SALES_CONFIRMED` (luật L2).

    Nếu module này mang theo một cờ như vậy thì sẽ có đường đặt cờ mà chưa
    qua kiểm duyệt.
    """
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(good_messages())])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m")

    assert not hasattr(result, "sales_check")
    assert "ZERO_SALES_CONFIRMED" not in json.dumps(result.__dict__, default=str)


# ---------------------------------------------------------------------------
# Prompt — luật thép có mặt trong chỉ dẫn
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "forbidden_topic",
    ["KHÔNG CHÀO BÁN", "tóc", "da đầu", "KHÔNG bịa dữ kiện", "220 ký tự", "MỘT dấu hỏi"],
)
async def test_sequence_prompt_states_the_iron_rules(profile, forbidden_topic: str) -> None:
    gateway = ScriptedGateway([messages_reply(good_messages())])

    await generate_sequence(profile, EVIDENCE, gateway, model="m", empathy_angle="x")

    assert forbidden_topic in gateway.prompts[0]


async def test_extra_instruction_is_appended_for_regeneration(profile) -> None:
    gateway = ScriptedGateway([messages_reply(good_messages())])

    await generate_sequence(
        profile,
        EVIDENCE,
        gateway,
        model="m",
        empathy_angle="x",
        extra_instruction="Bỏ câu nhắc giá ở tin 4.",
    )

    assert "Bỏ câu nhắc giá ở tin 4." in gateway.prompts[0]
    assert "SỬA LỖI LƯỢT TRƯỚC" in gateway.prompts[0]


async def test_evidence_is_the_only_source_offered_to_the_model(profile) -> None:
    gateway = ScriptedGateway([messages_reply(good_messages())])

    await generate_sequence(profile, EVIDENCE, gateway, model="m", empathy_angle="x")

    prompt = gateway.prompts[0]
    assert EVIDENCE in prompt
    assert profile.visual_context in prompt


async def test_missing_evidence_is_stated_not_hidden(profile) -> None:
    profile.visual_context = None
    gateway = ScriptedGateway([messages_reply(good_messages())])

    await generate_sequence(profile, "", gateway, model="m", empathy_angle="x")

    prompt = gateway.prompts[0]
    assert "(không có bằng chứng văn bản)" in prompt
    assert "(không có mô tả ảnh)" in prompt


async def test_usage_and_latency_are_recorded(profile) -> None:
    gateway = ScriptedGateway([ANGLE_REPLY, messages_reply(good_messages())])

    result = await generate_sequence(profile, EVIDENCE, gateway, model="m")

    assert result.usage == {"prompt_tokens": 900, "total_tokens": 1600}
    assert result.latency_ms is not None
