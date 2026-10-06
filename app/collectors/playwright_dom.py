"""Collector L3 — Playwright Chromium (plan.md §5.2).

Tắt mặc định (`PLAYWRIGHT_ENABLED=false`) vì nó kéo theo ~500MB thư viện GUI;
image Docker có Playwright là **stage riêng** (`--target playwright`).

Lớp này quan trọng hơn kế hoạch ban đầu tưởng: đo thật cho thấy `mbasic` là
login wall và L1 chỉ cho tên + ảnh đại diện (task.md I-14, I-22), nên bio/bài
viết thực tế phải trông vào đây hoặc vào người vận hành dán tay.

Giới hạn trung thực (plan.md §5.2): chỉ mở trang **công khai** như một trình
duyệt bình thường, 1 request/giây, không tài khoản ảo, không brute-force. Cookie
chỉ dùng khi **chính người dùng** cung cấp cookie của họ, và có cảnh báo rủi ro.

Import `playwright` **lười**: nó không nằm trong `requirements.txt` mặc định,
nên module này phải import được ở mọi máy; thiếu gói thì ghi `attempts` rồi đi
tiếp, không raise.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

from bs4 import BeautifulSoup

from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceImage
from app.collectors.text_guards import is_blocked_page, looks_like_a_person_name
from app.collectors.throttle import HostRateLimiter
from app.collectors.url import FacebookTarget
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

LAYER = "playwright"
SOURCE = "playwright_dom"

# User-agent **mobile** thật: bản mobile của Facebook nhẹ hơn và hay công khai
# nhiều hơn bản desktop cho khách chưa đăng nhập.
MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
VIEWPORT = {"width": 412, "height": 915}

NAV_TIMEOUT_MS = 30_000
SETTLE_TIMEOUT_MS = 8_000

_MIN_POST_LENGTH = 30
_MAX_POSTS = 3
_MAX_POST_LENGTH = 600

# Nhãn điều hướng của Facebook — không phải nội dung của khách.
_CHROME_MARKERS = (
    "xem thêm",
    "see more",
    "thích",
    "bình luận",
    "chia sẻ",
    "chính sách quyền riêng tư",
    "privacy policy",
    "điều khoản",
    "tải ứng dụng",
    "meta ©",
    "trang chủ",
    "bạn bè",
    "thông báo",
    "menu",
)


async def collect(
    target: FacebookTarget,
    bundle: EvidenceBundle,
    *,
    limiter: HostRateLimiter | None = None,
    cookie: str | None = None,
    screenshot_dir: str | None = None,
) -> EvidenceBundle:
    """Render trang bằng Chromium, chụp ảnh làm bằng chứng, bóc dữ kiện.

    Không raise: cờ tắt, thiếu gói, timeout, login wall — tất cả thành một dòng
    trong `attempts[]` để `error_note` nói đúng đã thử gì.
    """
    settings = get_settings()

    if not settings.playwright_enabled:
        bundle.add_attempt(
            CollectAttempt(
                layer=LAYER,
                ok=False,
                skipped=True,
                note="PLAYWRIGHT_ENABLED=false nên bỏ qua lớp này",
            )
        )
        return bundle

    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import async_playwright
    except ImportError:
        bundle.add_attempt(
            CollectAttempt(
                layer=LAYER,
                ok=False,
                skipped=True,
                note=(
                    "chưa cài playwright — dùng image Docker `--target playwright`, "
                    "hoặc `pip install -r requirements-playwright.txt && "
                    "playwright install chromium`"
                ),
            )
        )
        return bundle

    if limiter is not None:
        await limiter.wait(target.canonical_url)

    try:
        async with async_playwright() as driver:
            browser = await driver.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            try:
                context = await browser.new_context(
                    user_agent=MOBILE_USER_AGENT,
                    viewport=VIEWPORT,
                    locale="vi-VN",
                )
                if cookie:
                    await context.add_cookies(_cookies_from_header(cookie))

                page = await context.new_page()
                response = await page.goto(
                    target.canonical_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                )
                status = response.status if response is not None else None

                # `networkidle` trên Facebook gần như không bao giờ tới (polling
                # liên tục), nên chờ có hạn rồi đi tiếp với DOM đang có.
                try:
                    await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
                except PlaywrightError:
                    log.info("Trang không bao giờ im lặng, dùng DOM hiện có")

                await _dismiss_login_modal(page)
                await _scroll_to_load_photos(page)

                photos = await _collect_public_photos(page)
                html = await page.content()
                screenshot_path = await _save_screenshot(
                    page, target, screenshot_dir or settings.screenshot_dir
                )
            finally:
                await browser.close()
    except Exception as exc:  # Playwright ném nhiều loại lỗi; không được làm sập pipeline
        bundle.add_attempt(
            CollectAttempt(layer=LAYER, ok=False, note=f"lỗi Playwright: {type(exc).__name__}")
        )
        return bundle

    # Ảnh công khai được nạp vào bundle **trước** khi kiểm tra trang chắn: đo
    # thật cho thấy Facebook khoá text nhưng **không** khoá ảnh (task.md I-30),
    # và đề bài §1 nêu đích danh "hình ảnh công khai gần nhất" là nguồn hợp lệ.
    for url in photos:
        bundle.add_image(EvidenceImage(role="public_photo", url=url))

    return parse_into(html, bundle, http_status=status, screenshot_path=screenshot_path)


def parse_into(
    html: str,
    bundle: EvidenceBundle,
    *,
    http_status: int | None = 200,
    screenshot_path: str | None = None,
) -> EvidenceBundle:
    """Bóc dữ kiện từ DOM đã render. Tách ra để test không cần Chromium."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    # Ghi ngay, kể cả khi gặp login wall: ảnh chụp trang đăng nhập **cũng** là
    # bằng chứng cho câu "Facebook không cho đọc trang này".
    if screenshot_path:
        bundle.screenshot_path = screenshot_path

    if is_blocked_page(text):
        # Text bị khoá **không** có nghĩa là không thu được gì: Facebook vẫn
        # phục vụ lưới ảnh công khai (I-30). Nói đúng cả hai nửa sự thật.
        photos = [image for image in bundle.images if image.role == "public_photo"]
        bundle.add_attempt(
            CollectAttempt(
                layer=LAYER,
                ok=bool(photos),
                http_status=http_status,
                note=(
                    f"Facebook khoá phần chữ dù đã render JS, nhưng lấy được "
                    f"{len(photos)} ảnh công khai"
                    if photos
                    else "Facebook trả trang đăng nhập dù đã render JS"
                ),
            )
        )
        bundle.mark_blocked(
            "Facebook yêu cầu đăng nhập để xem phần chữ (tiểu sử, bài viết). "
            + (
                "Chỉ đọc được ảnh công khai; cần người vận hành dán nội dung tay "
                "nếu muốn thêm dữ kiện chữ."
                if photos
                else "Cần người vận hành dán nội dung tay."
            )
        )
        return bundle

    found_anything = False

    if name := _extract_name(soup):
        found_anything |= bundle.add_field(
            "customer_name",
            name,
            source=SOURCE,
            evidence=f"tiêu đề trang sau khi render JS: {name}",
            # Thấp hơn og:title (0.95): tiêu đề DOM dễ lẫn hậu tố điều hướng.
            confidence=0.9,
        )

    if bio := _extract_bio(soup):
        found_anything |= bundle.add_field(
            "bio",
            bio,
            source=SOURCE,
            evidence=f"mục giới thiệu trên DOM đã render: {bio}",
            confidence=0.85,
        )

    posts = _extract_posts(soup)
    if posts:
        joined = "\n---\n".join(posts)
        found_anything |= bundle.add_field(
            "post_text",
            joined,
            source=SOURCE,
            evidence=f"{len(posts)} đoạn bài viết công khai (DOM đã render):\n{joined}",
            confidence=0.8,
        )

    if avatar := _extract_avatar(soup):
        bundle.add_image(EvidenceImage(role="avatar", url=avatar))
        found_anything = True

    bundle.add_attempt(
        CollectAttempt(
            layer=LAYER,
            ok=found_anything,
            http_status=http_status,
            note=(
                f"ảnh chụp: {screenshot_path}"
                if screenshot_path and found_anything
                else ("" if found_anything else "không bóc được dữ kiện nào từ DOM")
            ),
        )
    )
    return bundle


