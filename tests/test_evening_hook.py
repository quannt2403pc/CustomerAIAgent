"""D1.18 — câu chuyện mồi 20h.

Ba điều được canh gác: hook đi qua **cả hai** validator, `trigger_time` luôn
`"20:00"`, và không lặp ý với 7 hook gần nhất.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import GatewayRateLimited
from app.services.evening_hook import (
    RECENT_HOOKS_TO_AVOID,
    TRIGGER_TIME,
    fetch_recent_hooks,
    find_repetition,
    generate_evening_hook,
    similarity,
)
from app.services.profiler import Demographics, ProfileResult

EVIDENCE = (
    "Nguyễn Thị Lan\n"
    '<meta property="og:title" content="Nguyễn Thị Lan">\n'
    "Mẹ hai bé, bán hàng online tại Hà Nội."
)

CLEAN_HOOK = "Tối rồi, mong bữa cơm của nhà mình hôm nay thật ấm. Mình để tin ở đây nhé."
DIRTY_HOOK = "Chị ơi, Dr.Bee đang có khuyến mãi, inbox để lại số em tư vấn nhé."
UNGROUNDED_HOOK = "Bé trai 3 tuổi của chị ăn cơm tối chưa ạ."

SEVEN_OLD_HOOKS = [
    "Tối rồi, mong bữa cơm của nhà mình hôm nay thật ấm. Mình để tin ở đây nhé.",
    "Hôm nay mấy đứa nhỏ ở nhà có ngoan không, mong buổi tối của bạn dễ chịu.",
    "Ngày dài rồi, chúc bạn một tối nhẹ nhàng và ngủ thật ngon.",
    "Giờ này chắc bạn vừa dọn xong bữa tối, nhớ để mình nghỉ một chút nhé.",
    "Mong tối nay bạn có khoảng lặng cho riêng mình sau một ngày tất bật.",
    "Đơn hàng hôm nay chắc nhiều, mong bạn kịp ăn tối tử tế.",
    "Chúc bạn buổi tối an lành, có gì cứ kể mình nghe.",
]


class HookGateway:
    """Trả lần lượt các hook đã dựng; judge luôn nói NO (sạch)."""

    provider = "antigravity"

    def __init__(self, hooks: list[str | Exception], judge_verdict: str = "NO"):
        self._hooks = list(hooks)
        self._judge = json.dumps({"verdict": judge_verdict, "reason": "chỉ hỏi thăm"})
        self.hook_calls = 0
        self.prompts: list[str] = []

    async def generate_content(self, payload, *, model):
        prompt = payload["contents"][0]["parts"][0]["text"]
        if "người kiểm duyệt nội dung" in prompt:
            return {"candidates": [{"content": {"parts": [{"text": self._judge}]}}]}

        self.hook_calls += 1
        self.prompts.append(prompt)
        item = self._hooks.pop(0) if self._hooks else CLEAN_HOOK
        if isinstance(item, Exception):
            raise item
        body = json.dumps(
            {"hook": item, "grounded_in": "Mẹ hai bé, bán hàng online tại Hà Nội."},
            ensure_ascii=False,
        )
        return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


@pytest.fixture
def profile() -> ProfileResult:
    return ProfileResult(
        status="SUCCESS",
        customer_name="Nguyễn Thị Lan",
        visual_context="Một người trưởng thành bế một em bé bên bánh sinh nhật.",
        demographics=Demographics(gender="Nữ"),
    )


# ---------------------------------------------------------------------------
# trigger_time là hằng số
# ---------------------------------------------------------------------------
def test_trigger_time_is_always_2000() -> None:
    assert TRIGGER_TIME == "20:00"


async def test_output_always_carries_2000(profile) -> None:
    result = await generate_evening_hook(profile, EVIDENCE, HookGateway([CLEAN_HOOK]), model="m")
    assert result.to_output_dict()["trigger_time"] == "20:00"


async def test_failed_hook_still_reports_2000(profile) -> None:
    """Thất bại thì `evening_hook_message` là null, nhưng mốc giờ vẫn đúng đặc tả."""
    result = await generate_evening_hook(
        profile, EVIDENCE, HookGateway([DIRTY_HOOK] * 3), model="m"
    )
    out = result.to_output_dict()
    assert out["trigger_time"] == "20:00"
    assert out["evening_hook_message"] is None


# ---------------------------------------------------------------------------
# Đi qua CẢ HAI validator
# ---------------------------------------------------------------------------
async def test_clean_hook_passes(profile) -> None:
    result = await generate_evening_hook(profile, EVIDENCE, HookGateway([CLEAN_HOOK]), model="m")

    assert result.passed is True
    assert result.message == CLEAN_HOOK
    assert result.sales_report.passed is True
    assert result.grounding_report.passed is True


async def test_sales_hook_is_rejected_and_regenerated(profile) -> None:
    gateway = HookGateway([DIRTY_HOOK, CLEAN_HOOK])

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert result.passed is True
    assert result.attempts == 2
    assert "drbee" in gateway.prompts[1].lower() or "Dr.Bee" in gateway.prompts[1]


async def test_ungrounded_hook_is_rejected_and_regenerated(profile) -> None:
    """Luật L1 áp cho hook y như cho chuỗi tin nhắn."""
    gateway = HookGateway([UNGROUNDED_HOOK, CLEAN_HOOK])

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert result.attempts == 2
    assert "bé trai" in gateway.prompts[1].lower()


async def test_three_dirty_rounds_return_no_content(profile) -> None:
    result = await generate_evening_hook(
        profile, EVIDENCE, HookGateway([DIRTY_HOOK] * 3), model="m"
    )

    assert result.passed is False
    assert result.message is None  # nội dung bẩn không rời khỏi service
    assert len(result.rejected_reasons) == 3


async def test_judge_failure_means_not_confirmed(profile) -> None:
    gateway = HookGateway([CLEAN_HOOK] * 3, judge_verdict="YES")

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert result.passed is False
    assert result.message is None


async def test_too_long_hook_is_rejected(profile) -> None:
    gateway = HookGateway(["x" * 300, CLEAN_HOOK])

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert result.attempts == 2
    assert "220" in gateway.prompts[1]


async def test_model_error_is_retried(profile) -> None:
    gateway = HookGateway([GatewayRateLimited(), CLEAN_HOOK])

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert result.passed is True
    assert any("gọi model thất bại" in reason for reason in result.rejected_reasons)


# ---------------------------------------------------------------------------
# Không lặp ý với 7 hook gần nhất
# ---------------------------------------------------------------------------
def test_recent_window_is_seven() -> None:
    assert RECENT_HOOKS_TO_AVOID == 7


def test_identical_text_is_fully_similar() -> None:
    assert similarity(CLEAN_HOOK, CLEAN_HOOK) == 1.0


def test_reworded_same_idea_is_detected() -> None:
    """Đổi từ ngữ mà giữ nguyên ý vẫn phải bị coi là lặp."""
    a = "Tối rồi, mong bữa cơm của nhà mình hôm nay thật ấm."
    b = "Tối rồi, mong bữa cơm nhà mình hôm nay ấm áp thật."
    assert similarity(a, b) >= 0.6


def test_different_ideas_are_not_similar() -> None:
    a = "Tối rồi, mong bữa cơm của nhà mình hôm nay thật ấm."
    b = "Nhìn bức tranh bạn chọn làm ảnh đại diện, mình thấy có nét trầm lặng riêng."
    assert similarity(a, b) < 0.6


def test_find_repetition_points_at_the_old_hook() -> None:
    repeated = find_repetition(SEVEN_OLD_HOOKS[0], SEVEN_OLD_HOOKS)
    assert repeated == SEVEN_OLD_HOOKS[0]


def test_find_repetition_returns_none_for_fresh_content() -> None:
    fresh = "Nhìn bức tranh bạn chọn làm ảnh đại diện, mình thấy có nét trầm lặng riêng."
    assert find_repetition(fresh, SEVEN_OLD_HOOKS) is None


def test_very_short_text_is_not_judged_for_similarity() -> None:
    """Câu quá ngắn thì tỉ lệ trùng từ nhiễu rất mạnh — đừng bắt oan."""
    assert find_repetition("Chào bạn", SEVEN_OLD_HOOKS) is None


async def test_repeating_an_old_hook_triggers_regeneration(profile) -> None:
    """DoD D1.18: so với 7 hook gần nhất → không trùng ý."""
    fresh = "Nhìn bức tranh bạn chọn làm ảnh đại diện, mình thấy có nét trầm lặng riêng."
    gateway = HookGateway([SEVEN_OLD_HOOKS[0], fresh])

    result = await generate_evening_hook(
        profile, EVIDENCE, gateway, model="m", recent_hooks=SEVEN_OLD_HOOKS
    )

    assert result.passed is True
    assert result.attempts == 2
    assert result.message == fresh
    assert "lặp ý" in gateway.prompts[1]


async def test_recent_hooks_are_listed_in_the_prompt(profile) -> None:
    gateway = HookGateway([CLEAN_HOOK])

    await generate_evening_hook(profile, EVIDENCE, gateway, model="m", recent_hooks=SEVEN_OLD_HOOKS)

    prompt = gateway.prompts[0]
    assert "7 tin" in prompt
    for old in SEVEN_OLD_HOOKS:
        assert old in prompt


async def test_only_seven_most_recent_are_used(profile) -> None:
    many = [*SEVEN_OLD_HOOKS, "Một hook thứ tám rất cũ về chuyện gì đó khác hẳn mọi tin trên."]
    gateway = HookGateway([CLEAN_HOOK])

    await generate_evening_hook(profile, EVIDENCE, gateway, model="m", recent_hooks=many)

    assert "thứ tám" not in gateway.prompts[0]


async def test_first_ever_hook_says_there_is_no_history(profile) -> None:
    gateway = HookGateway([CLEAN_HOOK])

    await generate_evening_hook(profile, EVIDENCE, gateway, model="m", recent_hooks=[])

    assert "chưa gửi lần nào" in gateway.prompts[0]


# ---------------------------------------------------------------------------
# Prompt nêu đúng luật
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rule", ["KHÔNG CHÀO BÁN", "tóc", "KHÔNG bịa dữ kiện", "220 ký tự", "20h00"]
)
async def test_hook_prompt_states_the_iron_rules(profile, rule: str) -> None:
    gateway = HookGateway([CLEAN_HOOK])

    await generate_evening_hook(profile, EVIDENCE, gateway, model="m")

    assert rule in gateway.prompts[0]


async def test_report_for_db_is_serialisable(profile) -> None:
    result = await generate_evening_hook(profile, EVIDENCE, HookGateway([CLEAN_HOOK]), model="m")
    assert json.dumps(result.report_for_db(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Chạm DB thật: 7 bản ghi có sẵn (DoD D1.18)
# ---------------------------------------------------------------------------
async def test_recent_hooks_are_read_from_the_database(db_session, profile) -> None:
    """DoD: "test với DB có sẵn 7 bản ghi"."""
    import datetime as dt

    from app.models import EveningHook, Profile

    row = Profile(
        facebook_url="https://www.facebook.com/lan",
        url_key="user:lan-hook-test",
        status="SUCCESS",
        customer_name="Nguyễn Thị Lan",
    )
    db_session.add(row)
    await db_session.flush()

    base = dt.datetime(2026, 10, 1, 20, 0, tzinfo=dt.UTC)
    for index, message in enumerate(SEVEN_OLD_HOOKS):
        db_session.add(
            EveningHook(
                profile_id=row.id,
                message=message,
                generated_at=base + dt.timedelta(days=index),
            )
        )
    # Một hook thứ tám, CŨ NHẤT — phải bị cửa sổ 7 tin bỏ ra ngoài.
    db_session.add(
        EveningHook(
            profile_id=row.id,
            message="Hook thứ tám đã rất cũ, nói về một chuyện hoàn toàn khác.",
            generated_at=base - dt.timedelta(days=30),
        )
    )
    await db_session.flush()

    recent = await fetch_recent_hooks(db_session, row.id)

    assert len(recent) == RECENT_HOOKS_TO_AVOID
    assert "thứ tám" not in " ".join(recent)
    # Mới nhất trước.
    assert recent[0] == SEVEN_OLD_HOOKS[-1]

    fresh = "Nhìn bức tranh bạn chọn làm ảnh đại diện, mình thấy có nét trầm lặng riêng."
    gateway = HookGateway([SEVEN_OLD_HOOKS[-1], fresh])

    result = await generate_evening_hook(profile, EVIDENCE, gateway, model="m", recent_hooks=recent)

    assert result.passed is True
    assert result.attempts == 2
    assert result.message == fresh


async def test_profile_without_history_gets_empty_list(db_session) -> None:
    from app.models import Profile

    row = Profile(
        facebook_url="https://www.facebook.com/moi",
        url_key="user:moi-hook-test",
        status="SUCCESS",
    )
    db_session.add(row)
    await db_session.flush()

    assert await fetch_recent_hooks(db_session, row.id) == []
