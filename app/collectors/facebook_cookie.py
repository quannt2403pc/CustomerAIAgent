"""Cookie Facebook của **chính người vận hành** (task X.2, plan.md §5.2).

Vì sao cần: đo đối chứng trên cùng một trang, cùng một thời điểm (task.md I-33)
cho thấy một bài viết **Công khai** vẫn bị che với khách chưa đăng nhập. Cùng
bài đó, một tài khoản lạ **đã đăng nhập** thì đọc được đủ nội dung. Không có
cookie thì pipeline chỉ lấy được tên + ảnh.

Ba ràng buộc không thương lượng:

1. **Cookie của chính họ.** Không tài khoản ảo, không mượn tài khoản người khác
   (luật L3). Module này không tạo tài khoản và không đăng nhập hộ ai.
2. **Mã hoá at-rest.** Lưu qua `app/services/credentials.py` (Fernet). Không
   bao giờ ghi plaintext xuống đĩa hay log — bộ lọc ở `core/logging` đã che
   `c_user`, `xs`, `fr`, `datr`, `sb`, nhưng đừng dựa vào đó làm lớp duy nhất.
3. **Cảnh báo rủi ro phải hiển thị trước khi lưu.** Facebook có thể gắn cờ hoặc
   khoá tài khoản bị dùng để truy cập tự động. Người vận hành phải biết điều đó
   trước khi quyết định, không phải sau khi mất tài khoản.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import CollectorError
from app.core.logging import get_logger

log = get_logger(__name__)

#: Phải hiện **trước** khi người dùng dán cookie, không phải sau.
RISK_WARNING = (
    "Cookie này cho hệ thống đọc Facebook **dưới danh nghĩa tài khoản của bạn**. "
    "Facebook có thể gắn cờ hoặc khoá tài khoản bị dùng để truy cập tự động — "
    "hãy cân nhắc dùng một tài khoản phụ của chính bạn. "
    "Chỉ dán cookie của **chính bạn**; dùng tài khoản người khác là sai cả về "
    "pháp lý lẫn điều khoản Facebook. Cookie được mã hoá trước khi lưu và không "
    "bao giờ xuất hiện trong log hay response."
)

#: `c_user` là ID tài khoản, `xs` là token phiên. Thiếu một trong hai thì cookie
#: không đăng nhập được — báo ngay còn hơn để pipeline chạy rồi thất bại im lặng.
REQUIRED_NAMES = ("c_user", "xs")

#: Cookie khác của Facebook, có thì tốt nhưng không bắt buộc.
OPTIONAL_NAMES = ("datr", "sb", "fr", "wd", "dpr")

_PAIR = re.compile(r"(?P<name>[A-Za-z0-9_\-]+)\s*=\s*(?P<value>[^;]+)")


@dataclass(frozen=True)
class CookieInfo:
    """Mô tả an toàn để hiện trên UI — **không** chứa giá trị cookie."""

    account_id: str
    names: tuple[str, ...]

    @property
    def masked_account(self) -> str:
        """`100012345678901` → `••••8901`. Đủ để nhận ra, không đủ để dùng lại."""
        return f"••••{self.account_id[-4:]}" if len(self.account_id) > 4 else "••••"


def parse(raw: str) -> dict[str, str]:
    """Bóc cặp `tên=giá trị` từ header `Cookie` người dùng dán.

    Nhận cả chuỗi copy từ DevTools (`c_user=1; xs=2; datr=3`) lẫn chuỗi có
    xuống dòng — người ta hay copy kèm ngắt dòng mà không để ý.
    """
    text = " ".join((raw or "").split())
    return {match.group("name"): match.group("value").strip() for match in _PAIR.finditer(text)}


def validate(raw: str) -> CookieInfo:
    """Kiểm hình dạng cookie. Thiếu thứ bắt buộc → `CollectorError` nói rõ thiếu gì.

    Chỉ kiểm **hình dạng**, không kiểm còn hiệu lực hay không — việc đó cần gọi
    mạng, nằm ở `check_alive()`.
    """
    pairs = parse(raw)
    if not pairs:
        raise CollectorError(
            "Không đọc được cookie nào. Hãy sao chép **toàn bộ** giá trị của header "
            "`Cookie` trong tab Network của DevTools, dạng `c_user=…; xs=…; datr=…`."
        )

    missing = [name for name in REQUIRED_NAMES if not pairs.get(name)]
    if missing:
        raise CollectorError(
            f"Cookie thiếu {', '.join(missing)} nên không đăng nhập được. "
            "`c_user` là ID tài khoản, `xs` là token phiên — cần cả hai. "
            "Hãy chắc bạn copy từ một tab Facebook **đang đăng nhập**."
        )

    account_id = pairs["c_user"]
    if not account_id.isdigit():
        raise CollectorError(
            "`c_user` phải là dãy số (ID tài khoản Facebook), nhưng giá trị nhận "
            f"được dài {len(account_id)} ký tự và không phải số."
        )

    # Log *tên* cookie, không log giá trị.
    log.info("Đã nhận cookie Facebook gồm: %s", ", ".join(sorted(pairs)))
    return CookieInfo(account_id=account_id, names=tuple(sorted(pairs)))


def to_header(raw: str) -> str:
    """Chuẩn hoá về dạng header `Cookie` gọn, chỉ giữ cookie Facebook biết đến.

    Lọc bớt cookie lạ: chúng không giúp gì mà lại kéo theo dữ liệu của site khác
    nếu người dùng lỡ copy cookie của cả trình duyệt.
    """
    pairs = parse(raw)
    keep = [*REQUIRED_NAMES, *OPTIONAL_NAMES]
    kept = {name: pairs[name] for name in keep if name in pairs}
    return "; ".join(f"{name}={value}" for name, value in kept.items())


async def check_alive(raw: str, *, client=None) -> bool:
    """Cookie còn đăng nhập được không?

    Gọi `mbasic.facebook.com` — nhẹ nhất. Thấy trang đăng nhập nghĩa là cookie
    đã hết hạn hoặc bị Facebook thu hồi.
    """
    import httpx

    from app.collectors.og_meta import build_headers
    from app.collectors.text_guards import is_blocked_page

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True)
    try:
        headers = {**build_headers(), "Cookie": to_header(raw)}
        try:
            response = await client.get("https://mbasic.facebook.com/", headers=headers)
        except Exception as exc:
            log.warning("Không kiểm tra được cookie: %s", type(exc).__name__)
            return False
        if response.status_code >= 400:
            return False
        return not is_blocked_page(response.text)
    finally:
        if owns_client:
            await client.aclose()