# --------------------------------------------------------------------------
# Ảnh công khai (task X.1)
# --------------------------------------------------------------------------
# Lưới ảnh công khai **không** bị khoá dù text bị khoá (I-30). Đề bài §1 nêu
# đích danh "ảnh đại diện (Avatar) **hoặc hình ảnh công khai gần nhất**".

#: Ảnh nhỏ hơn mức này là icon giao diện hoặc avatar của mục "Những người khác
#: có tên tương tự" — tức **ảnh người khác**. Đo thật: ảnh bài đăng 340×340,
#: avatar của khách 288×288, avatar người-tên-tương-tự 117×120.
MIN_PHOTO_EDGE_PX = 200
MAX_PUBLIC_PHOTOS = 3
PHOTO_SCROLL_STEPS = 3

#: Nút đóng do **chính Facebook** render trên hộp thoại mời đăng nhập. Bấm một
#: nút đóng mà trang tự đưa ra là thao tác duyệt web bình thường, không phải
#: vượt rào xác thực — nội dung phía sau vẫn đúng phần Facebook đã công khai.
_MODAL_CLOSE_SELECTORS = (
    '[aria-label="Đóng"]',
    '[aria-label="Close"]',
    'div[role="dialog"] [aria-label="Đóng"]',
    'div[role="dialog"] [aria-label="Close"]',
)

