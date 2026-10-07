"""Tích hợp Facebook Page / Messenger Platform (task.md X.6).

**Đây là nơi duy nhất trong repo được phép chứa đường gửi tin ra ngoài.**
Canh gác ở `tests/source_guards.py` chặn mọi module khác. Lý do đặt ranh giới
cứng như vậy: nếu đường gửi nằm rải rác thì không ai còn kiểm được điều kiện
đồng ý có thật sự được thi hành ở mọi lối vào hay không.
"""

from app.messenger.client import (
    MessengerDisabled,
    MessengerError,
    MessengerNotLinked,
    PageMessenger,
)
from app.messenger.webhook import (
    InboundMessage,
    SignatureInvalid,
    parse_inbound,
    verify_signature,
)

__all__ = [
    "InboundMessage",
    "MessengerDisabled",
    "MessengerError",
    "MessengerNotLinked",
    "PageMessenger",
    "SignatureInvalid",
    "parse_inbound",
    "verify_signature",
]
