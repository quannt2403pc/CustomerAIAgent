"""D1.13 — collector L3 Playwright.

Chromium không chạy trong test suite (nặng, và image mặc định không có nó), nên
test tách làm hai phần: **nhánh điều khiển** (cờ tắt, thiếu gói, lỗi) chạy thật,
và **bóc dữ kiện** (`parse_into`) chạy trên fixture DOM đã render.
"""

from __future__ import annotations

import builtins
import pathlib

import pytest

from app.collectors import playwright_dom
from app.collectors.evidence import EvidenceBundle
from app.collectors.url import normalize_facebook_url
from app.core.config import get_settings

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def target():
    return normalize_facebook_url("https://www.facebook.com/example_user")


@pytest.fixture
def bundle(target):
    return EvidenceBundle(url_key=target.url_key, facebook_url=target.canonical_url)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Cờ tắt → bỏ qua, không lỗi
# ---------------------------------------------------------------------------
async def test_disabled_flag_skips_without_error(target, bundle, monkeypatch) -> None:
    """DoD D1.13: tắt cờ → pipeline bỏ qua lớp này, `attempts[]` ghi `skipped`."""
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "false")
    get_settings.cache_clear()

    result = await playwright_dom.collect(target, bundle)

    attempt = result.attempts[-1]
    assert attempt.layer == "playwright"
    assert attempt.skipped is True
    assert attempt.ok is False
    assert "PLAYWRIGHT_ENABLED=false" in attempt.note
    assert result.is_empty is True


async def test_disabled_by_default(target, bundle) -> None:
    """Mặc định phải tắt — image Docker mặc định không có Chromium."""
    assert get_settings().playwright_enabled is False


# ---------------------------------------------------------------------------
# Bật cờ nhưng chưa cài gói → nói rõ cách cài, không raise
# ---------------------------------------------------------------------------
async def test_missing_package_explains_how_to_install(
    target, bundle, enabled, monkeypatch
) -> None:
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = await playwright_dom.collect(target, bundle)

    attempt = result.attempts[-1]
    assert attempt.skipped is True
    assert "playwright install chromium" in attempt.note
    assert "--target playwright" in attempt.note


# ---------------------------------------------------------------------------
# Bóc dữ kiện từ DOM đã render
# ---------------------------------------------------------------------------
def test_rendered_dom_yields_name_bio_posts_and_avatar(bundle) -> None:
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")

    result = playwright_dom.parse_into(html, bundle, screenshot_path="var/screenshots/x.png")

    assert result.value_of("customer_name") == "Nguyễn Thị Lan"
    assert "Mẹ hai bé" in (result.value_of("bio") or "")
    assert "bữa cơm tối" in (result.value_of("post_text") or "")
    assert result.avatar is not None
    assert "fbcdn.net" in result.avatar.url
    assert result.attempts[-1].ok is True


def test_screenshot_path_is_recorded_as_evidence(bundle) -> None:
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")

    result = playwright_dom.parse_into(html, bundle, screenshot_path="var/screenshots/x.png")

    assert "var/screenshots/x.png" in result.attempts[-1].note


def test_fields_carry_source_and_evidence(bundle) -> None:
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")
    result = playwright_dom.parse_into(html, bundle)

    for item in result.fields:
        assert item.source == "playwright_dom"
        assert item.evidence
        assert 0 < item.confidence <= 1


def test_rendered_name_yields_to_og_title(bundle) -> None:
    """og:title (0.95) chắc hơn tiêu đề DOM (0.9) — không ghi đè nguồn chắc hơn."""
    bundle.add_field(
        "customer_name", "Tên từ og", source="og_meta", evidence="og:title", confidence=0.95
    )
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")

    playwright_dom.parse_into(html, bundle)

    assert bundle.value_of("customer_name") == "Tên từ og"


def test_navigation_labels_are_not_taken_as_posts(bundle) -> None:
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")
    result = playwright_dom.parse_into(html, bundle)

    posts = result.value_of("post_text") or ""
    for chrome in ("Trang chủ", "Bạn bè", "Thông báo", "Chính sách quyền riêng tư"):
        assert chrome not in posts