#: Phần "Những người khác có tên tương tự" chứa avatar của **người khác**. Thu
#: chúng vào là vừa sai luật L1 (mô tả người lạ như thể là khách) vừa sai về
#: riêng tư của những người không liên quan.
_OTHER_PEOPLE_HEADINGS = (
    "tên tương tự",
    "similar names",
    "người bạn có thể biết",
    "people you may know",
)

#: Lấy ảnh nội dung, loại icon giao diện và ảnh của người khác.
#:
#: Chạy trong trình duyệt nên viết bằng JS. Ba bộ lọc:
#: 1. `scontent` — ảnh nội dung thật, khác `static.xx.fbcdn.net` (icon/sprite).
#: 2. Kích thước **thật đã tải** (`naturalWidth`) ≥ ngưỡng.
#: 3. Không nằm trong khối "tên tương tự" / "người bạn có thể biết".
_COLLECT_PHOTOS_JS = """
([minEdge, headings]) => {
  const inOtherPeopleBlock = (el) => {
    for (let node = el; node && node !== document.body; node = node.parentElement) {
      const text = (node.innerText || '').toLowerCase();
      if (text.length > 0 && text.length < 400) {
        if (headings.some(h => text.includes(h))) return true;
      }
    }
    return false;
  };
  const seen = new Set();
  const out = [];
  for (const img of document.querySelectorAll('img')) {
    const src = img.src || '';
    if (!src.includes('scontent')) continue;
    if (Math.min(img.naturalWidth, img.naturalHeight) < minEdge) continue;
    if (inOtherPeopleBlock(img)) continue;
    if (seen.has(src)) continue;
    seen.add(src);
    out.push(src);
  }
  return out;
}
"""


async def _dismiss_login_modal(page: Any) -> bool:
    """Đóng hộp thoại mời đăng nhập nếu có. Trả `True` nếu đã đóng."""
    for selector in _MODAL_CLOSE_SELECTORS:
        try:
            element = await page.query_selector(selector)
            if element is None:
                continue
            await element.click(timeout=3_000)
            await page.wait_for_timeout(1_500)
            log.info("Đã đóng hộp thoại mời đăng nhập")
            return True
        except Exception as exc:
            # Selector không khớp/không bấm được là chuyện bình thường — Facebook
            # đổi `aria-label` theo ngôn ngữ và theo phiên bản. Thử cái kế tiếp.
            log.debug("Selector %s không bấm được: %s", selector, type(exc).__name__)
            continue
    return False


async def _scroll_to_load_photos(page: Any) -> None:
    """Cuộn vài nhịp để lưới ảnh lazy-load kịp nạp."""
    for _ in range(PHOTO_SCROLL_STEPS):
        try:
            await page.mouse.wheel(0, 1_200)
            await page.wait_for_timeout(1_000)
        except Exception:  # pragma: no cover — phụ thuộc trình duyệt
            return


