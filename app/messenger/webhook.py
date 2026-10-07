"""Nhận tin đến từ Messenger Platform — xác thực và bóc tách.

Hai việc tách rời có chủ đích:

- `verify_signature` — **tin này có đúng từ Facebook không?** Webhook là một
  endpoint công khai, ai cũng POST được. Không kiểm chữ ký thì bất kỳ ai cũng
  bơm được "khách đã trả lời ABC" vào hệ thống, và lượt gợi ý kế tiếp sẽ dựa
  trên dữ liệu bịa — hỏng thẳng luật L1.
- `parse_inbound` — bóc payload lồng nhiều lớp thành danh sách phẳng.

Cả hai đều **thuần**, không chạm DB và không gọi mạng, nên test được bằng
payload thật đã lưu lại.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


class SignatureInvalid(Exception):
    """Chữ ký `X-Hub-Signature-256` không khớp — coi như tin giả, bỏ."""


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Một tin **khách thật đã gửi** tới Page."""

    #: Page-Scoped ID của người gửi. Vừa là địa chỉ để trả lời, vừa là bằng
    #: chứng họ đã chủ động nhắn Page trước — điều kiện duy nhất cho phép gửi.
    psid: str
    text: str
    #: ID tin của Facebook. Dùng để **chống xử lý lặp**: Facebook gửi lại
    #: webhook khi ta trả về mã lỗi, nên cùng một tin có thể đến nhiều lần.
    message_id: str
    #: Epoch **milli**giây (Facebook dùng ms, không phải giây).
    timestamp_ms: int


def verify_signature(*, app_secret: str, raw_body: bytes, header: str | None) -> None:
    """Kiểm `X-Hub-Signature-256`. Không khớp → `SignatureInvalid`.

    Dùng `hmac.compare_digest`, không dùng `==`: so sánh chuỗi thông thường
    thoát ra ngay byte đầu khác nhau, nên thời gian chạy tiết lộ bao nhiêu byte
    đã đúng — đủ để dò dần ra chữ ký hợp lệ.
    """
    if not app_secret:
        # Không có secret thì **không thể** xác thực. Chấp nhận tin trong trạng
        # thái này còn tệ hơn là từ chối, nên từ chối.
        raise SignatureInvalid("Chưa cấu hình MESSENGER_APP_SECRET — không xác thực được tin đến.")
    if not header or not header.startswith("sha256="):
        raise SignatureInvalid("Thiếu hoặc sai dạng header X-Hub-Signature-256.")

    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header.removeprefix("sha256=")):
        raise SignatureInvalid("Chữ ký X-Hub-Signature-256 không khớp.")


def parse_inbound(payload: dict[str, Any]) -> list[InboundMessage]:
    """Bóc các tin **văn bản của người thật** khỏi payload webhook.

    Bỏ qua có chủ đích:

    - `message.is_echo` — tin **chính Page vừa gửi** dội lại. Không lọc thì mỗi
      tin ta gửi sẽ được ghi lại như một lượt "khách trả lời".
    - tin chỉ có `attachments` (ảnh/sticker, không chữ) — không có gì để đưa vào
      ngữ cảnh gợi ý; bịa nội dung cho nó là vi phạm L1.
    - `delivery` / `read` / `postback` — không phải lời khách nói.
    """
    if payload.get("object") != "page":
        return []

    out: list[InboundMessage] = []
    for entry in payload.get("entry") or []:
        for event in entry.get("messaging") or []:
            message = event.get("message")
            if not isinstance(message, dict) or message.get("is_echo"):
                continue
            text = (message.get("text") or "").strip()
            psid = ((event.get("sender") or {}).get("id") or "").strip()
            message_id = (message.get("mid") or "").strip()
            if not text or not psid or not message_id:
                continue
            out.append(
                InboundMessage(
                    psid=psid,
                    text=text,
                    message_id=message_id,
                    timestamp_ms=int(event.get("timestamp") or 0),
                )
            )
    return out
