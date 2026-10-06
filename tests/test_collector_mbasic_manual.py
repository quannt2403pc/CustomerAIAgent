"""D1.12 — collector L2 (`mbasic`) + L4 (dán tay) + giới hạn 1 req/s.

Fixture HTML ở đây **đã xoá PII thật**: dùng dữ liệu bịa hoàn toàn, chỉ giữ lại
*cấu trúc* và các chuỗi tiếng Việt đo được từ phản hồi thật (task.md D1.12 DoD).
"""

from __future__ import annotations

import pathlib

import httpx
import pytest
import respx

from app.collectors import mbasic
from app.collectors.evidence import EvidenceBundle
from app.collectors.manual import collect_from_text, save_uploaded_avatar
from app.collectors.throttle import HostRateLimiter
from app.collectors.url import normalize_facebook_url
from app.core.errors import CollectorError

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def target():
    return normalize_facebook_url("https://www.facebook.com/example_user")


@pytest.fixture
def bundle(target):
    return EvidenceBundle(url_key=target.url_key, facebook_url=target.canonical_url)


# ---------------------------------------------------------------------------
# L2 — đọc được
# ---------------------------------------------------------------------------
def test_mbasic_profile_yields_name_bio_and_posts(bundle) -> None:
    html = (FIXTURES / "mbasic_profile.html").read_text(encoding="utf-8")

    result = mbasic.parse_into(html, bundle)

    assert result.value_of("customer_name") == "Nguyễn Thị Lan"
    assert "Mẹ hai bé" in (result.value_of("bio") or "")
    assert "bữa cơm tối" in (result.value_of("post_text") or "")
    assert result.attempts[-1].ok is True


def test_mbasic_fields_carry_evidence(bundle) -> None:
    html = (FIXTURES / "mbasic_profile.html").read_text(encoding="utf-8")
    result = mbasic.parse_into(html, bundle)

    for item in result.fields:
        assert item.source == "mbasic_html"
        assert item.evidence
        assert 0 < item.confidence <= 1


def test_mbasic_name_has_lower_confidence_than_og_title(bundle) -> None:
    """Heading mbasic dễ lẫn tên mục/tên trang → phải nhường og:title."""
    bundle.add_field(
        "customer_name", "Tên từ og", source="og_meta", evidence="og:title", confidence=0.95
    )
    html = (FIXTURES / "mbasic_profile.html").read_text(encoding="utf-8")

    mbasic.parse_into(html, bundle)

    assert bundle.value_of("customer_name") == "Tên từ og"


def test_navigation_chrome_is_not_taken_as_a_post(bundle) -> None:
    html = (FIXTURES / "mbasic_profile.html").read_text(encoding="utf-8")
    result = mbasic.parse_into(html, bundle)

    posts = result.value_of("post_text") or ""
    assert "Chính sách quyền riêng tư" not in posts
    assert "Xem thêm" not in posts


# ---------------------------------------------------------------------------
# L2 — login wall (tình huống đo thật)
# ---------------------------------------------------------------------------
def test_mbasic_login_wall_returns_http_200(bundle) -> None:
    """Đo thật 2026-10-06: mbasic trả **200** kèm trang đăng nhập (I-14).

    Đọc theo status code sẽ tưởng thành công rồi parse ra rỗng một cách vô nghĩa.
    """
    html = (FIXTURES / "mbasic_login_wall.html").read_text(encoding="utf-8")

    result = mbasic.parse_into(html, bundle, http_status=200)

    assert result.is_empty is True
    assert result.attempts[-1].ok is False
    assert result.attempts[-1].http_status == 200
    assert "đăng nhập" in result.attempts[-1].note
    assert "dán nội dung tay" in (result.blocked_reason or "")


@respx.mock
async def test_mbasic_http_error_is_recorded_not_raised(target, bundle) -> None:
    respx.get(target.mbasic_url).mock(return_value=httpx.Response(400, text="Error"))

    async with httpx.AsyncClient() as client:
        result = await mbasic.collect(target, bundle, client=client)

    assert result.attempts[-1].http_status == 400
    assert result.attempts[-1].ok is False


