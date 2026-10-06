"""D1.20 — `run_analysis` trọn luồng (mock mạng + mock cổng model) và lưu DB.

Đây là đường chính của sản phẩm: thu thập → profile → tin nhắn → hook → JSON.
Test ở đây thay **mạng** bằng respx và thay **cổng model** bằng gateway giả, nên
chạy được ở mọi máy mà vẫn đi qua đúng các nhánh thật.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.core.errors import InvalidFacebookUrl
from app.llm.base import ModelInfo
from app.models import EveningHook, Profile, ProfileEvidence, RapportMessage, RapportRun
from app.services.persistence import save_analysis
from app.services.pipeline import MANUAL_ONLY_URL, run_analysis
from tests.test_avatar_vision import make_image

PROFILE_URL = "https://www.facebook.com/example_user"
MBASIC_URL = "https://mbasic.facebook.com/example_user"
AVATAR_URL = "https://scontent.test/avatar.jpg"

PUBLIC_HTML = f"""
<html><head>
<meta property="og:title" content="Nguyễn Thị Lan | Facebook">
<meta property="og:image" content="{AVATAR_URL}">
</head><body></body></html>
"""

LOGIN_WALL_HTML = """
<html><head><title>Facebook</title></head>
<body>Đăng nhập vào Facebook. Tạo tài khoản mới.</body></html>
"""

TEN_MESSAGES = [
    "Chào Lan, ảnh đại diện của bạn trông thật ấm áp.",
    "Nhìn ảnh là thấy không khí gia đình rộn ràng.",
    "Mình hiểu cảm giác vừa trông con vừa lo việc.",
    "Những ngày như vậy mà vẫn tươi tỉnh là đáng quý.",
    "Mình cũng từng có quãng thời gian tất bật như thế.",
    "Hồi đó mình học được rằng nghỉ một chút là lại đi tiếp được.",
    "Hôm nay của bạn thế nào rồi.",
    "Bạn thường thư giãn bằng cách gì sau một ngày dài.",
    "Mình để tin ở đây, có gì cứ kể nhé.",
    "Chúc bạn buổi tối an lành.",
]

CLEAN_HOOK = "Tối rồi, mong buổi tối của bạn thật nhẹ nhàng. Mình để tin ở đây nhé."


class ScriptedGateway:
    """Gateway giả nhận biết từng bước qua nội dung prompt."""

    provider = "antigravity"

    def __init__(
        self,
        *,
        vision: str = "Một người trưởng thành bế một em bé bên bánh sinh nhật.",
        messages: list[str] | None = None,
        hook: str = CLEAN_HOOK,
        judge: str = "NO",
        supports_vision: bool | None = True,
    ):
        self._vision = vision
        self._messages = messages if messages is not None else TEN_MESSAGES
        self._hook = hook
        self._judge = judge
        self._supports_vision = supports_vision
        self.steps: list[str] = []

    async def list_models(self):
        return [ModelInfo(id="m", supports_vision=self._supports_vision)]

    async def aclose(self) -> None:
        return None

    async def generate_content(self, payload, *, model):
        parts = payload["contents"][0]["parts"]
        has_image = any("inline_data" in part for part in parts)
        prompt = next((p["text"] for p in parts if "text" in p), "")

        if has_image:
            self.steps.append("vision")
            return _reply(self._vision)
        if "người kiểm duyệt nội dung" in prompt:
            self.steps.append("judge")
            return _reply(json.dumps({"verdict": self._judge, "reason": "ok"}))
        if "ước lượng nhân khẩu học" in prompt:
            self.steps.append("demographics")
            return _reply(
                json.dumps(
                    {
                        "gender": "Nữ",
                        "estimated_age_range": "28 - 38 tuổi",
                        "apparent_lifestyle": "Mẹ chăm con nhỏ",
                        "basis": {"gender": "mô tả ảnh"},
                    },
                    ensure_ascii=False,
                )
            )
        if "góc thấu cảm chính" in prompt:
            self.steps.append("empathy")
            return _reply(
                json.dumps(
                    {"core_empathy_angle": "Ghi nhận sự tần tảo.", "grounded_in": "og:title"},
                    ensure_ascii=False,
                )
            )
        if "tin nhắn ĐẦU TIÊN" in prompt:
            self.steps.append("sequence")
            return _reply(json.dumps({"messages": self._messages}, ensure_ascii=False))
        if "20h00 tối" in prompt:
            self.steps.append("hook")
            return _reply(
                json.dumps({"hook": self._hook, "grounded_in": "og:title"}, ensure_ascii=False)
            )
        raise AssertionError(f"prompt không nhận ra: {prompt[:120]!r}")


def _reply(text: str) -> dict:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
            "totalTokenCount": 400,
        },
    }


@pytest.fixture
def public_profile_network():
    """Trang công khai: og đọc được, mbasic là login wall, avatar tải được."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(PROFILE_URL).mock(return_value=httpx.Response(200, text=PUBLIC_HTML))
        mock.get(MBASIC_URL).mock(return_value=httpx.Response(200, text=LOGIN_WALL_HTML))
        mock.get(AVATAR_URL).mock(return_value=httpx.Response(200, content=make_image(600, 600)))
        yield mock


