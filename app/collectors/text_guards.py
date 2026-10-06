"""Bộ chắn văn bản dùng chung cho mọi lớp collector.

Tồn tại vì một lỗi thật (task.md I-29): ba lớp L1/L2/L3 mỗi lớp giữ một bản
`_LOGIN_WALL_MARKERS` riêng, nên khi Facebook trả một trang chắn kiểu mới
("Đăng nhập để xem bài viết của tài khoản này", "Trình duyệt này không được hỗ
trợ") thì chỉ một lớp bắt được, hai lớp còn lại đọc chữ của **giao diện
Facebook** và tưởng đó là dữ liệu của khách.

Hậu quả đo được: L3 đặt `customer_name = "Trình duyệt này không được hỗ trợ"`
với confidence 0.9 — một dữ kiện **bịa**, đúng thứ luật L1 tồn tại để chặn.
"""

from __future__ import annotations

# Mọi dấu hiệu Facebook đang chắn thay vì cho xem trang cá nhân.
# Thêm marker mới thì thêm **ở đây**, cả ba lớp cùng được.
LOGIN_WALL_MARKERS: tuple[str, ...] = (
    # Trang đăng nhập
    "đăng nhập vào facebook",
    "log in to facebook",
    "log into facebook",
    "you must log in to continue",
    "bạn phải đăng nhập để tiếp tục",
    "tạo tài khoản mới",
    "create new account",
    # Chắn mềm: cho xem khung nhưng che nội dung (đo thật trên L3)
    "đăng nhập để xem",
    "log in to see",
    "đăng nhập hoặc tạo tài khoản",
    "những người khác có tên tương tự",
    "people with similar names",
    # Chặn theo trình duyệt — Chromium headless hay bị trang này
    "trình duyệt này không được hỗ trợ",
    "browser is not supported",
    "this browser is not supported",
    "unsupported browser",
    # Chặn theo tài khoản / checkpoint
    "login_form",
    "checkpoint/block",
    "security check required",
)

# Tiêu đề/heading chung của Facebook — không bao giờ là tên một người.
GENERIC_TITLES: frozenset[str] = frozenset(
    {
        "facebook",
        "log in to facebook",
        "log into facebook",
        "đăng nhập facebook",
        "đăng nhập vào facebook",
        "security check required",
        "error",
        "lỗi",
        "trang chủ",
        "home",
        "mobile",
        "trình duyệt này không được hỗ trợ",
        "browser is not supported",
    }
)

# Từ chức năng: xuất hiện trong **câu**, không xuất hiện trong **tên người**.
#
# Đây là chốt chặn thứ hai sau `GENERIC_TITLES`: danh sách tiêu đề cụ thể luôn
# chạy sau Facebook một bước, còn "một chuỗi chứa chữ `không` thì không phải tên
# người Việt" thì đúng với cả những trang chắn chưa từng thấy.
_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "không",
        "được",
        "này",
        "đó",
        "để",
        "xem",
        "của",
        "và",
        "là",
        "có",
        "với",
        "cho",
        "bạn",
        "tôi",
        "đã",
        "sẽ",
        "đang",
        "nếu",
        "hoặc",
        "nhưng",
        "the",
        "this",
        "that",
        "your",
        "you",
        "not",
        "supported",
        "please",
        "login",
        "log",
        "sign",
        "account",
        "page",
        "error",
    }
)

#: Cụm từ giao diện — khớp theo **chuỗi con**, không theo từ đơn.
#:
#: Cần riêng danh sách này vì `_FUNCTION_WORDS` so theo từng từ: "Vui lòng thử
#: lại sau" tách ra thành `vui`/`lòng`/`thử`/`lại`/`sau`, không từ nào là từ
#: chức năng, nên nó lọt qua và thành "tên khách".
_UI_PHRASES: tuple[str, ...] = (
    "vui lòng",
    "thử lại",
    "tải lại",
    "quay lại",
    "không được",
    "đăng nhập",
    "đăng ký",
    "try again",
    "please",
    "go back",
)

MAX_NAME_CHARS = 60
MAX_NAME_WORDS = 8


def is_blocked_page(text: str) -> bool:
    """Trang này là trang chắn của Facebook, không phải trang cá nhân?"""
    lowered = text.lower()
    return any(marker in lowered for marker in LOGIN_WALL_MARKERS)


def looks_like_a_person_name(value: str) -> bool:
    """Chuỗi này có thể là tên hiển thị của một người?

    Thà **từ chối** một tên thật lạ còn hơn **nhận** một câu giao diện làm tên:
    thiếu tên thì status hạ xuống `PARTIAL_OR_PRIVATE` và nói thật; nhận chữ của
    Facebook làm tên thì mọi tin nhắn sau đó gọi khách bằng một cái tên bịa.
    """
    text = " ".join((value or "").split())
    if not 2 <= len(text) <= MAX_NAME_CHARS:
        return False
    if text.lower() in GENERIC_TITLES:
        return False

    lowered = text.lower()
    if any(phrase in lowered for phrase in _UI_PHRASES):
        return False

    words = text.split()
    if len(words) > MAX_NAME_WORDS:
        return False

    # Dấu câu cuối câu: tên người không kết thúc bằng `.`/`!`/`?`/`:`
    if text[-1] in ".!?:;":
        return False

    lowered_words = {word.strip(".,!?:;\"'()").lower() for word in words}
    return not (lowered_words & _FUNCTION_WORDS)