@respx.mock
async def test_mbasic_network_error_is_recorded_not_raised(target, bundle) -> None:
    respx.get(target.mbasic_url).mock(side_effect=httpx.ConnectTimeout("hết hạn"))

    async with httpx.AsyncClient() as client:
        result = await mbasic.collect(target, bundle, client=client)

    assert "lỗi mạng" in result.attempts[-1].note


@respx.mock
async def test_user_supplied_cookie_is_sent_but_never_logged(target, bundle, capsys) -> None:
    from app.core.logging import setup_logging

    setup_logging("DEBUG", force=True)
    route = respx.get(target.mbasic_url).mock(
        return_value=httpx.Response(200, text="<html></html>")
    )
    cookie = "c_user=100012345; xs=99%3Atest-only-not-a-secret"

    async with httpx.AsyncClient() as client:
        await mbasic.collect(target, bundle, client=client, cookie=cookie)

    assert route.calls[0].request.headers["cookie"] == cookie
    err = capsys.readouterr().err
    assert "100012345" not in err
    assert "test-only-not-a-secret" not in err


# ---------------------------------------------------------------------------
# Giới hạn 1 req/s giữa các lớp
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_limiter_waits_between_two_requests_to_facebook() -> None:
    clock = FakeClock()
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)
        clock.now += delay

    limiter = HostRateLimiter(1.0, clock=clock, sleep=sleep)

    assert await limiter.wait("https://www.facebook.com/a") == 0.0
    clock.now += 0.3
    assert await limiter.wait("https://www.facebook.com/b") == pytest.approx(0.7)
    assert slept == [pytest.approx(0.7)]


async def test_limiter_treats_all_facebook_subdomains_as_one_budget() -> None:
    """Tính hạn mức riêng cho `mbasic.` và `www.` là tự lách luật của chính mình."""
    clock = FakeClock()

    async def sleep(delay: float) -> None:
        clock.now += delay

    limiter = HostRateLimiter(1.0, clock=clock, sleep=sleep)

    await limiter.wait("https://www.facebook.com/a")
    waited = await limiter.wait("https://mbasic.facebook.com/a")

    assert waited == pytest.approx(1.0)


async def test_limiter_does_not_delay_unrelated_hosts() -> None:
    clock = FakeClock()

    async def sleep(delay: float) -> None:
        clock.now += delay

    limiter = HostRateLimiter(1.0, clock=clock, sleep=sleep)

    await limiter.wait("https://www.facebook.com/a")
    assert await limiter.wait("https://example.test/a") == 0.0


@respx.mock
async def test_collect_honours_the_limiter(target, bundle) -> None:
    respx.get(target.mbasic_url).mock(return_value=httpx.Response(200, text="<html></html>"))
    seen: list[str] = []

    class RecordingLimiter:
        async def wait(self, url: str) -> float:
            seen.append(url)
            return 0.0

    async with httpx.AsyncClient() as client:
        await mbasic.collect(target, bundle, client=client, limiter=RecordingLimiter())

    assert seen == [target.mbasic_url]


# ---------------------------------------------------------------------------
# L4 — dán tay
# ---------------------------------------------------------------------------
def test_labelled_paste_maps_to_fields(bundle) -> None:
    result = collect_from_text(
        "Tên: Nguyễn Thị Lan\n"
        "Tiểu sử: Mẹ hai bé, bán hàng online\n"
        "Nơi ở: Hà Nội\n"
        "Bài viết: Hôm nay con bé đi học về kể chuyện cô giáo mới.\n",
        bundle,
    )

    assert result.value_of("customer_name") == "Nguyễn Thị Lan"
    assert result.value_of("bio") == "Mẹ hai bé, bán hàng online"
    assert result.value_of("location") == "Hà Nội"
    assert "cô giáo mới" in (result.value_of("post_text") or "")