# ---------------------------------------------------------------------------
# Luồng đầy đủ
# ---------------------------------------------------------------------------
async def test_full_run_produces_success_output(public_profile_network, tmp_path) -> None:
    gateway = ScriptedGateway()

    outcome = await run_analysis(
        gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    output = outcome.output
    assert output.status == "SUCCESS"
    assert output.facebook_url == PROFILE_URL
    assert output.profile_data.customer_name == "Nguyễn Thị Lan"
    assert "em bé" in output.profile_data.visual_context
    assert output.profile_data.estimated_demographics.gender == "Nữ"
    assert len(output.ethical_rapport.dialogue_sequence_10) == 10
    assert output.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"
    assert output.evening_cadence_20pm.trigger_time == "20:00"
    assert output.evening_cadence_20pm.evening_hook_message == CLEAN_HOOK
    assert output.error_note is None


async def test_full_run_visits_every_step_in_order(public_profile_network, tmp_path) -> None:
    gateway = ScriptedGateway()

    await run_analysis(gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path))

    # Vision trước demographics (demographics dùng mô tả ảnh làm đầu vào).
    assert gateway.steps.index("vision") < gateway.steps.index("demographics")
    assert "sequence" in gateway.steps
    assert "judge" in gateway.steps
    assert gateway.steps.index("sequence") < gateway.steps.index("hook")


async def test_output_is_json_loads_parseable(public_profile_network, tmp_path) -> None:
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )
    assert json.loads(outcome.output.to_json())["status"] == "SUCCESS"


async def test_evidence_records_every_layer_attempt(public_profile_network, tmp_path) -> None:
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    layers = {attempt.layer for attempt in outcome.bundle.attempts}
    assert {"og_meta", "mbasic", "avatar"} <= layers
    # mbasic là login wall → phải được ghi là thất bại, không âm thầm bỏ qua.
    mbasic_attempt = next(a for a in outcome.bundle.attempts if a.layer == "mbasic")
    assert mbasic_attempt.ok is False


# ---------------------------------------------------------------------------
# Nhánh private — không bịa, không gọi model vô ích
# ---------------------------------------------------------------------------
async def test_fully_private_page_stops_before_generating(tmp_path) -> None:
    gateway = ScriptedGateway()

    with respx.mock(assert_all_called=False) as mock:
        mock.get(PROFILE_URL).mock(return_value=httpx.Response(200, text=LOGIN_WALL_HTML))
        mock.get(MBASIC_URL).mock(return_value=httpx.Response(200, text=LOGIN_WALL_HTML))

        outcome = await run_analysis(
            gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
        )

    output = outcome.output
    assert output.status == "PARTIAL_OR_PRIVATE"
    assert output.profile_data.customer_name is None
    assert output.ethical_rapport.dialogue_sequence_10 == []
    assert output.ethical_rapport.sales_mention_check == "FAILED"
    assert output.evening_cadence_20pm.trigger_time == "20:00"
    assert "đăng nhập" in output.error_note
    # Không có gì để suy luận thì đừng tốn một lần gọi model nào.
    assert gateway.steps == []


async def test_network_failure_is_reported_not_raised(tmp_path) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(PROFILE_URL).mock(side_effect=httpx.ConnectError("mất mạng"))
        mock.get(MBASIC_URL).mock(side_effect=httpx.ConnectError("mất mạng"))

        outcome = await run_analysis(
            gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
        )

    assert outcome.output.status == "PARTIAL_OR_PRIVATE"
    assert outcome.output.error_note


async def test_invalid_url_raises_because_it_is_the_callers_mistake(tmp_path) -> None:
    """URL sai định dạng **là** lỗi của người gọi — khác hẳn trang private."""
    with pytest.raises(InvalidFacebookUrl):
        await run_analysis(
            gateway=ScriptedGateway(),
            model="m",
            url="https://twitter.com/abc",
            upload_dir=str(tmp_path),
        )


