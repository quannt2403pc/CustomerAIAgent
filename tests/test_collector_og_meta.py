"""D1.11 — collector L1 + `EvidenceBundle`.

Hai điều được canh gác chặt:
- Mọi field đều **mang** `source` + `evidence` + `confidence`; không có bằng
  chứng thì không tạo field (luật L1).
- Login wall **không raise** — nó là sự thật về trang đó, đi vào `attempts[]`
  + `blocked_reason`.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.collectors import og_meta
from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceField, EvidenceImage
from app.collectors.url import normalize_facebook_url

PROFILE_URL = "https://www.facebook.com/example_user"

PUBLIC_HTML = """
<html><head>
<meta property="og:title" content="Nguyễn Thị Lan | Facebook">
<meta property="og:description" content="Mẹ hai bé, thích nấu ăn và chụp ảnh gia đình.">
<meta property="og:image" content="https://scontent.test/avatar.jpg">
</head><body>trang cá nhân</body></html>
"""

LOGIN_WALL_HTML = """
<html><head>
<meta property="og:title" content="Facebook">
<meta property="og:description" content="Create an account or log in to Facebook.">
</head><body><div id="login_form">You must log in to continue</div></body></html>
"""

ONLY_TITLE_HTML = """
<html><head><meta property="og:title" content="Trần Văn Bình"></head><body></body></html>
"""


@pytest.fixture
def target():
    return normalize_facebook_url(PROFILE_URL)


@pytest.fixture
def bundle(target):
    return EvidenceBundle(url_key=target.url_key, facebook_url=target.canonical_url)


# ---------------------------------------------------------------------------
# EvidenceField — luật L1 ở mức kiểu dữ liệu
# ---------------------------------------------------------------------------
def test_field_without_evidence_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="evidence"):
        EvidenceField(
            key="customer_name", value="Lan", source="og_meta", evidence="", confidence=0.9
        )


def test_field_with_empty_value_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="value rỗng"):
        EvidenceField(key="bio", value="", source="og_meta", evidence="<meta>", confidence=0.5)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_must_be_a_probability(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        EvidenceField(
            key="bio", value="x", source="og_meta", evidence="<meta>", confidence=confidence
        )


def test_add_field_skips_empty_value_instead_of_inventing(bundle) -> None:
    assert bundle.add_field("bio", None, source="og_meta", evidence="<meta>", confidence=0.5) is (
        False
    )
    assert bundle.value_of("bio") is None  # None nghĩa là "không có", không phải ""


def test_higher_confidence_wins_lower_is_ignored(bundle) -> None:
    bundle.add_field("customer_name", "Lan", source="og_meta", evidence="og", confidence=0.95)
    bundle.add_field("customer_name", "Lan B", source="mbasic_html", evidence="h1", confidence=0.7)
    assert bundle.value_of("customer_name") == "Lan"

    bundle.add_field(
        "customer_name", "Lan C", source="manual_paste", evidence="dán", confidence=1.0
    )
    assert bundle.value_of("customer_name") == "Lan C"


# ---------------------------------------------------------------------------
# Thu thập thành công
# ---------------------------------------------------------------------------
@respx.mock
async def test_public_profile_yields_fields_with_evidence(target, bundle) -> None:
    respx.get(PROFILE_URL).mock(return_value=httpx.Response(200, text=PUBLIC_HTML))

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    name = result.get_field("customer_name")
    assert name is not None
    assert name.value == "Nguyễn Thị Lan"  # hậu tố "| Facebook" đã bị bỏ
    assert name.source == "og_meta"
    assert "og:title" in name.evidence  # truy vết được về bằng chứng thật
    assert name.confidence > 0.9

    assert result.avatar is not None
    assert result.avatar.url == "https://scontent.test/avatar.jpg"
    assert result.blocked_reason is None
    assert result.attempts[-1].ok is True


@respx.mock
async def test_every_field_carries_source_evidence_confidence(target, bundle) -> None:
    respx.get(PROFILE_URL).mock(return_value=httpx.Response(200, text=PUBLIC_HTML))

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    assert result.fields
    for item in result.fields:
        assert item.source
        assert item.evidence
        assert 0 < item.confidence <= 1


def test_only_title_gives_exactly_one_field(bundle) -> None:
    result = og_meta.parse_into(ONLY_TITLE_HTML, bundle)

    assert result.value_of("customer_name") == "Trần Văn Bình"
    assert result.value_of("page_description") is None
    assert result.has_avatar is False


# ---------------------------------------------------------------------------
# Bị chặn — KHÔNG raise
# ---------------------------------------------------------------------------
def test_login_wall_is_recorded_not_raised(bundle) -> None:
    result = og_meta.parse_into(LOGIN_WALL_HTML, bundle)

    assert result.is_empty is True
    assert result.blocked_reason is not None
    assert "đăng nhập" in result.blocked_reason
    assert result.attempts[-1].ok is False


def test_generic_login_title_is_not_taken_as_a_name(bundle) -> None:
    """`og:title` của trang login là "Facebook" — lấy nó làm tên khách là bịa."""
    result = og_meta.parse_into(LOGIN_WALL_HTML, bundle)
    assert result.value_of("customer_name") is None


@respx.mock
async def test_404_is_recorded_not_raised(target, bundle) -> None:
    respx.get(PROFILE_URL).mock(return_value=httpx.Response(404, text="not found"))

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    assert result.attempts[-1].http_status == 404
    assert "404" in (result.blocked_reason or "")


@respx.mock
async def test_429_marks_rate_limited(target, bundle) -> None:
    respx.get(PROFILE_URL).mock(return_value=httpx.Response(429))

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    assert result.attempts[-1].http_status == 429
    assert "429" in (result.blocked_reason or "")


@respx.mock
async def test_network_error_is_recorded_not_raised(target, bundle) -> None:
    respx.get(PROFILE_URL).mock(side_effect=httpx.ConnectTimeout("hết hạn"))

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    assert result.attempts[-1].ok is False
    assert "lỗi mạng" in result.attempts[-1].note


# ---------------------------------------------------------------------------
# describe_coverage — nguồn của `error_note`
# ---------------------------------------------------------------------------
def test_coverage_of_empty_bundle_says_nothing_was_read(bundle) -> None:
    bundle.add_attempt(CollectAttempt(layer="og_meta", ok=False, http_status=403))
    text = bundle.describe_coverage()
    assert "Không thu thập được" in text
    assert "og_meta" in text
    assert "403" in text


def test_coverage_lists_what_was_actually_read(bundle) -> None:
    bundle.add_field("customer_name", "Lan", source="og_meta", evidence="og", confidence=0.9)
    text = bundle.describe_coverage()
    assert "customer_name" in text


# ---------------------------------------------------------------------------
# Vòng JSONB
# ---------------------------------------------------------------------------
def test_bundle_survives_json_round_trip(bundle) -> None:
    bundle.add_field("customer_name", "Lan", source="og_meta", evidence="og:title", confidence=0.95)
    bundle.add_image(EvidenceImage(role="avatar", url="https://x.test/a.jpg", sha256="abc"))
    bundle.add_attempt(CollectAttempt(layer="og_meta", ok=True, http_status=200))
    bundle.mark_blocked("một lý do")

    restored = EvidenceBundle.from_dict(bundle.to_dict())

    assert restored.to_dict() == bundle.to_dict()
    assert restored.value_of("customer_name") == "Lan"
    assert restored.avatar is not None


def test_mark_blocked_keeps_the_first_reason(bundle) -> None:
    """Lý do đầu tiên gần nguyên nhân gốc nhất; ghi đè sẽ che mất nó."""
    bundle.mark_blocked("login wall")
    bundle.mark_blocked("không có thẻ og")
    assert bundle.blocked_reason == "login wall"


# ---------------------------------------------------------------------------
# I-12 — header đầy đủ, nếu không Facebook trả 400 cho mọi URL
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "header",
    [
        "User-Agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "Sec-Fetch-Dest",
        "Sec-Fetch-Mode",
        "Sec-Fetch-Site",
        "Sec-Fetch-User",
        "Upgrade-Insecure-Requests",
        "Accept-Language",
    ],
)
def test_headers_include_what_a_real_chrome_sends(header: str) -> None:
    """Thiếu bất kỳ header nào trong nhóm này là Facebook trả 400 (đo thật I-12)."""
    assert header in og_meta.build_headers()


@respx.mock
async def test_collect_sends_the_full_header_set(target, bundle) -> None:
    route = respx.get(PROFILE_URL).mock(return_value=httpx.Response(200, text=PUBLIC_HTML))

    async with httpx.AsyncClient() as client:
        await og_meta.collect(target, bundle, client=client)

    sent = route.calls[0].request.headers
    assert sent["sec-ch-ua-platform"] == '"Windows"'
    assert sent["sec-fetch-mode"] == "navigate"


@respx.mock
async def test_400_explains_what_to_try_next(target, bundle) -> None:
    """400 là phản hồi Facebook thật dùng để chặn client không phải trình duyệt."""
    respx.get(PROFILE_URL).mock(
        return_value=httpx.Response(400, text="<title>Error</title>Sorry, something went wrong.")
    )

    async with httpx.AsyncClient() as client:
        result = await og_meta.collect(target, bundle, client=client)

    assert result.attempts[-1].http_status == 400
    assert "Playwright" in (result.blocked_reason or "")
    assert "dán nội dung tay" in (result.blocked_reason or "")


# ---------------------------------------------------------------------------
# I-14 — og:description là khuôn mẫu rỗng nghĩa, không phải bio
# ---------------------------------------------------------------------------
# Chuỗi **nguyên văn** Facebook trả cho một trang cá nhân thật (2026-10-06).
REAL_PROFILE_HTML = """
<html><head>
<meta property="og:type" content="video.other" />
<meta property="og:title" content="Unclee Vander" />
<meta property="og:description" content="Unclee Vander đang ở trên Facebook. Tham gia Facebook để kết nối với Unclee Vander và những người khác mà có thể bạn biết. Facebook trao cho mọi người quyền chia sẻ và mở rộng và kết nối thế giới." />
<meta property="og:url" content="https://www.facebook.com/yazawanico24111/" />
<meta property="og:image" content="https://scontent.test/v/t39.30808-1/489728770.jpg" />
<meta property="og:locale" content="en_US" />
</head><body></body></html>
"""


def test_real_profile_yields_name_and_avatar_but_no_fake_bio(bundle) -> None:
    result = og_meta.parse_into(REAL_PROFILE_HTML, bundle)

    assert result.value_of("customer_name") == "Unclee Vander"
    assert result.avatar is not None
    # Khuôn mẫu bị loại → KHÔNG có page_description giả.
    assert result.value_of("page_description") is None
    assert result.attempts[-1].ok is True


def test_generic_template_would_poison_the_grounding_corpus(bundle) -> None:
    """Nếu nhận khuôn mẫu làm evidence, `GroundingValidator` sẽ coi "kết nối",
    "chia sẻ", "thế giới" là dữ kiện có thật về khách — rò luật L1.
    """
    result = og_meta.parse_into(REAL_PROFILE_HTML, bundle)
    corpus = result.evidence_corpus()
    assert "Tham gia Facebook" not in corpus
    assert "quyền chia sẻ" not in corpus


@pytest.mark.parametrize(
    "description, is_generic",
    [
        (
            "Unclee Vander đang ở trên Facebook. Tham gia Facebook để kết nối với "
            "Unclee Vander và những người khác mà có thể bạn biết.",
            True,
        ),
        (
            "Lan is on Facebook. Join Facebook to connect with Lan and others you may know.",
            True,
        ),
        # Bio THẬT có nhắc chữ Facebook — không được loại oan.
        ("Mẹ hai bé. Bán hàng online, hay đăng ảnh con lên Facebook.", False),
        ("Yêu cây cảnh và cà phê sáng.", False),
        ("", False),
    ],
)
def test_generic_description_detection_needs_two_signals(description, is_generic) -> None:
    assert og_meta.is_generic_description(description) is is_generic


# ---------------------------------------------------------------------------
# I-14 — mbasic trả 200 nhưng là trang đăng nhập
# ---------------------------------------------------------------------------
# Chuỗi thật trên mbasic.facebook.com khi chưa đăng nhập (2026-10-06).
REAL_MBASIC_LOGIN_HTML = """
<html><head><title>Facebook</title></head><body>
Khám phá những điều bạn yêu thích . Đăng nhập vào Facebook
Email hoặc số di động Mật khẩu Đăng nhập Quên mật khẩu? Tạo tài khoản mới
</body></html>
"""


def test_vietnamese_login_wall_is_detected(bundle) -> None:
    """Marker phải là "đăng nhập vào facebook" — thiếu chữ "vào" là không khớp."""
    result = og_meta.parse_into(REAL_MBASIC_LOGIN_HTML, bundle)

    assert result.is_empty is True
    assert "đăng nhập" in (result.blocked_reason or "")
    assert result.attempts[-1].note == "Facebook trả trang đăng nhập"
