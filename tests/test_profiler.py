"""D1.15 — profiler + quy tắc hạ status + golden case.

Golden case theo plan.md §11: ① profile công khai đầy đủ ② chỉ có og:title
③ private hoàn toàn ④ không avatar ⑤ evidence cố tình mâu thuẫn.
"""

from __future__ import annotations

import json

import pytest

from app.collectors.avatar import normalize
from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceImage
from app.core.errors import GatewayBadResponse, GatewayRateLimited
from app.llm.base import ModelInfo
from app.llm.catalog import ModelCatalog
from app.services.json_reply import parse_object, parse_string_list
from app.services.profiler import (
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    build_profile,
    decide_status,
    normalize_age_range,
)
from tests.test_avatar_vision import make_image

DEMOGRAPHICS_REPLY = {
    "gender": "Nữ",
    "estimated_age_range": "28 - 38 tuổi",
    "apparent_lifestyle": "Mẹ chăm con nhỏ",
    "basis": {
        "gender": "mô tả ảnh nói là người phụ nữ",
        "estimated_age_range": "ảnh có em bé và một người trưởng thành",
        "apparent_lifestyle": "ảnh có em bé",
    },
}


class ScriptedGateway:
    """Trả lần lượt các phản hồi đã dựng sẵn (vision trước, demographics sau)."""

    provider = "antigravity"

    def __init__(self, replies: list[str | Exception], supports_vision: bool | None = True):
        self._replies = list(replies)
        self._supports_vision = supports_vision
        self.calls = 0

    async def list_models(self):
        return [ModelInfo(id="m", supports_vision=self._supports_vision)]

    async def generate_content(self, payload, *, model):
        self.calls += 1
        reply = self._replies.pop(0) if self._replies else ""
        if isinstance(reply, Exception):
            raise reply
        return {
            "candidates": [{"content": {"parts": [{"text": reply}]}}],
            "usageMetadata": {"promptTokenCount": 100, "totalTokenCount": 150},
        }


@pytest.fixture
def catalog() -> ModelCatalog:
    return ModelCatalog(clock=lambda: 0.0)


@pytest.fixture
def avatar():
    return normalize(make_image(400, 400))


def bundle_with(name: str | None = None, *, avatar_url: str | None = None, **extra):
    b = EvidenceBundle(url_key="user:example_user", facebook_url="https://www.facebook.com/x")
    if name:
        b.add_field(
            "customer_name",
            name,
            source="og_meta",
            evidence=f'<meta property="og:title" content="{name}">',
            confidence=0.95,
        )
    for key, value in extra.items():
        b.add_field(key, value, source="mbasic_html", evidence=f"{key}: {value}", confidence=0.8)
    if avatar_url:
        b.add_image(EvidenceImage(role="avatar", url=avatar_url))
    return b


# ---------------------------------------------------------------------------
# Golden case ① — profile công khai đầy đủ
# ---------------------------------------------------------------------------
async def test_golden_full_public_profile_is_success(catalog, avatar) -> None:
    gateway = ScriptedGateway(
        [
            "Một người trưởng thành bế một em bé bên bánh sinh nhật.",
            json.dumps(DEMOGRAPHICS_REPLY, ensure_ascii=False),
        ]
    )

    result = await build_profile(
        bundle_with("Nguyễn Thị Lan", bio="Mẹ hai bé"),
        gateway,
        model="m",
        avatar=avatar,
        catalog=catalog,
    )

    assert result.status == STATUS_SUCCESS
    assert result.error_note is None
    assert result.customer_name == "Nguyễn Thị Lan"
    assert "em bé" in result.visual_context
    assert result.demographics.gender == "Nữ"
    assert result.demographics.estimated_age_range == "28 - 38 tuổi"
    assert result.is_usable_for_rapport is True


async def test_basis_is_kept_internally_but_not_in_output(catalog, avatar) -> None:
    """`basis` để truy vết căn cứ (lưu DB), không bắt buộc trong JSON nộp bài."""
    gateway = ScriptedGateway(
        ["Một người trưởng thành bế em bé.", json.dumps(DEMOGRAPHICS_REPLY, ensure_ascii=False)]
    )

    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )

    assert result.demographics.basis["gender"]
    assert "basis" not in result.to_profile_data()["estimated_demographics"]


# ---------------------------------------------------------------------------
# Golden case ② — chỉ có og:title
# ---------------------------------------------------------------------------
async def test_golden_only_og_title_leaves_everything_else_null(catalog) -> None:
    gateway = ScriptedGateway([json.dumps({"gender": None, "basis": {}})])

    result = await build_profile(bundle_with("Trần Văn Bình"), gateway, model="m", catalog=catalog)

    assert result.status == STATUS_PARTIAL
    assert result.customer_name == "Trần Văn Bình"
    assert result.visual_context is None
    assert result.demographics.gender is None
    assert result.demographics.estimated_age_range is None
    assert "bối cảnh ảnh đại diện" in result.error_note


