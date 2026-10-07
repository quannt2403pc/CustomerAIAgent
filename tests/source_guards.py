"""Quét **code thật**, bỏ qua comment và docstring — dùng chung cho các luật thép.

Vì sao cần một bản dùng chung: hai luật được canh gác bằng cách quét source —
**L6** (không hardcode tên model) và **L3** (không có đường gửi tin nhắn). Cả hai
đều từng báo động giả vì cách quét ngây thơ:

- L6 chỉ bỏ qua dòng *bắt đầu* bằng `\"\"\"`, nên dòng **tiếp sau** của một docstring
  nhiều dòng giải thích bẫy I-10 bị báo là vi phạm.
- L3 quét cả docstring, nên chính câu "module này **không** import client
  Messenger nào" bị tính là một vi phạm.

Báo động giả làm người ta mất tin vào cái canh gác rồi tắt nó đi — tệ hơn là không
có. Hai lớp giữ hai bản quét riêng thì mỗi lần sửa chỉ sửa được một bên, đúng kiểu
lỗi gốc của I-29.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize


def docstring_line_numbers(tree: ast.AST) -> set[int]:
    """Số dòng của **mọi** docstring, gồm cả dòng tiếp sau của docstring nhiều dòng."""
    lines: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def comment_columns(source: str) -> dict[int, int]:
    """Cột bắt đầu comment của từng dòng, theo **tokenize**.

    Không đoán bằng `line.find("#")`: dấu `#` có thể nằm trong một chuỗi, và cắt
    sai chỗ sẽ bỏ lọt đúng phần code cần kiểm.
    """
    columns: dict[int, int] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            columns[row] = min(columns.get(row, col), col)
    return columns


def find_in_code(source: str, pattern: re.Pattern[str]) -> list[str]:
    """Các dòng **code thật** khớp `pattern`, bỏ qua comment và docstring."""
    allowed = docstring_line_numbers(ast.parse(source))
    columns = comment_columns(source)

    hits: list[str] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        if lineno in allowed:
            continue
        code = line[: columns[lineno]] if lineno in columns else line
        if pattern.search(code):
            hits.append(f"{lineno}: {line.strip()}")
    return hits


def scan_files(
    paths: list[pathlib.Path], pattern: re.Pattern[str], *, root: pathlib.Path
) -> list[str]:
    """Quét nhiều tệp, trả danh sách vi phạm kèm đường dẫn tương đối."""
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root)
        offenders += [
            f"{rel}:{hit}" for hit in find_in_code(path.read_text(encoding="utf-8"), pattern)
        ]
    return offenders


# ---------------------------------------------------------------------------
# Luật thép L3 — đường gửi tin bị khoanh vào ĐÚNG MỘT nơi
# ---------------------------------------------------------------------------
#
# Luật L3 đã đổi có chủ đích (task.md X.6, người dùng quyết): trước đây là "không
# gửi tin cho ai cả", giờ là "**chỉ** gửi cho người đã chủ động nhắn Page trước".
#
# Canh gác vì thế đổi *bản chất* chứ không bị nới ra. Nó canh hai thứ khác nhau:
#
#   1. `SEND_API_PATTERN` — **tự dựng** một đường gửi (gọi thẳng Graph API, hay
#      kéo một thư viện gửi tin vào). Chỉ `app/messenger/` được làm việc đó.
#   2. `SANCTIONED_SEND_CALL` — **gọi** đường gửi đã có. Việc này hợp lệ, nhưng
#      chỉ ở những tệp đã điểm danh, và được đếm chính xác.
#
# Phân biệt hai thứ này là điểm mấu chốt. Gộp chúng lại thì canh gác chặn luôn
# cả cái lối ra duy nhất mà ta vừa cố tình thiết kế — và cách duy nhất để test
# xanh lại sẽ là tắt nó đi. Đó đúng là cái bẫy I-41 đã dạy.
SEND_API_PATTERN = re.compile(
    r"send_message"
    r"|/me/messages"
    r"|graph\.facebook\.com/[^\s\"']*/messages"
    r"|MessengerClient"
    r"|fbmessenger"
    r"|pymessenger",
    re.IGNORECASE,
)

#: Nơi **duy nhất** được tự dựng đường gửi. POSIX để khớp giống nhau mọi OS.
SEND_SANCTUARY = "app/messenger/"

#: Lời gọi hợp lệ duy nhất tới đường gửi, từ bên ngoài `app/messenger/`.
SANCTIONED_SEND_CALL = "messenger.send_text"

#: Những tệp được phép chứa `SANCTIONED_SEND_CALL`. Thêm tệp vào đây buộc người
#: sửa phải nghĩ: lối mới này có kiểm `psid` (tức có kiểm đồng ý) hay không?
SEND_CALLERS_ALLOWED = frozenset({"app/routers/conversations.py"})

#: Những tệp **nói về** Messenger nên đương nhiên chứa chữ đó. Miễn trừ ở đây
#: chỉ là **miễn trừ chữ**; hành vi của chúng vẫn do hai canh gác trên soi.
MESSENGER_AWARE_FILES = frozenset(
    {
        "app/routers/messenger.py",
        "app/services/page_messenger.py",
        "app/core/errors.py",
        "app/core/config.py",
        # Chỉ nối router vào app — không có khả năng gửi gì.
        "app/main.py",
    }
)

#: Mọi chỗ **khác** trong `app/` được phép chứa chữ "messenger".
ALLOWED_MESSENGER_IDENTIFIERS = frozenset(
    {
        "messenger_url_for",
        "messenger_url",
        "PageMessenger",
        "build_messenger",
        "messenger.send_text",
        "app.messenger",
        # Lớp lỗi — chúng **chặn** việc gửi chứ không gửi. `MessengerNotLinked`
        # chính là câu từ chối khi người nhận chưa nhắn Page trước.
        "MessengerDisabled",
        "MessengerNotLinked",
        "MessengerWindowExpired",
    }
)

MESSENGER_WORD_PATTERN = re.compile(r"messenger", re.IGNORECASE)


def unexpected_messenger_mentions(source: str, *, rel_path: str = "") -> list[str]:
    """Dòng code có chữ "messenger" **ngoài** danh sách đã điểm danh."""
    if rel_path.startswith(SEND_SANCTUARY) or rel_path in MESSENGER_AWARE_FILES:
        return []
    hits = find_in_code(source, MESSENGER_WORD_PATTERN)
    return [hit for hit in hits if not any(n in hit for n in ALLOWED_MESSENGER_IDENTIFIERS)]


def send_path_offenders(paths: list[pathlib.Path], *, root: pathlib.Path) -> list[str]:
    """Chỗ **tự dựng** đường gửi ngoài `app/messenger/` — vi phạm L3."""
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(SEND_SANCTUARY):
            continue
        source = path.read_text(encoding="utf-8")
        offenders += [f"{rel}:{hit}" for hit in find_in_code(source, SEND_API_PATTERN)]
    return offenders


def send_call_sites(paths: list[pathlib.Path], *, root: pathlib.Path) -> dict[str, list[str]]:
    """Mọi lời gọi `send_text` ngoài `app/messenger/`, nhóm theo tệp.

    Trả về cả map thay vì chỉ "có/không" để test khẳng định được **đúng một**
    lối ra: thêm một lối thứ hai là thay đổi đáng kể về an toàn, không phải chi
    tiết cài đặt.
    """
    found: dict[str, list[str]] = {}
    pattern = re.compile(r"send_text")
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(SEND_SANCTUARY):
            continue
        hits = find_in_code(path.read_text(encoding="utf-8"), pattern)
        if hits:
            found[rel] = hits
    return found


# ---------------------------------------------------------------------------
# Thứ vẫn bị cấm tuyệt đối: tự động hoá trình duyệt để DM profile cá nhân
# ---------------------------------------------------------------------------
#
# Đây là cách duy nhất về mặt kỹ thuật để nhắn một profile Facebook bất kỳ, và
# là cách đã bị từ chối có lý do: vi phạm ToS Facebook, rủi ro khoá chính tài
# khoản người vận hành, và biến hệ thống thành công cụ nhắn hàng loạt cho người
# chưa hề đồng ý. Nó bị canh **riêng** khỏi `SEND_API_PATTERN` vì không được
# phép tồn tại ở *bất kỳ đâu*, kể cả trong `app/messenger/`.
#
# Canh gác đòi **cả hai** dấu hiệu cùng xuất hiện trong một tệp:
#
#   - một bộ lái trình duyệt (`playwright`, `selenium`, …), VÀ
#   - một URL **giao diện nhắn tin** của Facebook.
#
# Vì sao không chỉ cần một: repo này dùng Playwright thật cho collector (đọc
# bài đăng công khai), và `conversations.py` dựng link `m.me` thật cho người vận
# hành **tự mở**. Cấm từng dấu hiệu riêng lẻ sẽ báo động giả vào hai tính năng
# hợp lệ đó — rồi ai đó sẽ tắt canh gác. Chính sự **kết hợp** mới là tự động hoá.
BROWSER_DRIVER_PATTERN = re.compile(
    r"playwright|selenium|puppeteer|webdriver|pyppeteer|chromedriver", re.IGNORECASE
)

MESSAGING_UI_URL_PATTERN = re.compile(
    r"messenger\.com|facebook\.com/messages|m\.me/|mbasic\.facebook\.com", re.IGNORECASE
)


def browser_automation_offenders(paths: list[pathlib.Path], *, root: pathlib.Path) -> list[str]:
    """Tệp có **cả** bộ lái trình duyệt **và** URL giao diện nhắn tin."""
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        driver = find_in_code(source, BROWSER_DRIVER_PATTERN)
        ui_url = find_in_code(source, MESSAGING_UI_URL_PATTERN)
        if driver and ui_url:
            rel = path.relative_to(root).as_posix()
            offenders.append(f"{rel}: lái trình duyệt {driver[0]!r} + URL nhắn tin {ui_url[0]!r}")
    return offenders


# ---------------------------------------------------------------------------
# Logger stdlib không nhận kwargs tuỳ ý
# ---------------------------------------------------------------------------
#
# `app.core.logging.get_logger` trả một `logging.Logger` **chuẩn**, không phải
# structlog. Viết `log.warning("abc", detail=x)` theo thói quen structlog sẽ ném
# `TypeError: Logger._log() got an unexpected keyword argument` — nhưng chỉ
# **lúc dòng log đó chạy**, nên nó lọt qua lint, qua type check, và qua test
# nếu nhánh ấy không được chạy.
#
# Đo thật (task.md I-54): một dòng như vậy trong handler webhook biến mọi tin
# sai chữ ký thành 500 thay vì 403 — và Facebook gửi lại khi nhận 5xx.
LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "log"})

#: Những kwarg `logging` **thật sự** nhận.
LOGGING_REAL_KWARGS = frozenset({"exc_info", "stack_info", "stacklevel", "extra"})


def logger_kwarg_offenders(paths: list[pathlib.Path], *, root: pathlib.Path) -> list[str]:
    """Lời gọi logger dùng kwarg mà `logging` không nhận."""
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in LOG_LEVELS:
                continue
            # Chỉ xét lời gọi trên một tên trông như logger, để không bắt oan
            # `self.warning(...)` của lớp khác.
            target = node.func.value
            name = target.id if isinstance(target, ast.Name) else ""
            if name not in {"log", "logger", "LOG", "LOGGER"}:
                continue
            bad = [kw.arg for kw in node.keywords if kw.arg not in LOGGING_REAL_KWARGS]
            if bad:
                offenders.append(f"{rel}:{node.lineno}: {name}.{node.func.attr}(… {bad})")
    return offenders
