"""D1.14 — chuẩn hoá avatar + bước vision.

Điều được canh gác chặt nhất: **không bịa mô tả**. Mỗi nhánh thất bại phải cho
ra `visual_context = None` kèm một `note` nói đúng việc cần làm.
"""

from __future__ import annotations

import io
import pathlib

import httpx
import pytest
import respx
from PIL import Image

from app.collectors import avatar as avatar_mod
from app.collectors.evidence import EvidenceBundle, EvidenceImage
from app.core.errors import GatewayBadResponse, GatewayRateLimited
from app.llm.base import ModelInfo
from app.llm.catalog import ModelCatalog
from app.prompts import load as load_prompt
from app.prompts import render as render_prompt
from app.services.vision import describe_avatar, is_unclear

AVATAR_URL = "https://scontent.test/v/t39.30808-1/489728770.jpg"


def make_image(width: int, height: int, fmt: str = "JPEG") -> bytes:
    image = Image.new("RGB", (width, height), (120, 160, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def bundle() -> EvidenceBundle:
    b = EvidenceBundle(url_key="user:example_user", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_URL))
    return b


class FakeGateway:
    """Gateway giả: trả text cố định, hoặc raise lỗi đã dựng sẵn."""

    provider = "antigravity"

    def __init__(self, text: str | None = None, error: Exception | None = None, models=None):
        self._text = text
        self._error = error
        self._models = models or [ModelInfo(id="co-vision", supports_vision=True)]
        self.payloads: list[dict] = []

    async def list_models(self):
        return list(self._models)

    async def generate_content(self, payload, *, model):
        self.payloads.append(payload)
        if self._error is not None:
            raise self._error
        return {
            "candidates": [{"content": {"parts": [{"text": self._text}]}}],
            "usageMetadata": {"promptTokenCount": 300, "totalTokenCount": 340},
        }


@pytest.fixture
def catalog() -> ModelCatalog:
    return ModelCatalog(clock=lambda: 0.0)


# ---------------------------------------------------------------------------
# Chuẩn hoá: WebP ≤1024px
# ---------------------------------------------------------------------------
def test_large_image_is_shrunk_to_1024_longest_edge() -> None:
    result = avatar_mod.normalize(make_image(2400, 1200))

    assert max(result.width, result.height) == 1024
    assert result.mime_type == "image/webp"
    # Giữ đúng tỉ lệ — méo ảnh làm mô tả vision sai.
    assert result.width / result.height == pytest.approx(2.0, abs=0.01)


def test_small_image_is_not_upscaled() -> None:
    result = avatar_mod.normalize(make_image(200, 300))
    assert (result.width, result.height) == (200, 300)


def test_output_is_really_webp() -> None:
    result = avatar_mod.normalize(make_image(500, 500))
    with Image.open(io.BytesIO(result.data)) as reopened:
        assert reopened.format == "WEBP"


def test_png_with_alpha_is_accepted() -> None:
    image = Image.new("RGBA", (300, 300), (255, 0, 0, 128))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = avatar_mod.normalize(buffer.getvalue())
    assert result.mime_type == "image/webp"


def test_sha256_is_stable_for_identical_input() -> None:
    raw = make_image(400, 400)
    assert avatar_mod.normalize(raw).sha256 == avatar_mod.normalize(raw).sha256


def test_non_image_bytes_are_rejected() -> None:
    with pytest.raises(ValueError, match="không phải ảnh"):
        avatar_mod.normalize(b"<html>day khong phai anh</html>")


# ---------------------------------------------------------------------------
# Tải: thất bại thì ghi nhận, không raise
# ---------------------------------------------------------------------------
@respx.mock
async def test_fetch_normalizes_and_records_sha256(bundle, tmp_path) -> None:
    respx.get(AVATAR_URL).mock(
        return_value=httpx.Response(
            200, content=make_image(1600, 1600), headers={"Content-Type": "image/jpeg"}
        )
    )

    async with httpx.AsyncClient() as client:
        result = await avatar_mod.fetch_and_normalize(
            bundle, client=client, output_dir=str(tmp_path)
        )

    assert result is not None
    assert max(result.width, result.height) == 1024
    assert pathlib.Path(result.local_path).is_file()
    # sha256 + đường dẫn là **bằng chứng** cho visual_context.
    assert bundle.avatar.sha256 == result.sha256
    assert bundle.avatar.local_path == result.local_path
    assert bundle.attempts[-1].ok is True


async def test_no_avatar_is_skipped_not_failed(tmp_path) -> None:
    empty = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")

    assert await avatar_mod.fetch_and_normalize(empty, output_dir=str(tmp_path)) is None
    assert empty.attempts[-1].skipped is True


@respx.mock
async def test_http_error_is_recorded_not_raised(bundle, tmp_path) -> None:
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(403))

    async with httpx.AsyncClient() as client:
        assert (
            await avatar_mod.fetch_and_normalize(bundle, client=client, output_dir=str(tmp_path))
            is None
        )
    assert bundle.attempts[-1].http_status == 403