# ---------------------------------------------------------------------------
# Golden case ③ — private hoàn toàn
# ---------------------------------------------------------------------------
async def test_golden_fully_private_invents_nothing(catalog) -> None:
    b = EvidenceBundle(url_key="user:private", facebook_url="https://www.facebook.com/p")
    b.add_attempt(CollectAttempt(layer="og_meta", ok=False, http_status=200, note="login wall"))
    b.add_attempt(CollectAttempt(layer="mbasic", ok=False, http_status=200, note="login wall"))
    b.mark_blocked("Facebook yêu cầu đăng nhập để xem trang này.")

    gateway = ScriptedGateway([])
    result = await build_profile(b, gateway, model="m", catalog=catalog)

    assert result.status == STATUS_PARTIAL
    assert result.customer_name is None
    assert result.visual_context is None
    assert result.demographics.is_empty is True
    assert result.is_usable_for_rapport is False
    # `error_note` phải nói rõ đọc được tới đâu — đây là tiêu chí §4 của đề bài.
    assert "đăng nhập" in result.error_note
    assert "og_meta" in result.error_note
    # Không gọi model lần nào: không có gì để suy luận thì đừng gọi.
    assert gateway.calls == 0


async def test_fully_private_profile_data_is_all_null(catalog) -> None:
    b = EvidenceBundle(url_key="user:p", facebook_url="https://www.facebook.com/p")
    b.mark_blocked("Trang bị khoá riêng tư.")

    result = await build_profile(b, ScriptedGateway([]), model="m", catalog=catalog)

    data = result.to_profile_data()
    assert data["customer_name"] is None
    assert data["visual_context"] is None
    assert all(v is None for v in data["estimated_demographics"].values())


# ---------------------------------------------------------------------------
# Golden case ④ — không avatar
# ---------------------------------------------------------------------------
async def test_golden_no_avatar_downgrades_status(catalog) -> None:
    """DoD D1.14/D1.15: không tải được ảnh → visual_context null + hạ status."""
    gateway = ScriptedGateway([json.dumps({"gender": "Nam", "basis": {}})])

    result = await build_profile(
        bundle_with("Lê Văn Cường"), gateway, model="m", avatar=None, catalog=catalog
    )

    assert result.status == STATUS_PARTIAL
    assert result.visual_context is None
    assert "Không tải được ảnh đại diện" in result.error_note


async def test_non_vision_model_downgrades_and_explains(catalog, avatar) -> None:
    gateway = ScriptedGateway([json.dumps({"gender": None, "basis": {}})], supports_vision=False)

    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )

    assert result.status == STATUS_PARTIAL
    assert "không đọc được ảnh" in result.error_note


# ---------------------------------------------------------------------------
# Golden case ⑤ — evidence mâu thuẫn
# ---------------------------------------------------------------------------
async def test_golden_conflicting_evidence_keeps_the_stronger_source(catalog, avatar) -> None:
    """og:title (0.95) thắng heading mbasic (0.85) — không trộn hai cái tên."""
    b = bundle_with("Nguyễn Thị Lan")
    b.add_field(
        "customer_name",
        "Một Cái Tên Khác",
        source="mbasic_html",
        evidence="<h1>Một Cái Tên Khác</h1>",
        confidence=0.85,
    )
    gateway = ScriptedGateway(
        ["Ảnh chân dung một người trưởng thành.", json.dumps(DEMOGRAPHICS_REPLY)]
    )

    result = await build_profile(b, gateway, model="m", avatar=avatar, catalog=catalog)

    assert result.customer_name == "Nguyễn Thị Lan"
    assert "Một Cái Tên Khác" not in (result.customer_name or "")


# ---------------------------------------------------------------------------
# estimated_age_range luôn là KHOẢNG
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("28 - 38 tuổi", "28 - 38 tuổi"),
        ("25-35", "25 - 35 tuổi"),
        ("30 – 40 tuổi", "30 - 40 tuổi"),
        ("từ 20 đến 30 tuổi", "20 - 30 tuổi"),
        ("38 - 28 tuổi", "28 - 38 tuổi"),  # đảo ngược được sắp lại
        # Một con số → thành khoảng, KHÔNG in nguyên con số ra output.
        ("32 tuổi", "27 - 37 tuổi"),
        ("32", "27 - 37 tuổi"),
        ("3 tuổi", "1 - 8 tuổi"),
        # Không đọc được → None, không đoán.
        ("không rõ", None),
        ("", None),
        (None, None),
        (42, None),
        ("khoảng trung niên", None),
        ("200 tuổi", None),
    ],
)
def test_age_range_is_always_a_range(raw, expected) -> None:
    assert normalize_age_range(raw) == expected