def test_manual_confidence_is_highest_because_a_human_saw_it(bundle) -> None:
    bundle.add_field(
        "customer_name", "Tên từ og", source="og_meta", evidence="og:title", confidence=0.95
    )
    collect_from_text("Tên: Tên người vận hành đọc được", bundle)
    assert bundle.value_of("customer_name") == "Tên người vận hành đọc được"


def test_free_form_paste_does_not_guess_the_name(bundle) -> None:
    """Đoán dòng đầu là tên thì sai lúc nào không biết — đó là bịa (luật L1)."""
    result = collect_from_text(
        "Hôm nay trời Hà Nội trở lạnh. Cả nhà vừa ăn xong bữa cơm tối.", bundle
    )

    assert result.value_of("customer_name") is None
    assert "bữa cơm tối" in (result.value_of("post_text") or "")
    assert "không đoán tên" in result.attempts[-1].note


def test_unknown_labels_are_kept_as_text_not_dropped(bundle) -> None:
    result = collect_from_text("Sở thích lạ: nuôi cá\nTên: Lan", bundle)

    assert result.value_of("customer_name") == "Lan"
    # Dòng nhãn lạ vẫn là nội dung thật — không được bỏ đi.
    assert "nuôi cá" in (result.value_of("post_text") or "")


def test_repeated_label_is_appended_not_overwritten(bundle) -> None:
    result = collect_from_text(
        "Bài viết: Đoạn một dài đủ để không bị lọc.\nBài viết: Đoạn hai cũng vậy.", bundle
    )
    posts = result.value_of("post_text") or ""
    assert "Đoạn một" in posts
    assert "Đoạn hai" in posts


def test_empty_paste_is_recorded_as_a_failed_attempt(bundle) -> None:
    result = collect_from_text("   \n  ", bundle)

    assert result.is_empty is True
    assert result.attempts[-1].ok is False
    assert "chưa dán" in result.attempts[-1].note


def test_manual_path_needs_no_network(bundle) -> None:
    """`python main.py --profile-file …` phải chạy được khi không có mạng."""
    result = collect_from_text("Tên: Lan\nTiểu sử: Mẹ hai bé", bundle)
    assert result.is_empty is False


# ---------------------------------------------------------------------------
# L4 — ảnh tải lên
# ---------------------------------------------------------------------------
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
)


def test_uploaded_image_is_named_by_sha256(bundle, tmp_path) -> None:
    image = save_uploaded_avatar(PNG_BYTES, bundle, mime_type="image/png", upload_dir=str(tmp_path))

    assert image.sha256 is not None
    assert image.local_path is not None
    assert image.sha256 in image.local_path  # tên gốc do người ngoài đặt bị loại bỏ
    assert pathlib.Path(image.local_path).read_bytes() == PNG_BYTES
    assert bundle.has_avatar is True


def test_same_image_twice_does_not_duplicate(bundle, tmp_path) -> None:
    save_uploaded_avatar(PNG_BYTES, bundle, mime_type="image/png", upload_dir=str(tmp_path))
    save_uploaded_avatar(PNG_BYTES, bundle, mime_type="image/png", upload_dir=str(tmp_path))
    assert len(bundle.images) == 1


@pytest.mark.parametrize("mime", ["image/svg+xml", "text/html", "application/pdf"])
def test_disallowed_mime_is_refused(bundle, tmp_path, mime: str) -> None:
    with pytest.raises(CollectorError, match="không được nhận"):
        save_uploaded_avatar(PNG_BYTES, bundle, mime_type=mime, upload_dir=str(tmp_path))


def test_empty_file_is_refused(bundle, tmp_path) -> None:
    with pytest.raises(CollectorError, match="rỗng"):
        save_uploaded_avatar(b"", bundle, mime_type="image/png", upload_dir=str(tmp_path))


def test_oversized_file_is_refused(bundle, tmp_path) -> None:
    from app.collectors.manual import MAX_IMAGE_BYTES

    with pytest.raises(CollectorError, match="lớn hơn giới hạn"):
        save_uploaded_avatar(
            b"x" * (MAX_IMAGE_BYTES + 1), bundle, mime_type="image/png", upload_dir=str(tmp_path)
        )
