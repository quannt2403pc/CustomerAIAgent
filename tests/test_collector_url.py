"""D1.11 — chuẩn hoá URL Facebook.

Bảng 12 URL vào → `url_key` ra (task.md D1.11 DoD). Cùng một người, dù link đến
từ đâu, phải cho ra **một** `url_key` — nếu không, `profiles` đầy bản ghi trùng.
"""

from __future__ import annotations

import pytest

from app.collectors.url import normalize_facebook_url, strip_junk_query
from app.core.errors import InvalidFacebookUrl


@pytest.mark.parametrize(
    "raw, expected_key",
    [
        # username — các biến thể host/scheme/dấu gạch cuối
        ("https://www.facebook.com/example_user", "user:example_user"),
        ("https://facebook.com/example_user/", "user:example_user"),
        ("http://m.facebook.com/example_user", "user:example_user"),
        ("https://web.facebook.com/example_user", "user:example_user"),
        ("https://mbasic.facebook.com/example_user", "user:example_user"),
        ("facebook.com/example_user", "user:example_user"),  # thiếu scheme
        ("https://www.facebook.com/Example_User", "user:example_user"),  # hoa/thường
        # tham số rác khi chia sẻ từ app
        ("https://www.facebook.com/example_user?mibextid=LQQJ4d", "user:example_user"),
        ("https://www.facebook.com/example_user?rdid=abc&sfnsn=mo", "user:example_user"),
        # profile.php
        ("https://www.facebook.com/profile.php?id=100012345678901", "id:100012345678901"),
        (
            "https://www.facebook.com/profile.php?id=100012345678901&mibextid=x",
            "id:100012345678901",
        ),
        ("https://m.facebook.com/profile.php?id=100012345678901", "id:100012345678901"),
        # /people/
        (
            "https://www.facebook.com/people/Nguyen-Van-A/100012345678901/",
            "id:100012345678901",
        ),
        # ID số đứng một mình
        ("https://www.facebook.com/100012345678901", "id:100012345678901"),
        # fragment
        ("https://www.facebook.com/example_user#about", "user:example_user"),
    ],
)
def test_url_key_is_stable(raw: str, expected_key: str) -> None:
    assert normalize_facebook_url(raw).url_key == expected_key


def test_all_variants_of_one_person_collapse_to_one_key() -> None:
    variants = [
        "https://www.facebook.com/example_user",
        "https://m.facebook.com/example_user/",
        "https://facebook.com/example_user?mibextid=ZbWKwL",
        "EXAMPLE_USER".join(["https://www.facebook.com/", ""]),
    ]
    assert len({normalize_facebook_url(v).url_key for v in variants}) == 1


def test_canonical_and_mbasic_urls_are_derived() -> None:
    target = normalize_facebook_url("https://m.facebook.com/example_user?mibextid=x")
    assert target.canonical_url == "https://www.facebook.com/example_user"
    assert target.mbasic_url == "https://mbasic.facebook.com/example_user"
    assert target.kind == "username"


def test_profile_id_urls_are_derived() -> None:
    target = normalize_facebook_url("https://www.facebook.com/profile.php?id=100012345678901")
    assert target.canonical_url.endswith("profile.php?id=100012345678901")
    assert target.mbasic_url.startswith("https://mbasic.facebook.com/profile.php")
    assert target.kind == "profile_id"


# ---------------------------------------------------------------------------
# Từ chối
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expect_in_message",
    [
        ("", "Chưa nhập"),
        ("https://twitter.com/example_user", "domain Facebook"),
        ("https://facebook.com.evil.test/example_user", "domain Facebook"),
        ("https://www.facebook.com/", "không trỏ tới một trang cá nhân"),
        ("https://www.facebook.com/groups/12345", "không trỏ tới một trang cá nhân"),
        ("https://www.facebook.com/watch/?v=1", "không trỏ tới một trang cá nhân"),
        ("https://www.facebook.com/login.php", "không trỏ tới một trang cá nhân"),
        ("https://www.facebook.com/profile.php", "thiếu tham số `id`"),
        ("https://www.facebook.com/profile.php?id=abc", "thiếu tham số `id`"),
        ("https://www.facebook.com/people/Ten-Hien-Thi", "thiếu ID số"),
    ],
)
def test_rejected_urls_say_why(raw: str, expect_in_message: str) -> None:
    with pytest.raises(InvalidFacebookUrl) as exc:
        normalize_facebook_url(raw)
    assert expect_in_message in str(exc.value)


def test_lookalike_domain_is_rejected() -> None:
    """`facebook.com.evil.test` phải bị chặn — so khớp phải là host đầy đủ."""
    with pytest.raises(InvalidFacebookUrl):
        normalize_facebook_url("https://facebook.com.evil.test/abc")


def test_invalid_url_is_a_400_not_a_500() -> None:
    assert InvalidFacebookUrl.http_status == 400


# ---------------------------------------------------------------------------
# strip_junk_query
# ---------------------------------------------------------------------------
def test_strip_junk_keeps_meaningful_params() -> None:
    cleaned = strip_junk_query(
        "https://www.facebook.com/profile.php?id=123456789&mibextid=x&rdid=y"
    )
    assert "id=123456789" in cleaned
    assert "mibextid" not in cleaned
    assert "rdid" not in cleaned


def test_strip_junk_drops_fragment() -> None:
    assert "#" not in strip_junk_query("https://www.facebook.com/abc?ref=x#about")
