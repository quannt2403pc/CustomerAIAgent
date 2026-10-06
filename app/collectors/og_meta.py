"""Collector L1 — thẻ Open Graph (plan.md §5.2).

Nhanh nhất, không cần đăng nhập: Facebook phục vụ `og:title` / `og:image` cho
trang công khai để link preview hoạt động.

**Ba điều đo thật ngày 2026-10-06 định hình module này** (task.md I-12…I-14):

1. Thiếu header `sec-ch-ua` / `Sec-Fetch-*` → Facebook trả **HTTP 400 "Sorry,
   something went wrong"** cho *mọi* URL, kể cả trang chủ. Thêm đủ header thì
   200. Vì vậy `build_headers()` gửi trọn bộ header mà chính User-Agent đã khai
   báo sẽ gửi — không giả mạo ai, chỉ nhất quán với chính mình.
2. `Accept-Encoding: br` cần gói `brotli`, thiếu nó thì body là nhị phân rối và
   parser đọc ra rỗng — một lỗi *im lặng*.
3. `og:description` của trang cá nhân Facebook là **khuôn mẫu rỗng nghĩa**
   ("X đang ở trên Facebook. Tham gia Facebook để kết nối với X…"), **không**
   phải bio. Nhận nó làm evidence là nạp chữ vô nghĩa cho LLM và — tệ hơn — cho
   `GroundingValidator` coi từ trong khuôn mẫu đó là "có bằng chứng". Phải loại.

**Không bao giờ raise khi bị chặn.** Login wall là sự thật về trang đó, không
phải lỗi hệ thống — nó đi vào `attempts[]` + `blocked_reason` để `error_note`
nói đúng "đọc được tới đâu" (luật L1).
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceImage
from app.collectors.text_guards import is_blocked_page, looks_like_a_person_name
from app.collectors.url import FacebookTarget
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

LAYER = "og_meta"
SOURCE = "og_meta"

# User-agent thật của một trình duyệt. Không giả mạo crawler của ai khác, không
# dùng tài khoản ảo — chỉ đọc đúng thứ Facebook trả cho khách chưa đăng nhập
# (plan.md §5.2 "giới hạn trung thực").
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


# Khuôn mẫu `og:description` mà Facebook gắn cho MỌI trang cá nhân.
# Cần ≥2 dấu hiệu khớp để không loại oan một bio thật có nhắc chữ "Facebook".
_GENERIC_DESCRIPTION_MARKERS = (
    "đang ở trên facebook",
    "tham gia facebook để kết nối",
    "quyền chia sẻ và mở rộng",
    "is on facebook",
    "join facebook to connect",
    "gives people the power to share",
    "see posts, photos and more",
    "xem bài viết, ảnh và nhiều nội dung khác",
)


def build_headers() -> dict[str, str]:
    """Trọn bộ header mà Chrome 131 trên Windows thật sự gửi.

    Thiếu `sec-ch-ua` / `Sec-Fetch-*` là Facebook trả 400 ngay (I-12). Đây
    không phải mẹo lách: một User-Agent khai là Chrome mà không gửi các header
    Chrome vẫn gửi thì chính nó mới là lời khai không nhất quán.
    """
    return {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


async def collect(
    target: FacebookTarget,
    bundle: EvidenceBundle,
    *,
    client: httpx.AsyncClient | None = None,
) -> EvidenceBundle:
    """Đọc thẻ OG của `target.canonical_url`, bổ sung vào `bundle`."""
    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.collector_timeout_seconds),
        follow_redirects=True,
    )
    try:
        try:
            response = await client.get(target.canonical_url, headers=build_headers())
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, note=f"lỗi mạng: {type(exc).__name__}")
            )
            return bundle

        if response.status_code >= 400:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, http_status=response.status_code)
            )
            bundle.mark_blocked(_explain_status(response.status_code))
            return bundle

        return parse_into(response.text, bundle, http_status=response.status_code)
    finally:
        if owns_client:
            await client.aclose()


def parse_into(
    html: str, bundle: EvidenceBundle, *, http_status: int | None = 200
) -> EvidenceBundle:
    """Bóc thẻ OG từ HTML. Tách khỏi `collect()` để test không cần mạng."""
    if is_blocked_page(html):
        bundle.add_attempt(
            CollectAttempt(
                layer=LAYER,
                ok=False,
                http_status=http_status,
                note="Facebook trả trang đăng nhập",
            )
        )
        bundle.mark_blocked(
            "Facebook yêu cầu đăng nhập để xem trang này, nên chỉ đọc được "
            "metadata công khai (nếu có)."
        )
        return bundle

    soup = BeautifulSoup(html, "lxml")
    found_anything = False

    if title := _meta(soup, "og:title"):
        if looks_like_a_person_name(_clean_name(title)):
            found_anything |= bundle.add_field(
                "customer_name",
                _clean_name(title),
                source=SOURCE,
                evidence=f'<meta property="og:title" content="{title}">',
                confidence=0.95,
            )

    description = _meta(soup, "og:description")
    if description and not is_generic_description(description):
        found_anything |= bundle.add_field(
            "page_description",
            description,
            source=SOURCE,
            evidence=f'<meta property="og:description" content="{description}">',
            confidence=0.8,
        )
    elif description:
        # Ghi lại để người đọc log hiểu vì sao không có `page_description`.
        log.info("Bỏ qua og:description vì là khuôn mẫu chung của Facebook")

    if image_url := _meta(soup, "og:image"):
        bundle.add_image(EvidenceImage(role="avatar", url=image_url))
        found_anything = True

    bundle.add_attempt(
        CollectAttempt(
            layer=LAYER,
            ok=found_anything,
            http_status=http_status,
            note="" if found_anything else "không có thẻ og nào dùng được",
        )
    )
    if not found_anything:
        bundle.mark_blocked("Trang không công khai thẻ Open Graph nào đọc được.")
    return bundle


def is_generic_description(description: str) -> bool:
    """`og:description` có phải khuôn mẫu rỗng nghĩa của Facebook?

    Yêu cầu khớp **≥2** dấu hiệu: một bio thật hoàn toàn có thể nhắc chữ
    "Facebook", và loại oan bio thật cũng là làm mất dữ kiện có thật.
    """
    lowered = description.lower()
    hits = sum(1 for marker in _GENERIC_DESCRIPTION_MARKERS if marker in lowered)
    return hits >= 2


def _explain_status(status: int) -> str:
    """Câu tiếng Việt cho `error_note` — nói đúng việc cần làm."""
    if status == 404:
        return "Trang không tồn tại hoặc đã bị xoá (HTTP 404)."
    if status == 429:
        return "Facebook đang giới hạn tần suất truy cập (HTTP 429)."
    if status == 400:
        return (
            "Facebook từ chối yêu cầu (HTTP 400) — thường là chặn client không "
            "phải trình duyệt thật. Hãy thử lớp Playwright hoặc dán nội dung tay."
        )
    if status in (401, 403):
        return f"Facebook không cho đọc trang này mà chưa đăng nhập (HTTP {status})."
    return f"Facebook trả HTTP {status}."


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    if tag is None:
        return None
    content = tag.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _clean_name(title: str) -> str:
    """`og:title` hay có hậu tố `| Facebook` — bỏ đi, giữ nguyên phần tên."""
    name = title.strip()
    for suffix in (" | Facebook", " - Facebook", " | Trang chủ", " • Facebook"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name