@respx.mock
async def test_oversized_download_is_refused(bundle, tmp_path) -> None:
    respx.get(AVATAR_URL).mock(
        return_value=httpx.Response(200, content=b"x" * (avatar_mod.MAX_DOWNLOAD_BYTES + 1))
    )

    async with httpx.AsyncClient() as client:
        assert (
            await avatar_mod.fetch_and_normalize(bundle, client=client, output_dir=str(tmp_path))
            is None
        )
    assert "vượt giới hạn" in bundle.attempts[-1].note


@respx.mock
async def test_html_served_instead_of_image_is_refused(bundle, tmp_path) -> None:
    """Facebook CDN trả trang lỗi HTML với HTTP 200 là chuyện có thật."""
    respx.get(AVATAR_URL).mock(return_value=httpx.Response(200, text="<html>Error</html>"))

    async with httpx.AsyncClient() as client:
        assert (
            await avatar_mod.fetch_and_normalize(bundle, client=client, output_dir=str(tmp_path))
            is None
        )
    assert "không phải ảnh" in bundle.attempts[-1].note


async def test_locally_uploaded_image_needs_no_network(tmp_path) -> None:
    """Đường L4: ảnh đã trên đĩa → chuẩn hoá được khi không có mạng."""
    path = tmp_path / "upload.png"
    path.write_bytes(make_image(800, 800, fmt="PNG"))

    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url="manual://abc", local_path=str(path)))

    result = await avatar_mod.fetch_and_normalize(b, output_dir=str(tmp_path))
    assert result is not None
    assert result.mime_type == "image/webp"


# ---------------------------------------------------------------------------
# Prompt nằm ở file, không nhúng trong code
# ---------------------------------------------------------------------------
def test_vision_prompt_lives_in_a_text_file() -> None:
    prompt = load_prompt("vision_describe")
    assert len(prompt) > 200


@pytest.mark.parametrize(
    "forbidden",
    ["Nghề nghiệp", "Thu nhập", "hôn nhân", "Tên riêng"],
)
def test_vision_prompt_forbids_inference_beyond_the_image(forbidden: str) -> None:
    """plan.md §5.3: cấm suy diễn nghề/thu nhập/hôn nhân từ ảnh."""
    assert forbidden in load_prompt("vision_describe")


def test_vision_prompt_allows_saying_it_cannot_see() -> None:
    assert "Không nhìn rõ" in load_prompt("vision_describe")


def test_missing_prompt_names_what_is_available() -> None:
    with pytest.raises(FileNotFoundError, match="vision_describe"):
        load_prompt("khong_ton_tai")


def test_render_fails_loudly_on_missing_variable(monkeypatch) -> None:
    """`{bien}` lọt nguyên văn vào prompt gửi model là lỗi im lặng — phải nổ."""
    monkeypatch.setattr("app.prompts.load", lambda _name: "Xin chào {ten_khach}.")

    with pytest.raises(KeyError, match="ten_khach"):
        render_prompt("gia_lap")


def test_render_substitutes_values(monkeypatch) -> None:
    monkeypatch.setattr("app.prompts.load", lambda _name: "Xin chào {ten_khach}.")
    assert render_prompt("gia_lap", ten_khach="Lan") == "Xin chào Lan."


# ---------------------------------------------------------------------------
# Bước vision — không bịa
# ---------------------------------------------------------------------------
async def test_vision_returns_description(catalog, tmp_path) -> None:
    gateway = FakeGateway(text="Một người trưởng thành bế một em bé bên bánh sinh nhật.")
    avatar = avatar_mod.normalize(make_image(600, 600))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)

    assert result.ok is True
    assert "em bé" in result.description
    assert result.usage == {"prompt_tokens": 300, "total_tokens": 340}
    assert result.latency_ms is not None


async def test_vision_sends_the_image_and_the_system_prompt(catalog) -> None:
    gateway = FakeGateway(text="Ảnh chân dung một người trưởng thành.")
    avatar = avatar_mod.normalize(make_image(300, 300))

    await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)

    payload = gateway.payloads[0]
    parts = payload["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/webp"
    assert "MÔ TẢ NHỮNG GÌ NHÌN THẤY" in payload["systemInstruction"]["parts"][0]["text"]


async def test_no_avatar_gives_none_not_an_invented_description(catalog) -> None:
    gateway = FakeGateway(text="không bao giờ được gọi")

    result = await describe_avatar(None, gateway, model="co-vision", catalog=catalog)

    assert result.description is None
    assert "Không tải được ảnh" in result.note
    assert gateway.payloads == []  # không gọi model vô ích


async def test_model_without_vision_is_not_called_and_says_why(catalog) -> None:
    """DoD D1.14: model không vision → visual_context null + giải thích, KHÔNG bịa."""
    gateway = FakeGateway(
        text="không bao giờ được gọi",
        models=[ModelInfo(id="khong-vision", supports_vision=False)],
    )
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="khong-vision", catalog=catalog)

    assert result.description is None
    assert "không đọc được ảnh" in result.note
    assert gateway.payloads == []