# ---------------------------------------------------------------------------
# Đường L4 — không cần mạng
# ---------------------------------------------------------------------------
async def test_manual_paste_only_needs_no_network(tmp_path) -> None:
    """`--profile-file` không kèm `--url` → không request HTTP nào."""
    gateway = ScriptedGateway(vision="")

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(PROFILE_URL)

        outcome = await run_analysis(
            gateway=gateway,
            model="m",
            profile_text="Tên: Nguyễn Thị Lan\nTiểu sử: Mẹ hai bé, bán hàng online tại Hà Nội.",
            upload_dir=str(tmp_path),
        )

    assert route.call_count == 0
    assert outcome.output.facebook_url == MANUAL_ONLY_URL
    assert outcome.output.profile_data.customer_name == "Nguyễn Thị Lan"
    # Không có ảnh → PARTIAL_OR_PRIVATE, nhưng vẫn sinh được nội dung.
    assert outcome.output.status == "PARTIAL_OR_PRIVATE"
    assert len(outcome.output.ethical_rapport.dialogue_sequence_10) == 10


async def test_url_plus_manual_paste_merges_evidence(public_profile_network, tmp_path) -> None:
    """Luồng thực tế: L1 cho tên + ảnh, người vận hành dán thêm bio/post."""
    outcome = await run_analysis(
        gateway=ScriptedGateway(),
        model="m",
        url=PROFILE_URL,
        profile_text="Tiểu sử: Mẹ hai bé, bán hàng online tại Hà Nội.",
        upload_dir=str(tmp_path),
    )

    corpus = outcome.bundle.evidence_corpus()
    assert "Nguyễn Thị Lan" in corpus  # từ og:title
    assert "bán hàng online" in corpus  # từ người vận hành dán
    assert outcome.output.status == "SUCCESS"


