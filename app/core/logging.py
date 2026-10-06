"""Logging — hai ràng buộc cứng.

1. **Mọi log đi stderr.** stdout dành riêng cho chuỗi JSON của CLI, nên
   `python main.py --url … > output.json` luôn ra file sạch (plan.md §5.7).
2. **Không secret nào lọt vào log.** Che theo mẫu (plan.md §7.2):
   `Authorization`, `x-goog-api-key`, `secret-key`, `key=`, `code=`, `state=`,
   cookie Facebook.

Việc che diễn ra ở **hai** chỗ, có lý do:
- `SecretRedactingFilter` che `record.msg` → dọn sạch ngay cả với handler
  dùng formatter khác.
- `RedactingFormatter` che chuỗi **cuối cùng** → bắt được secret nằm trong
  traceback, vì `exc_text` chỉ được dựng lúc format, sau khi filter đã chạy.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

MASK = "***"

# Nhãn nào xuất hiện là coi như giá trị đi kèm phải che.
_SENSITIVE_LABELS = (
    "authorization",
    "x-goog-api-key",
    "api-key",
    "api_key",
    "apikey",
    "google_api_key",
    "secret-key",
    "secret_key",
    "mgmt_key",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "key",
    "code",
    "state",
)
_LABELS_RE = "|".join(re.escape(label) for label in _SENSITIVE_LABELS)

# Ký tự kết thúc một giá trị: khoảng trắng, dấu nháy, dấu phân cách JSON/query.
_VALUE = r"[^\s'\",;}\]&]+"

_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `nhãn: giá trị` / `"nhãn": "giá trị"` / `nhãn=giá trị` / `?nhãn=giá trị`
    # Group 1 giữ lại phần nhãn để log còn đọc được là đã che cái gì.
    re.compile(
        rf"(?i)(['\"]?(?:{_LABELS_RE})['\"]?\s*[:=]\s*['\"]?)(?:bearer\s+)?{_VALUE}",
    ),
    # Cookie Facebook do người dùng tự cung cấp (L3 — tuỳ chọn, mã hoá at-rest).
    re.compile(rf"(?i)\b((?:c_user|xs|fr|datr|sb)=){_VALUE}"),
    # `Bearer <token>` trần, không có nhãn phía trước.
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
)


def redact(text: str) -> str:
    """Che mọi secret nhận dạng được trong `text`."""
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}{MASK}", text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Che secret trên chuỗi log đã format.

    Thay `record.msg` bằng kết quả đã che và xoá `record.args` — nếu giữ args,
    `Formatter` sẽ format lại và secret quay về.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except (TypeError, ValueError):
            rendered = str(record.msg)

        cleaned = redact(rendered)
        if cleaned != rendered or record.args:
            record.msg = cleaned
            record.args = ()

        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class RedactingFormatter(logging.Formatter):
    """Che secret trên chuỗi cuối cùng, sau khi traceback đã được dựng."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """StreamHandler neo cứng vào stderr.

    `stream` phân giải **lúc emit**, không lúc khởi tạo: ai đổi `sys.stderr`
    (pytest capsys, uvicorn reload, redirect của người dùng) thì log đi theo —
    nhưng không bao giờ đi được sang stdout, vì stdout là chỗ của JSON CLI.
    """

    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)

    @property  # type: ignore[override]
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        # Bỏ qua mọi mưu toan gán stream khác — kể cả từ StreamHandler.__init__.
        pass


_CONFIGURED = False


def setup_logging(level: str = "INFO", *, force: bool = False) -> None:
    """Cấu hình root logger: 1 handler duy nhất, ra stderr, đã che secret."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    handler = StderrHandler()
    handler.setFormatter(
        RedactingFormatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(SecretRedactingFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # httpx log cả URL (có thể chứa ?key=). Bộ lọc đã che, nhưng hạ mức cho đỡ nhiễu.
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("httpcore").setLevel("WARNING")
    logging.getLogger("apscheduler").setLevel("WARNING")

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_repr(value: Any, *, limit: int = 500) -> str:
    """repr đã che secret và cắt ngắn — dùng khi buộc phải log một payload."""
    text = redact(repr(value))
    return text if len(text) <= limit else text[:limit] + "…"