async def test_unknown_vision_capability_still_tries(catalog) -> None:
    """Cổng Google API Key không khai báo cờ vision (I-06) → cứ thử, đừng chặn oan."""
    gateway = FakeGateway(
        text="Ảnh phong cảnh biển, không có người.",
        models=[ModelInfo(id="chua-biet", supports_vision=None)],
    )
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="chua-biet", catalog=catalog)

    assert result.ok is True
    assert len(gateway.payloads) == 1


async def test_gateway_error_gives_none_with_reason(catalog) -> None:
    gateway = FakeGateway(error=GatewayRateLimited())
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)

    assert result.description is None
    assert "quota" in result.note.lower() or "thất bại" in result.note


async def test_safety_block_gives_none_with_reason(catalog) -> None:
    gateway = FakeGateway(error=GatewayBadResponse("Nội dung bị bộ lọc an toàn chặn."))
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)
    assert result.description is None


async def test_empty_model_reply_gives_none(catalog) -> None:
    gateway = FakeGateway(text="   ")
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)
    assert result.description is None


async def test_model_saying_it_cannot_see_is_kept_as_truth(catalog) -> None:
    """ "Không nhìn rõ" **là** thông tin đúng — giữ nguyên, đánh dấu bằng note."""
    gateway = FakeGateway(text="Không nhìn rõ nội dung ảnh.")
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)

    assert result.ok is True
    assert "Không nhìn rõ" in result.description
    assert "không nhìn rõ" in result.note.lower()


async def test_description_is_one_line_without_quotes(catalog) -> None:
    gateway = FakeGateway(text='  "Một người trưởng thành\n  mặc áo xanh."  ')
    avatar = avatar_mod.normalize(make_image(300, 300))

    result = await describe_avatar(avatar, gateway, model="co-vision", catalog=catalog)

    assert "\n" not in result.description
    assert not result.description.startswith('"')


@pytest.mark.parametrize(
    "text, unclear",
    [
        ("Không nhìn rõ nội dung ảnh.", True),
        ("Không rõ có bao nhiêu người.", True),
        ("Một người trưởng thành mặc áo xanh.", False),
    ],
)
def test_unclear_detection(text: str, unclear: bool) -> None:
    assert is_unclear(text) is unclear


# ---------------------------------------------------------------------------
# I-16 — thinking token của Gemini 3.x ăn vào maxOutputTokens
# ---------------------------------------------------------------------------
class TruncatingGateway(FakeGateway):
    """Giả lập `finishReason=MAX_TOKENS` kèm text cụt — đo thật trên 3.x."""

    async def generate_content(self, payload, *, model):
        self.payloads.append(payload)
        return {
            "candidates": [
                {
                    "finishReason": "MAX_TOKENS",
                    "content": {"parts": [{"text": "Ảnh là một mảng màu xanh dương"}]},
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1573,
                "candidatesTokenCount": 8,
                "totalTokenCount": 1825,
            },
        }


async def test_vision_budget_is_large_enough_for_thinking_tokens(catalog) -> None:
    """cap=256 từng làm `gemini-3-flash-preview` dùng ~244 token để suy nghĩ,
    chỉ còn 8 token cho câu trả lời (I-16). Hạn mức phải rộng hơn nhiều.
    """
    from app.services.vision import VISION_MAX_OUTPUT_TOKENS

    assert VISION_MAX_OUTPUT_TOKENS >= 1024

    gateway = FakeGateway(text="Một người trưởng thành mặc áo xanh.")
    await describe_avatar(
        avatar_mod.normalize(make_image(300, 300)), gateway, model="co-vision", catalog=catalog
    )
    sent = gateway.payloads[0]["generationConfig"]["maxOutputTokens"]
    assert sent == VISION_MAX_OUTPUT_TOKENS


async def test_truncated_description_is_returned_but_flagged(catalog) -> None:
    """Câu cụt vẫn hơn mất hẳn, nhưng không được đọc như mô tả đầy đủ."""
    gateway = TruncatingGateway()

    result = await describe_avatar(
        avatar_mod.normalize(make_image(300, 300)), gateway, model="co-vision", catalog=catalog
    )

    assert result.ok is True
    assert result.description == "Ảnh là một mảng màu xanh dương"
    assert "bị cắt" in result.note
