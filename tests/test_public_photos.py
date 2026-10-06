"""X.1 — thu ảnh công khai + mô tả nhiều ảnh ở bước vision.

Đề bài §1 nêu đích danh "ngữ cảnh từ hình ảnh đại diện (Avatar) **hoặc hình ảnh
công khai gần nhất**". Đo thật (task.md I-30): Facebook khoá phần chữ nhưng vẫn
phục vụ lưới ảnh, nên đây là nguồn evidence mạnh nhất lấy được mà không cần
đăng nhập.

Điều được canh gác chặt nhất: **không thu ảnh của người khác**. Mục "Những
người khác có tên tương tự" nằm ngay trên cùng trang; mô tả avatar của họ như
thể là khách vừa vi phạm L1 vừa vi phạm riêng tư của người không liên quan.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.collectors import avatar as avatar_mod
from app.collectors import playwright_dom
from app.collectors.evidence import EvidenceBundle, EvidenceImage
from app.llm.base import ModelInfo
from app.llm.catalog import ModelCatalog
from app.services.vision import describe_avatar
from tests.test_avatar_vision import make_image

PHOTO_URLS = [
    "https://scontent.test/v/t39.30808-6/anh-bai-dang-1.jpg",
    "https://scontent.test/v/t39.30808-6/anh-bai-dang-2.jpg",
    "https://scontent.test/v/t39.30808-6/anh-bai-dang-3.jpg",
]
AVATAR_URL = "https://scontent.test/v/t39.30808-1/avatar.jpg"


@pytest.fixture
def bundle() -> EvidenceBundle:
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_URL))
    for url in PHOTO_URLS:
        b.add_image(EvidenceImage(role="public_photo", url=url))
    return b


@pytest.fixture
def catalog() -> ModelCatalog:
    return ModelCatalog(clock=lambda: 0.0)


class VisionGateway:
    provider = "antigravity"

    def __init__(self, text: str = "Một người trưởng thành bên bàn ăn gia đình."):
        self._text = text
        self.payloads: list[dict] = []

    async def list_models(self):
        return [ModelInfo(id="m", supports_vision=True)]

    async def generate_content(self, payload, *, model):
        self.payloads.append(payload)
        return {
            "candidates": [{"content": {"parts": [{"text": self._text}]}}],
            "usageMetadata": {"promptTokenCount": 4000, "totalTokenCount": 4100},
        }


# ---------------------------------------------------------------------------
# Lọc ảnh: KHÔNG lấy ảnh của người khác
# ---------------------------------------------------------------------------
def test_size_threshold_excludes_other_peoples_avatars() -> None:
    """Đo thật: ảnh bài đăng 340×340, avatar khách 288×288, avatar của mục
    "Những người khác có tên tương tự" chỉ 117×120.
    """
    assert playwright_dom.MIN_PHOTO_EDGE_PX > 120
    assert playwright_dom.MIN_PHOTO_EDGE_PX <= 288


def test_other_people_headings_cover_both_languages() -> None:
    headings = playwright_dom._OTHER_PEOPLE_HEADINGS
    assert any("tương tự" in h for h in headings)
    assert any("similar names" in h for h in headings)
    assert all(h == h.lower() for h in headings)


def test_photo_collector_js_filters_by_three_rules() -> None:
    """JS chạy trong trình duyệt nên không test được bằng pytest — kiểm bằng
    cách khẳng định cả ba bộ lọc còn trong mã.
    """
    js = playwright_dom._COLLECT_PHOTOS_JS
    assert "scontent" in js  # loại icon giao diện static.xx.fbcdn.net
    assert "naturalWidth" in js  # kích thước THẬT đã tải, không phải CSS
    assert "inOtherPeopleBlock" in js  # loại ảnh người khác


def test_photo_count_is_bounded() -> None:
    """Mỗi ảnh thêm vào là ~1500 token prompt — phải có trần."""
    assert 1 <= playwright_dom.MAX_PUBLIC_PHOTOS <= 5


def test_modal_close_selectors_target_facebooks_own_button() -> None:
    """Bấm nút đóng mà chính trang đưa ra là duyệt web bình thường.

    Không có selector nào nhắm vào việc gỡ bỏ lớp che bằng CSS/JS — đó mới là
    vượt rào.
    """
    selectors = playwright_dom._MODAL_CLOSE_SELECTORS
    assert all("aria-label" in s for s in selectors)
    assert not any("display" in s or "remove" in s for s in selectors)


# ---------------------------------------------------------------------------
# Tải + chuẩn hoá
# ---------------------------------------------------------------------------
@respx.mock
async def test_public_photos_are_downloaded_and_normalised(bundle, tmp_path) -> None:
    for url in PHOTO_URLS:
        respx.get(url).mock(return_value=httpx.Response(200, content=make_image(1600, 1600)))

    async with httpx.AsyncClient() as client:
        photos = await avatar_mod.fetch_public_photos(
            bundle, client=client, output_dir=str(tmp_path)
        )

    assert len(photos) == 3
    for photo in photos:
        assert photo.role == "public_photo"
        assert photo.mime_type == "image/webp"
        assert max(photo.width, photo.height) == 1024
    assert bundle.attempts[-1].ok is True


@respx.mock
async def test_sha256_is_attached_to_the_right_url(bundle, tmp_path) -> None:
    """Ảnh hỏng bị bỏ qua, nên ghép hai danh sách song song sẽ gắn **nhầm** sha256."""
    respx.get(PHOTO_URLS[0]).mock(return_value=httpx.Response(404))
    respx.get(PHOTO_URLS[1]).mock(return_value=httpx.Response(200, content=make_image(400, 400)))
    respx.get(PHOTO_URLS[2]).mock(return_value=httpx.Response(200, content=make_image(500, 500)))

    async with httpx.AsyncClient() as client:
        photos = await avatar_mod.fetch_public_photos(
            bundle, client=client, output_dir=str(tmp_path)
        )

    assert len(photos) == 2
    by_url = {image.url: image for image in bundle.images}
    # Ảnh 404 không được gắn sha256 của ảnh khác.
    assert by_url[PHOTO_URLS[0]].sha256 is None
    assert by_url[PHOTO_URLS[1]].sha256 == photos[0].sha256
    assert by_url[PHOTO_URLS[2]].sha256 == photos[1].sha256


@respx.mock
async def test_one_broken_photo_does_not_lose_the_others(bundle, tmp_path) -> None:
    respx.get(PHOTO_URLS[0]).mock(return_value=httpx.Response(200, text="<html>loi</html>"))
    respx.get(PHOTO_URLS[1]).mock(return_value=httpx.Response(200, content=make_image(400, 400)))
    respx.get(PHOTO_URLS[2]).mock(side_effect=httpx.ConnectTimeout("hết hạn"))

    async with httpx.AsyncClient() as client:
        photos = await avatar_mod.fetch_public_photos(
            bundle, client=client, output_dir=str(tmp_path)
        )

    assert len(photos) == 1
    assert "2 ảnh bỏ qua" in bundle.attempts[-1].note


async def test_no_public_photos_means_no_attempt_noise(tmp_path) -> None:
    empty = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")

    assert await avatar_mod.fetch_public_photos(empty, output_dir=str(tmp_path)) == []
    assert empty.attempts == []


@respx.mock
async def test_photo_limit_is_respected(bundle, tmp_path) -> None:
    for url in PHOTO_URLS:
        respx.get(url).mock(return_value=httpx.Response(200, content=make_image(300, 300)))

    async with httpx.AsyncClient() as client:
        photos = await avatar_mod.fetch_public_photos(
            bundle, client=client, output_dir=str(tmp_path), limit=2
        )

    assert len(photos) == 2


# ---------------------------------------------------------------------------
# Bước vision nhận nhiều ảnh
# ---------------------------------------------------------------------------
async def test_vision_sends_avatar_plus_public_photos(catalog) -> None:
    gateway = VisionGateway()
    avatar = avatar_mod.normalize(make_image(400, 400))
    photos = [avatar_mod.normalize(make_image(300, 300)) for _ in range(2)]

    result = await describe_avatar(
        avatar, gateway, model="m", catalog=catalog, public_photos=photos
    )

    parts = gateway.payloads[0]["contents"][0]["parts"]
    image_parts = [p for p in parts if "inline_data" in p]
    assert len(image_parts) == 3  # 1 avatar + 2 ảnh công khai
    assert result.image_count == 3


async def test_vision_prompt_states_how_many_images(catalog) -> None:
    gateway = VisionGateway()
    avatar = avatar_mod.normalize(make_image(400, 400))
    photos = [avatar_mod.normalize(make_image(300, 300))]

    await describe_avatar(avatar, gateway, model="m", catalog=catalog, public_photos=photos)

    system = gateway.payloads[0]["systemInstruction"]["parts"][0]["text"]
    assert "2 ảnh" in system
    assert "ảnh công khai gần nhất" in system


async def test_vision_still_works_with_avatar_only(catalog) -> None:
    gateway = VisionGateway()
    avatar = avatar_mod.normalize(make_image(400, 400))

    result = await describe_avatar(avatar, gateway, model="m", catalog=catalog)

    parts = gateway.payloads[0]["contents"][0]["parts"]
    assert len([p for p in parts if "inline_data" in p]) == 1
    assert result.image_count == 1


async def test_public_photos_alone_still_produce_a_description(catalog) -> None:
    """Không có avatar nhưng có ảnh công khai → vẫn mô tả được, không bỏ phí."""
    gateway = VisionGateway()
    photos = [avatar_mod.normalize(make_image(300, 300))]

    result = await describe_avatar(None, gateway, model="m", catalog=catalog, public_photos=photos)

    assert result.ok is True
    assert result.image_count == 1


async def test_no_images_at_all_still_returns_none(catalog) -> None:
    gateway = VisionGateway()

    result = await describe_avatar(None, gateway, model="m", catalog=catalog, public_photos=[])

    assert result.description is None
    assert gateway.payloads == []


# ---------------------------------------------------------------------------
# Trang bị chặn chữ nhưng vẫn lấy được ảnh
# ---------------------------------------------------------------------------
def test_blocked_text_with_photos_is_reported_honestly() -> None:
    """Nói đúng **cả hai** nửa: chữ bị khoá, ảnh thì không."""
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="public_photo", url=PHOTO_URLS[0]))

    result = playwright_dom.parse_into("<html><body>Đăng nhập vào Facebook</body></html>", b)

    assert result.attempts[-1].ok is True  # có thu được thứ gì đó
    assert "1 ảnh công khai" in result.attempts[-1].note
    assert "khoá phần chữ" in result.attempts[-1].note
    assert "ảnh công khai" in (result.blocked_reason or "")


def test_blocked_text_without_photos_says_nothing_was_read() -> None:
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")

    result = playwright_dom.parse_into("<html><body>Đăng nhập vào Facebook</body></html>", b)

    assert result.attempts[-1].ok is False
    assert "dán nội dung tay" in (result.blocked_reason or "")


def test_public_photos_survive_the_json_round_trip() -> None:
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_URL, sha256="a"))
    b.add_image(EvidenceImage(role="public_photo", url=PHOTO_URLS[0], sha256="b"))

    restored = EvidenceBundle.from_dict(b.to_dict())

    roles = [image.role for image in restored.images]
    assert roles == ["avatar", "public_photo"]
    assert restored.avatar.sha256 == "a"


# ---------------------------------------------------------------------------
# Không gửi cùng một tấm ảnh hai lần
# ---------------------------------------------------------------------------
# URL thật: `og:image` là bản đã crop (`?cstp=mx292x173`), lưới phục vụ đúng
# tấm đó ở kích thước đầy đủ. Cùng path, khác query.
SAME_PHOTO_PATH = "/v/t39.30808-1/489728770_1863751037521680_320808922.jpg"
AVATAR_CROPPED = f"https://scontent.test{SAME_PHOTO_PATH}?stp=dst-jpg&cstp=mx292x173"
AVATAR_FULL = f"https://scontent.test{SAME_PHOTO_PATH}?stp=dst-jpg&_nc_cat=104"


@respx.mock
async def test_avatar_is_not_sent_again_as_a_public_photo(tmp_path) -> None:
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_CROPPED))
    b.add_image(EvidenceImage(role="public_photo", url=AVATAR_FULL))
    b.add_image(EvidenceImage(role="public_photo", url=PHOTO_URLS[0]))

    respx.get(PHOTO_URLS[0]).mock(return_value=httpx.Response(200, content=make_image(340, 340)))

    async with httpx.AsyncClient() as client:
        photos = await avatar_mod.fetch_public_photos(b, client=client, output_dir=str(tmp_path))

    # Chỉ còn tấm thật sự khác — gửi lại avatar tốn ~1500 token mà không thêm gì.
    assert len(photos) == 1


@respx.mock
async def test_avatar_prefers_the_uncropped_grid_version(tmp_path) -> None:
    """`og:image` là thumbnail đã crop (I-17); lưới có bản vuông nét hơn."""
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_CROPPED))
    b.add_image(EvidenceImage(role="public_photo", url=AVATAR_FULL))

    cropped = respx.get(url=AVATAR_CROPPED).mock(
        return_value=httpx.Response(200, content=make_image(292, 173))
    )
    full = respx.get(url=AVATAR_FULL).mock(
        return_value=httpx.Response(200, content=make_image(288, 288))
    )

    async with httpx.AsyncClient() as client:
        avatar = await avatar_mod.fetch_and_normalize(b, client=client, output_dir=str(tmp_path))

    assert full.called
    assert not cropped.called
    assert (avatar.width, avatar.height) == (288, 288)


@respx.mock
async def test_avatar_falls_back_to_og_image_when_no_grid_version(tmp_path) -> None:
    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_image(EvidenceImage(role="avatar", url=AVATAR_CROPPED))

    respx.get(url=AVATAR_CROPPED).mock(
        return_value=httpx.Response(200, content=make_image(292, 173))
    )

    async with httpx.AsyncClient() as client:
        avatar = await avatar_mod.fetch_and_normalize(b, client=client, output_dir=str(tmp_path))

    assert (avatar.width, avatar.height) == (292, 173)


def test_photo_key_ignores_size_parameters() -> None:
    assert avatar_mod._photo_key(AVATAR_CROPPED) == avatar_mod._photo_key(AVATAR_FULL)
    assert avatar_mod._photo_key(AVATAR_CROPPED) != avatar_mod._photo_key(PHOTO_URLS[0])


# ---------------------------------------------------------------------------
# Mô tả ảnh là bằng chứng, nên GroundingValidator phải thấy nó
# ---------------------------------------------------------------------------
async def test_vision_description_enters_the_evidence_corpus(catalog, tmp_path) -> None:
    """Không đưa `visual_context` vào corpus thì một tin nhắn nhắc đúng điều
    trong ảnh vẫn bị `GroundingValidator` coi là "không có bằng chứng".
    """
    from app.services.profiler import build_profile

    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_field(
        "customer_name", "Unclee Vander", source="og_meta", evidence="og:title", confidence=0.95
    )
    gateway = VisionGateway(text="Một nhóm người đang thi đấu bóng đá trên sân cỏ.")
    avatar = avatar_mod.normalize(make_image(300, 300))

    profile = await build_profile(b, gateway, model="m", avatar=avatar, catalog=catalog)

    corpus = b.evidence_corpus()
    assert "bóng đá" in corpus
    assert profile.visual_context in corpus


async def test_vision_evidence_cites_the_image_hashes(catalog) -> None:
    """Bằng chứng phải truy vết về **đúng** những ảnh đã mô tả."""
    from app.services.profiler import build_profile

    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    avatar = avatar_mod.normalize(make_image(300, 300))
    photos = [avatar_mod.normalize(make_image(340, 340))]

    await build_profile(
        b, VisionGateway(), model="m", avatar=avatar, public_photos=photos, catalog=catalog
    )

    field = b.get_field("visual_context")
    assert field is not None
    assert field.source == "vision_avatar"
    assert "2 ảnh" in field.evidence
    assert avatar.sha256[:12] in field.evidence
    assert photos[0].sha256[:12] in field.evidence


async def test_no_vision_description_means_no_vision_field(catalog) -> None:
    """Không mô tả được thì không được tạo bằng chứng rỗng (luật L1)."""
    from app.services.profiler import build_profile

    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    b.add_field("customer_name", "Lan", source="og_meta", evidence="og:title", confidence=0.95)

    await build_profile(b, VisionGateway(), model="m", avatar=None, catalog=catalog)

    assert b.get_field("visual_context") is None


async def test_vision_evidence_has_lower_confidence_than_read_text(catalog) -> None:
    """Mô tả ảnh là *diễn giải*, không chắc bằng chữ đọc trực tiếp."""
    from app.services.profiler import build_profile

    b = EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")
    avatar = avatar_mod.normalize(make_image(300, 300))

    await build_profile(b, VisionGateway(), model="m", avatar=avatar, catalog=catalog)

    vision_field = b.get_field("visual_context")
    assert vision_field.confidence < 0.95  # og:title
