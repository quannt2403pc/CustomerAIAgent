"""Bộ chắn văn bản dùng chung — canh gác một lỗi L1 đã xảy ra thật.

Chạy L3 Playwright trên link thật, Facebook trả trang "Trình duyệt này không
được hỗ trợ" và code **nhận câu đó làm tên khách** với confidence 0.9
(task.md I-29). Mọi tin nhắn sau đó sẽ gọi khách bằng một cái tên bịa.

Nguyên nhân gốc: ba lớp collector mỗi lớp giữ một bản danh sách marker riêng,
nên marker mới chỉ được thêm vào một chỗ.
"""

from __future__ import annotations

import pytest

from app.collectors import mbasic, og_meta, playwright_dom
from app.collectors.evidence import EvidenceBundle
from app.collectors.text_guards import (
    LOGIN_WALL_MARKERS,
    is_blocked_page,
    looks_like_a_person_name,
)

# Chuỗi **nguyên văn** Facebook trả cho Chromium headless, đo 2026-10-06.
REAL_UNSUPPORTED_BROWSER = """
<html><head><title>Trình duyệt này không được hỗ trợ</title></head>
<body>
  <h1>Trình duyệt này không được hỗ trợ</h1>
  <div>Những người khác có tên tương tự</div>
  <div>Đăng nhập để xem bài viết của tài khoản này và tìm nhiều nội dung khác</div>
</body></html>
"""


@pytest.fixture
def bundle():
    return EvidenceBundle(url_key="user:x", facebook_url="https://www.facebook.com/x")


# ---------------------------------------------------------------------------
# Chuỗi giao diện KHÔNG được thành tên khách
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ui_copy",
    [
        "Trình duyệt này không được hỗ trợ",
        "Đăng nhập để xem bài viết của tài khoản này",
        "Những người khác có tên tương tự",
        "This browser is not supported",
        "Log in to see photos and videos from friends",
        "Bạn phải đăng nhập để tiếp tục",
        "Vui lòng thử lại sau",
        "Facebook",
        "Trang chủ",
        "Error",
    ],
)
def test_facebook_ui_copy_is_never_a_person_name(ui_copy: str) -> None:
    assert looks_like_a_person_name(ui_copy) is False


@pytest.mark.parametrize(
    "real_name",
    [
        "Nguyễn Thị Lan",
        "Unclee Vander",
        "Trần Văn Bình",
        "Lê Thị Mỹ Duyên",
        "Đỗ Quyên",
        "John Smith",
        "Hoàng Anh",
    ],
)
def test_real_names_still_pass(real_name: str) -> None:
    """Thắt quá tay cũng là lỗi: loại oan tên thật thì mất dữ kiện có thật."""
    assert looks_like_a_person_name(real_name) is True


@pytest.mark.parametrize("value", ["", " ", "A", "x" * 61, "Một Hai Ba Bốn Năm Sáu Bảy Tám Chín"])
def test_out_of_range_strings_are_refused(value: str) -> None:
    assert looks_like_a_person_name(value) is False


def test_sentence_punctuation_disqualifies_a_name() -> None:
    assert looks_like_a_person_name("Nguyễn Thị Lan.") is False
    assert looks_like_a_person_name("Thật vậy sao?") is False


# ---------------------------------------------------------------------------
# Trang chắn — cả ba lớp dùng CÙNG một danh sách marker
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "page",
    [
        "Đăng nhập vào Facebook",
        "Đăng nhập để xem bài viết của tài khoản này",
        "Những người khác có tên tương tự",
        "Trình duyệt này không được hỗ trợ",
        "This browser is not supported",
        "You must log in to continue",
        "Tạo tài khoản mới",
        "<div id=login_form>",
    ],
)
def test_blocked_pages_are_detected(page: str) -> None:
    assert is_blocked_page(page) is True


def test_a_real_profile_page_is_not_flagged_as_blocked() -> None:
    assert is_blocked_page("Nguyễn Thị Lan. Mẹ hai bé, bán hàng online tại Hà Nội.") is False


def test_all_three_collectors_share_one_marker_list() -> None:
    """Ba bản danh sách riêng là lý do marker mới chỉ được thêm vào một chỗ."""
    for module in (og_meta, mbasic, playwright_dom):
        assert not hasattr(module, "_LOGIN_WALL_MARKERS"), (
            f"{module.__name__} có danh sách marker riêng — phải dùng "
            "app.collectors.text_guards.LOGIN_WALL_MARKERS"
        )
        assert not hasattr(module, "_looks_like_a_name"), (
            f"{module.__name__} có guard tên riêng — phải dùng "
            "app.collectors.text_guards.looks_like_a_person_name"
        )


def test_marker_list_is_not_empty_and_lowercase() -> None:
    """`is_blocked_page` so trên chuỗi đã hạ chữ — marker viết hoa sẽ không khớp."""
    assert LOGIN_WALL_MARKERS
    assert all(marker == marker.lower() for marker in LOGIN_WALL_MARKERS)


# ---------------------------------------------------------------------------
# Cả ba lớp phải chặn đúng trang thật đã làm vỡ L3
# ---------------------------------------------------------------------------
def test_l3_no_longer_invents_a_name_from_the_unsupported_browser_page(bundle) -> None:
    """Đây **chính** là lỗi đã xảy ra: `customer_name` = "Trình duyệt này…"."""
    result = playwright_dom.parse_into(REAL_UNSUPPORTED_BROWSER, bundle)

    assert result.value_of("customer_name") is None
    assert result.is_empty is True
    assert result.attempts[-1].ok is False
    assert result.blocked_reason is not None


def test_l1_rejects_the_same_page(bundle) -> None:
    result = og_meta.parse_into(REAL_UNSUPPORTED_BROWSER, bundle)

    assert result.value_of("customer_name") is None
    assert result.is_empty is True


def test_l2_rejects_the_same_page(bundle) -> None:
    result = mbasic.parse_into(REAL_UNSUPPORTED_BROWSER, bundle)

    assert result.value_of("customer_name") is None
    assert result.is_empty is True


def test_login_gate_copy_does_not_become_post_text(bundle) -> None:
    """Chữ của cổng đăng nhập từng vào `post_text` — nó sẽ thành "bằng chứng"
    cho `GroundingValidator`, mở đường cho tin nhắn nhắc nội dung không có thật.
    """
    result = playwright_dom.parse_into(REAL_UNSUPPORTED_BROWSER, bundle)

    corpus = result.evidence_corpus()
    assert "Đăng nhập để xem" not in corpus
    assert "tên tương tự" not in corpus


def test_og_title_that_is_ui_copy_is_refused(bundle) -> None:
    html = """
    <html><head>
    <meta property="og:title" content="Trình duyệt này không được hỗ trợ">
    </head><body>trang bình thường không có marker nào</body></html>
    """
    result = og_meta.parse_into(html, bundle)
    assert result.value_of("customer_name") is None