async def _collect_public_photos(page: Any) -> list[str]:
    """URL ảnh công khai, đã loại icon và ảnh của người khác."""
    try:
        urls = await page.evaluate(
            _COLLECT_PHOTOS_JS, [MIN_PHOTO_EDGE_PX, list(_OTHER_PEOPLE_HEADINGS)]
        )
    except Exception as exc:  # pragma: no cover — phụ thuộc trình duyệt
        log.warning("Không đọc được lưới ảnh: %s", type(exc).__name__)
        return []

    photos = [url for url in urls if isinstance(url, str) and url][:MAX_PUBLIC_PHOTOS]
    if photos:
        log.info("Thu được %d ảnh công khai", len(photos))
    return photos


async def _save_screenshot(page: Any, target: FacebookTarget, directory: str) -> str | None:
    """Chụp toàn trang làm **bằng chứng** cho `profile_evidence.screenshot_path`.

    Tên file theo `url_key` đã chuẩn hoá, không theo URL thô — URL thô chứa ký
    tự không hợp lệ cho tên file.
    """
    try:
        folder = pathlib.Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target.url_key)
        path = folder / f"{safe}.png"
        await page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception as exc:  # ảnh chụp là điều tốt-nếu-có, không được làm sập lượt thu thập
        log.warning("Không chụp được ảnh trang: %s", type(exc).__name__)
        return None


def _cookies_from_header(header: str) -> list[dict[str, str]]:
    """`"c_user=1; xs=2"` → danh sách cookie của Playwright."""
    cookies: list[dict[str, str]] = []
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name and value:
            cookies.append({"name": name, "value": value, "domain": ".facebook.com", "path": "/"})
    return cookies


def _extract_name(soup: BeautifulSoup) -> str | None:
    if (h1 := soup.find("h1")) and (value := h1.get_text(" ", strip=True)):
        if looks_like_a_person_name(value):
            return value
    if soup.title and (raw := (soup.title.string or "")):
        # `Unclee Vander (@yazawanico24111) • Facebook, Connect with friends`
        value = re.sub(r"\s*\(@[^)]*\)", "", raw)
        value = re.sub(r"\s*[|•·]\s*Facebook.*$", "", value).strip()
        if looks_like_a_person_name(value):
            return value
    return None


def _extract_bio(soup: BeautifulSoup) -> str | None:
    """Đoạn ngay sau nhãn "Giới thiệu"/"Intro" trên DOM đã render."""
    labels = ("giới thiệu", "tiểu sử", "intro", "about")
    for element in soup.find_all(["h2", "h3", "span", "div"]):
        label = element.get_text(" ", strip=True).lower()
        if label and len(label) <= 30 and any(label.startswith(key) for key in labels):
            for sibling in element.find_all_next(string=False, limit=8):
                candidate = sibling.get_text(" ", strip=True)
                if 20 <= len(candidate) <= 500 and candidate.lower() != label:
                    return candidate
    return None


def _extract_posts(soup: BeautifulSoup) -> list[str]:
    """Lấy tối đa 3 đoạn đủ dài, bỏ nhãn điều hướng và đoạn trùng."""
    seen: set[str] = set()
    posts: list[str] = []

    for element in soup.find_all(["div", "p", "span"]):
        if element.find(["div", "p", "span"]) is not None:
            continue  # chỉ lấy node lá, tránh lấy cả cây rồi trùng
        value = element.get_text(" ", strip=True)
        if len(value) < _MIN_POST_LENGTH or value in seen:
            continue
        lowered = value.lower()
        if any(marker in lowered for marker in _CHROME_MARKERS):
            continue
        seen.add(value)
        posts.append(value[:_MAX_POST_LENGTH])
        if len(posts) >= _MAX_POSTS:
            break
    return posts


def _extract_avatar(soup: BeautifulSoup) -> str | None:
    """Ưu tiên `og:image`; nếu không có thì tìm `<img>` trỏ về CDN của Facebook."""
    tag = soup.find("meta", property="og:image")
    if tag and isinstance(tag.get("content"), str) and tag["content"].strip():
        return tag["content"].strip()

    for image in soup.find_all("img"):
        src = image.get("src")
        if isinstance(src, str) and "fbcdn.net" in src:
            return src
    return None