def test_login_wall_after_rendering_is_reported(bundle) -> None:
    """Render JS xong vẫn là trang đăng nhập → nói thật, hướng sang dán tay."""
    html = """
    <html><head><title>Facebook</title></head>
    <body>Đăng nhập vào Facebook. Tạo tài khoản mới.</body></html>
    """

    result = playwright_dom.parse_into(html, bundle)

    assert result.is_empty is True
    assert result.attempts[-1].ok is False
    assert "render JS" in result.attempts[-1].note
    assert "dán nội dung tay" in (result.blocked_reason or "")


def test_title_suffixes_are_stripped(bundle) -> None:
    html = """
    <html><head><title>Unclee Vander (@yazawanico24111) • Facebook, Connect with friends</title>
    </head><body></body></html>
    """
    result = playwright_dom.parse_into(html, bundle)
    assert result.value_of("customer_name") == "Unclee Vander"


def test_generic_title_is_not_taken_as_a_name(bundle) -> None:
    html = "<html><head><title>Facebook</title></head><body></body></html>"
    result = playwright_dom.parse_into(html, bundle)
    assert result.value_of("customer_name") is None


def test_empty_dom_is_recorded_as_a_failed_attempt(bundle) -> None:
    result = playwright_dom.parse_into("<html><body></body></html>", bundle)

    assert result.is_empty is True
    assert result.attempts[-1].ok is False
    assert "không bóc được" in result.attempts[-1].note


# ---------------------------------------------------------------------------
# Cookie người dùng tự cung cấp
# ---------------------------------------------------------------------------
def test_cookie_header_is_converted_for_playwright() -> None:
    cookies = playwright_dom._cookies_from_header("c_user=100012345; xs=99%3Aabcd; rác")

    assert {c["name"] for c in cookies} == {"c_user", "xs"}
    assert all(c["domain"] == ".facebook.com" for c in cookies)


def test_empty_cookie_header_yields_nothing() -> None:
    assert playwright_dom._cookies_from_header("") == []


# ---------------------------------------------------------------------------
# Giới hạn trung thực
# ---------------------------------------------------------------------------
def test_user_agent_is_a_real_mobile_browser() -> None:
    """Không giả mạo crawler của ai khác (plan.md §5.2)."""
    agent = playwright_dom.MOBILE_USER_AGENT
    assert "Mobile" in agent
    assert "facebookexternalhit" not in agent
    assert "googlebot" not in agent.lower()


def test_pipeline_records_playwright_as_skipped_when_not_implemented_path(bundle) -> None:
    """`run_analysis` phải ghi lại là đã cân nhắc lớp này, không im lặng bỏ qua."""
    import inspect

    from app.services import pipeline

    source = inspect.getsource(pipeline.run_analysis)
    assert "playwright" in source


# ---------------------------------------------------------------------------
# Ảnh chụp đi vào `profile_evidence.screenshot_path`
# ---------------------------------------------------------------------------
def test_screenshot_path_lands_on_the_bundle(bundle) -> None:
    """DoD D1.13: ảnh chụp phải được tham chiếu trong `profile_evidence.screenshot_path`."""
    html = (FIXTURES / "playwright_rendered.html").read_text(encoding="utf-8")

    result = playwright_dom.parse_into(html, bundle, screenshot_path="var/screenshots/x.png")

    assert result.screenshot_path == "var/screenshots/x.png"
    assert result.to_dict()["screenshot_path"] == "var/screenshots/x.png"


def test_screenshot_is_kept_even_on_a_login_wall(bundle) -> None:
    """Ảnh chụp trang đăng nhập **cũng** là bằng chứng cho "không đọc được"."""
    html = "<html><body>Đăng nhập vào Facebook</body></html>"

    result = playwright_dom.parse_into(html, bundle, screenshot_path="var/screenshots/wall.png")

    assert result.is_empty is True
    assert result.screenshot_path == "var/screenshots/wall.png"


def test_screenshot_path_survives_the_json_round_trip(bundle) -> None:
    from app.collectors.evidence import EvidenceBundle

    bundle.screenshot_path = "var/screenshots/x.png"
    restored = EvidenceBundle.from_dict(bundle.to_dict())
    assert restored.screenshot_path == "var/screenshots/x.png"