# ---------------------------------------------------------------------------
# Kiểm duyệt fail → FAILED_VALIDATION
# ---------------------------------------------------------------------------
async def test_sales_language_exhausts_retries_and_fails_closed(
    public_profile_network, tmp_path
) -> None:
    dirty = [*TEN_MESSAGES[:9], "Chị dùng Dr.Bee chưa, giá chỉ 299k thôi."]
    gateway = ScriptedGateway(messages=dirty)

    outcome = await run_analysis(
        gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    output = outcome.output
    assert output.status == "FAILED_VALIDATION"
    assert output.ethical_rapport.dialogue_sequence_10 == []
    assert output.ethical_rapport.sales_mention_check == "FAILED"
    assert "Dr.Bee" not in output.to_json()
    assert "299k" not in output.to_json()
    assert "kiểm duyệt" in output.error_note


async def test_failed_hook_also_downgrades_status(public_profile_network, tmp_path) -> None:
    gateway = ScriptedGateway(hook="Chị ơi, inbox để lại số em tư vấn nhé.")

    outcome = await run_analysis(
        gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    assert outcome.output.status == "FAILED_VALIDATION"
    assert outcome.output.evening_cadence_20pm.evening_hook_message is None
    assert outcome.output.evening_cadence_20pm.trigger_time == "20:00"


async def test_non_vision_model_still_produces_messages(public_profile_network, tmp_path) -> None:
    gateway = ScriptedGateway(supports_vision=False)

    outcome = await run_analysis(
        gateway=gateway, model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    assert outcome.output.profile_data.visual_context is None
    assert outcome.output.status == "PARTIAL_OR_PRIVATE"
    assert len(outcome.output.ethical_rapport.dialogue_sequence_10) == 10
    assert "không đọc được ảnh" in outcome.output.error_note


async def test_recent_hooks_are_forwarded_to_the_hook_step(
    public_profile_network, tmp_path
) -> None:
    gateway = ScriptedGateway()

    await run_analysis(
        gateway=gateway,
        model="m",
        url=PROFILE_URL,
        recent_hooks=[CLEAN_HOOK],
        upload_dir=str(tmp_path),
    )

    # Hook giả trùng hoàn toàn với hook cũ → phải bị bắt lặp và sinh lại.
    assert gateway.steps.count("hook") >= 2


# ---------------------------------------------------------------------------
# Lưu DB (chạm Postgres thật)
# ---------------------------------------------------------------------------
async def test_save_analysis_writes_every_table(
    db_session, public_profile_network, tmp_path
) -> None:
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    profile_id = await save_analysis(
        db_session, outcome, provider="antigravity", model="gemini-test"
    )

    async def count(model, **where):
        stmt = select(func.count()).select_from(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        return (await db_session.execute(stmt)).scalar_one()

    assert await count(Profile, id=profile_id) == 1
    assert await count(ProfileEvidence, profile_id=profile_id) == 1
    assert await count(RapportRun, profile_id=profile_id) == 1
    assert await count(EveningHook, profile_id=profile_id) == 1

    run = (
        await db_session.execute(select(RapportRun).where(RapportRun.profile_id == profile_id))
    ).scalar_one()
    assert run.provider == "antigravity"
    assert run.model == "gemini-test"
    assert run.sales_check == "ZERO_SALES_CONFIRMED"
    assert await count(RapportMessage, run_id=run.id) == 10


async def test_rerunning_the_same_url_does_not_duplicate_the_profile(
    db_session, public_profile_network, tmp_path
) -> None:
    """`url_key` unique → chạy lại cùng URL thì cập nhật, không tạo profile trùng."""
    first = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )
    second = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )

    id_one = await save_analysis(db_session, first, provider="antigravity", model="m")
    id_two = await save_analysis(db_session, second, provider="antigravity", model="m")

    assert id_one == id_two

    total = (
        await db_session.execute(
            select(func.count()).select_from(Profile).where(Profile.id == id_one)
        )
    ).scalar_one()
    assert total == 1

    # Nhưng lịch sử lượt sinh thì giữ lại cả hai — đó là bằng chứng so sánh về sau.
    runs = (
        await db_session.execute(
            select(func.count()).select_from(RapportRun).where(RapportRun.profile_id == id_one)
        )
    ).scalar_one()
    assert runs == 2


async def test_saved_demographics_keep_the_internal_basis(
    db_session, public_profile_network, tmp_path
) -> None:
    """`basis` chỉ lưu DB, không ra output — đường truy vết căn cứ suy luận."""
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )
    profile_id = await save_analysis(db_session, outcome, provider="antigravity", model="m")

    row = (await db_session.execute(select(Profile).where(Profile.id == profile_id))).scalar_one()

    assert row.demographics["gender"] == "Nữ"
    assert row.demographics["basis"]["gender"] == "mô tả ảnh"
    assert "basis" not in outcome.output.to_dict()["profile_data"]["estimated_demographics"]


async def test_saved_evidence_bundle_round_trips(
    db_session, public_profile_network, tmp_path
) -> None:
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )
    profile_id = await save_analysis(db_session, outcome, provider="antigravity", model="m")

    row = (
        await db_session.execute(
            select(ProfileEvidence).where(ProfileEvidence.profile_id == profile_id)
        )
    ).scalar_one()

    from app.collectors.evidence import EvidenceBundle

    restored = EvidenceBundle.from_dict(row.bundle)
    assert restored.value_of("customer_name") == "Nguyễn Thị Lan"
    assert restored.attempts


async def test_failed_validation_saves_no_messages(
    db_session, public_profile_network, tmp_path
) -> None:
    dirty = [*TEN_MESSAGES[:9], "Chị dùng Dr.Bee chưa, giá chỉ 299k thôi."]
    outcome = await run_analysis(
        gateway=ScriptedGateway(messages=dirty),
        model="m",
        url=PROFILE_URL,
        upload_dir=str(tmp_path),
    )

    profile_id = await save_analysis(db_session, outcome, provider="antigravity", model="m")

    run = (
        await db_session.execute(select(RapportRun).where(RapportRun.profile_id == profile_id))
    ).scalar_one()
    messages = (
        await db_session.execute(
            select(func.count()).select_from(RapportMessage).where(RapportMessage.run_id == run.id)
        )
    ).scalar_one()

    assert run.sales_check == "FAILED"
    assert messages == 0  # nội dung bẩn không vào DB
    assert run.grounding_report["passed"] is False
    assert run.grounding_report["attempts"] == 3


async def test_screenshot_path_is_persisted(db_session, public_profile_network, tmp_path) -> None:
    """DoD D1.13: đường dẫn ảnh chụp phải đi tới `profile_evidence.screenshot_path`."""
    outcome = await run_analysis(
        gateway=ScriptedGateway(), model="m", url=PROFILE_URL, upload_dir=str(tmp_path)
    )
    outcome.bundle.screenshot_path = "var/screenshots/user_example_user.png"

    profile_id = await save_analysis(db_session, outcome, provider="antigravity", model="m")

    row = (
        await db_session.execute(
            select(ProfileEvidence).where(ProfileEvidence.profile_id == profile_id)
        )
    ).scalar_one()
    assert row.screenshot_path == "var/screenshots/user_example_user.png"
