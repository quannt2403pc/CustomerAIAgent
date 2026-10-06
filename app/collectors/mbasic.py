"""Collector L2 — `mbasic.facebook.com` (plan.md §5.2).

Bản HTML tối giản của Facebook: không JavaScript, nhẹ, dễ parse. Khi đọc được
thì nó cho nhiều hơn L1 — tiểu sử, vài đoạn bài viết công khai.

**Giới hạn đo thật 2026-10-06 (task.md I-14):** với khách chưa đăng nhập,
`mbasic` trả **HTTP 200 kèm trang đăng nhập**, không phải trang cá nhân. Nghĩa là
lớp này chỉ thực sự có tác dụng khi người dùng tự cung cấp cookie của **chính
họ** (tuỳ chọn, D1.13). Không đọc được thì nói thật — không bịa (luật L1).
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup, Tag

from app.collectors.evidence import CollectAttempt, EvidenceBundle
from app.collectors.og_meta import build_headers
from app.collectors.text_guards import is_blocked_page, looks_like_a_person_name
from app.collectors.throttle import HostRateLimiter
from app.collectors.url import FacebookTarget
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

LAYER = "mbasic"
SOURCE = "mbasic_html"


# Nhãn mục tiểu sử trên mbasic (cả hai ngôn ngữ).
_BIO_LABELS = ("giới thiệu", "tiểu sử", "intro", "bio", "about")

_MIN_POST_LENGTH = 25
_MAX_POSTS = 3
_MAX_POST_LENGTH = 600


async def collect(
    target: FacebookTarget,
    bundle: EvidenceBundle,
    *,
    client: httpx.AsyncClient | None = None,
    limiter: HostRateLimiter | None = None,
    cookie: str | None = None,
) -> EvidenceBundle:
    """Đọc `target.mbasic_url`, bổ sung vào `bundle`. Không raise khi bị chặn."""
    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.collector_timeout_seconds),
        follow_redirects=True,
    )
    try:
        if limiter is not None:
            await limiter.wait(target.mbasic_url)

        headers = build_headers()
        if cookie:
            # Cookie của **chính người dùng**, do họ tự cung cấp và đã mã hoá
            # at-rest. Không bao giờ log giá trị này (bộ lọc ở core/logging).
            headers["Cookie"] = cookie

        try:
            response = await client.get(target.mbasic_url, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, note=f"lỗi mạng: {type(exc).__name__}")
            )
            return bundle

        if response.status_code >= 400:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, http_status=response.status_code)
            )
            return bundle

        return parse_into(response.text, bundle, http_status=response.status_code)
    finally:
        if owns_client:
            await client.aclose()


def parse_into(
    html: str, bundle: EvidenceBundle, *, http_status: int | None = 200
) -> EvidenceBundle:
    """Bóc tên/bio/bài viết từ HTML mbasic. Tách ra để test không cần mạng."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    if is_blocked_page(text):
        bundle.add_attempt(
            CollectAttempt(
                layer=LAYER,
                ok=False,
                http_status=http_status,
                note="mbasic trả trang đăng nhập (HTTP 200)",
            )
        )
        bundle.mark_blocked(
            "Bản mbasic cũng yêu cầu đăng nhập. Cần dán nội dung tay hoặc bật "
            "lớp Playwright để đọc thêm."
        )
        return bundle

    found_anything = False

    if name := _extract_name(soup):
        found_anything |= bundle.add_field(
            "customer_name",
            name,
            source=SOURCE,
            evidence=f"<h1>/<title> trên mbasic: {name}",
            # Thấp hơn og:title (0.95): heading mbasic dễ lẫn tên mục, tên trang.
            confidence=0.85,
        )

    if bio := _extract_bio(soup):
        found_anything |= bundle.add_field(
            "bio",
            bio,
            source=SOURCE,
            evidence=f"mục giới thiệu trên mbasic: {bio}",
            confidence=0.8,
        )

    posts = _extract_posts(soup)
    if posts:
        joined = "\n---\n".join(posts)
        found_anything |= bundle.add_field(
            "post_text",
            joined,
            source=SOURCE,
            evidence=f"{len(posts)} đoạn bài viết công khai trên mbasic:\n{joined}",
            confidence=0.75,
        )

    bundle.add_attempt(
        CollectAttempt(
            layer=LAYER,
            ok=found_anything,
            http_status=http_status,
            note="" if found_anything else "không bóc được dữ kiện nào từ mbasic",
        )
    )
    return bundle


def _extract_name(soup: BeautifulSoup) -> str | None:
    if (h1 := soup.find("h1")) and (value := h1.get_text(" ", strip=True)):
        if looks_like_a_person_name(value):
            return value
    if soup.title and (value := (soup.title.string or "").strip()):
        value = re.sub(r"\s*[|•\-]\s*Facebook.*$", "", value).strip()
        if looks_like_a_person_name(value):
            return value
    return None


def _extract_bio(soup: BeautifulSoup) -> str | None:
    """Tìm đoạn văn ngay sau một nhãn kiểu "Giới thiệu" / "Intro"."""
    for element in soup.find_all(["h2", "h3", "span", "div"]):
        if not isinstance(element, Tag):
            continue
        label = element.get_text(" ", strip=True).lower()
        if label and any(label.startswith(key) for key in _BIO_LABELS) and len(label) <= 30:
            for sibling in element.find_all_next(string=False, limit=6):
                candidate = sibling.get_text(" ", strip=True)
                if _MIN_POST_LENGTH <= len(candidate) <= 500 and candidate.lower() != label:
                    return candidate
    return None


def _extract_posts(soup: BeautifulSoup) -> list[str]:
    """Lấy tối đa 3 đoạn bài viết công khai, đủ dài để có nội dung thật.

    Lọc trùng và lọc đoạn ngắn: nút bấm, nhãn điều hướng trên mbasic cũng là
    `<p>`/`<div>`, nhận chúng vào sẽ thành "dữ kiện" rỗng nghĩa.
    """
    seen: set[str] = set()
    posts: list[str] = []

    for element in soup.find_all(["p", "div"]):
        if not isinstance(element, Tag):
            continue
        # Chỉ lấy node lá chứa văn bản, tránh lấy cả cây rồi trùng lặp.
        if element.find(["p", "div"]) is not None:
            continue
        value = element.get_text(" ", strip=True)
        if len(value) < _MIN_POST_LENGTH or value in seen:
            continue
        if _is_navigation_chrome(value):
            continue
        seen.add(value)
        posts.append(value[:_MAX_POST_LENGTH])
        if len(posts) >= _MAX_POSTS:
            break
    return posts


def _is_navigation_chrome(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "xem thêm",
        "see more",
        "thích · bình luận",
        "like · comment",
        "chính sách quyền riêng tư",
        "privacy policy",
        "điều khoản",
        "tải ứng dụng",
        "meta ©",
        "meta @",
    )
    return any(marker in lowered for marker in markers)