async def test_single_age_from_model_becomes_a_range(catalog, avatar) -> None:
    gateway = ScriptedGateway(
        [
            "Ảnh chân dung một người trưởng thành.",
            json.dumps({"estimated_age_range": "35 tuổi", "basis": {}}),
        ]
    )

    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )

    assert result.demographics.estimated_age_range == "30 - 40 tuổi"
    assert result.demographics.estimated_age_range.count("-") == 1


# ---------------------------------------------------------------------------
# Gender: chỉ nhận đúng hai giá trị
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [("Nữ", "Nữ"), ("nam", "Nam"), ("Female", "Nữ"), ("male", "Nam")],
)
async def test_gender_accepted_values(catalog, avatar, raw, expected) -> None:
    gateway = ScriptedGateway(["Ảnh chân dung.", json.dumps({"gender": raw, "basis": {}})])
    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )
    assert result.demographics.gender == expected


@pytest.mark.parametrize("raw", ["không rõ", "N/A", "khác", "null", "", "Nữ/Nam"])
async def test_unclear_gender_becomes_none_not_a_guess(catalog, avatar, raw) -> None:
    gateway = ScriptedGateway(["Ảnh chân dung.", json.dumps({"gender": raw, "basis": {}})])
    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )
    assert result.demographics.gender is None


# ---------------------------------------------------------------------------
# Model lỗi → không bịa
# ---------------------------------------------------------------------------
async def test_demographics_failure_leaves_fields_null(catalog, avatar) -> None:
    gateway = ScriptedGateway(["Ảnh chân dung.", GatewayRateLimited()])

    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )

    assert result.demographics.is_empty is True
    assert any("nhân khẩu học" in note for note in result.notes)


async def test_unparseable_demographics_json_leaves_fields_null(catalog, avatar) -> None:
    gateway = ScriptedGateway(["Ảnh chân dung.", "xin lỗi, tôi không chắc"])

    result = await build_profile(
        bundle_with("Lan"), gateway, model="m", avatar=avatar, catalog=catalog
    )

    assert result.demographics.is_empty is True


# ---------------------------------------------------------------------------
# decide_status thuần
# ---------------------------------------------------------------------------
def test_status_success_needs_both_name_and_visual() -> None:
    b = bundle_with("Lan")
    assert decide_status(b, customer_name="Lan", visual_context="Ảnh chân dung")[0] == (
        STATUS_SUCCESS
    )


@pytest.mark.parametrize(
    "name, visual",
    [(None, "Ảnh chân dung"), ("Lan", None), (None, None)],
)
def test_status_partial_when_anything_is_missing(name, visual) -> None:
    status, note = decide_status(bundle_with(name), customer_name=name, visual_context=visual)
    assert status == STATUS_PARTIAL
    assert note


def test_error_note_lists_exactly_what_is_missing() -> None:
    _, note = decide_status(bundle_with(), customer_name=None, visual_context=None)
    assert "tên hiển thị" in note
    assert "bối cảnh ảnh đại diện" in note


# ---------------------------------------------------------------------------
# Đọc JSON của model
# ---------------------------------------------------------------------------
def test_parse_object_handles_code_fence() -> None:
    assert parse_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_object_handles_leading_prose() -> None:
    assert parse_object('Đây là kết quả: {"a": 1} Hy vọng giúp được bạn.') == {"a": 1}


@pytest.mark.parametrize("text", ["", "không phải json", '{"a": 1', "[1, 2]"])
def test_parse_object_refuses_to_patch_broken_json(text: str) -> None:
    """Vá JSON hỏng bằng regex là đoán ý model — một dấu phẩy đổi hẳn nghĩa."""
    with pytest.raises(GatewayBadResponse):
        parse_object(text)


def test_parse_string_list_from_object() -> None:
    assert parse_string_list('{"items": ["a", "b"]}', key="items") == ["a", "b"]


def test_parse_string_list_accepts_a_bare_array() -> None:
    """Lệch *hình dạng*, không lệch *nội dung* → không cần sinh lại."""
    assert parse_string_list('["a", "b"]', key="items") == ["a", "b"]


def test_parse_string_list_drops_non_strings_and_blanks() -> None:
    assert parse_string_list('{"items": ["a", 5, "", "  ", "b"]}', key="items") == ["a", "b"]


def test_parse_string_list_errors_when_key_is_missing() -> None:
    with pytest.raises(GatewayBadResponse, match="items"):
        parse_string_list('{"khac": ["a"]}', key="items")


def test_parse_string_list_errors_when_all_items_unusable() -> None:
    with pytest.raises(GatewayBadResponse):
        parse_string_list('{"items": [1, 2, null]}', key="items")
