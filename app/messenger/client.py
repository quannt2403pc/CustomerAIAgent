"""Gửi tin qua Facebook Page (Messenger Platform Send API).

Luật L3 ở bản này (đã sửa có chủ đích theo quyết định người dùng — task.md X.6):

    Chỉ được gửi tin cho người đã **chủ động nhắn Page trước**.

Điều kiện đó không phải lời hứa trong tài liệu mà được **cấu trúc dữ liệu thi
hành**: `send_text` đòi một `psid`, và PSID chỉ tồn tại trong DB khi webhook
nhận được tin của chính người đó. Không có đường nào tạo PSID từ một URL
profile hay một username.

Vẫn **không** hiện thực: tự động hoá trình duyệt đã đăng nhập để DM profile cá
nhân. Việc đó vi phạm ToS Facebook, rủi ro khoá tài khoản người vận hành, và
biến hệ thống thành công cụ nhắn hàng loạt cho người chưa đồng ý.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from app.core.errors import (
    MessengerDisabled,
    MessengerError,
    MessengerNotLinked,
    MessengerWindowExpired,
)

#: Facebook trả mã 10 kèm subcode này khi đã quá cửa sổ nhắn tin cho phép.
#: Phân biệt được nó mới nói đúng cho người vận hành là "phải chờ khách nhắn
#: lại", thay vì để họ bấm thử lại vô ích.
_SUBCODE_OUTSIDE_WINDOW: Final = 2018278

#: Hết hạn/thu hồi token. Retry chỉ làm tệ hơn, nên tách riêng.
_CODES_AUTH: Final = frozenset({190, 102})


class PageMessenger:
    """Gửi tin thay cho một Facebook Page cụ thể.

    `page_access_token` lấy từ `llm_credentials` (mã hoá Fernet at-rest), không
    từ biến môi trường: nó là secret người dùng dán trên UI, và L4 cấm secret
    đi vào Git dưới mọi hình thức.
    """

    def __init__(
        self,
        *,
        page_access_token: str,
        base_url: str,
        api_version: str,
        use_human_agent_tag: bool = True,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not page_access_token.strip():
            raise MessengerDisabled
        self._token = page_access_token.strip()
        root = f"{base_url.rstrip('/')}/{api_version}"
        self._endpoint = f"{root}/me/messages"
        self._names_base = root
        self._use_human_agent_tag = use_human_agent_tag
        self._timeout = timeout
        self._client = client

    async def send_text(self, *, psid: str, text: str) -> str:
        """Gửi `text` tới `psid`. Trả `message_id` Facebook cấp.

        `message_id` được trả về chứ không bỏ đi: nó là **bằng chứng tin đã đi
        thật**, và là thứ duy nhất phân biệt "đã gửi" với "tưởng đã gửi" khi
        đối chiếu về sau.
        """
        if not psid.strip():
            raise MessengerNotLinked
        body = self._build_body(psid=psid.strip(), text=text)
        payload = await self._post(body)
        message_id = str(payload.get("message_id") or "").strip()
        if not message_id:
            raise MessengerError(detail=f"Send API thiếu message_id: {payload!r}")
        return message_id

    async def fetch_display_name(self, psid: str) -> str | None:
        """Tên hiển thị của người có `psid`, hoặc `None` nếu không lấy được.

        Dùng để hội thoại đến từ webhook không hiện ra vô danh. Trả `None` thay
        vì dựng một nhãn tạm: một cái tên bịa trong ô "khách hàng" là đúng thứ
        luật L1 cấm, và nó sẽ đi tiếp vào prompt ở lượt gợi ý sau.

        Lỗi ở đây **không** được làm vỡ luồng nhận tin — tin của khách quan
        trọng hơn cái tên, nên mọi thất bại đều quy về `None`.
        """
        url = f"{self._names_base}/{psid.strip()}"
        params = {"fields": "name", "access_token": self._token}
        try:
            if self._client is not None:
                resp = await self._client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                return None
            name = str((resp.json() or {}).get("name") or "").strip()
        except (httpx.HTTPError, ValueError):
            return None
        return name[:120] or None

    def _build_body(self, *, psid: str, text: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "recipient": {"id": psid},
            "message": {"text": text},
            # `RESPONSE` = đang trả lời tin khách vừa gửi. Đúng bản chất việc ta
            # làm, và là loại duy nhất không cần message tag trong cửa sổ 24h.
            "messaging_type": "RESPONSE",
        }
        if self._use_human_agent_tag:
            # Nới cửa sổ 24h → 7 ngày, với điều kiện người thật soạn/bấm gửi.
            # Điều kiện đó đúng ở đây: mọi tin đều do người vận hành chọn.
            body["messaging_type"] = "MESSAGE_TAG"
            body["tag"] = "HUMAN_AGENT"
        return body

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        params = {"access_token": self._token}
        try:
            if self._client is not None:
                resp = await self._client.post(self._endpoint, params=params, json=body)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(self._endpoint, params=params, json=body)
        except httpx.HTTPError as exc:
            raise MessengerError(detail=f"Không nối được Graph API: {exc!r}") from exc

        if resp.status_code >= 400:
            raise self._translate(resp)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise MessengerError(detail="Graph API trả về thân không phải JSON.") from exc
        if not isinstance(payload, dict):
            raise MessengerError(detail=f"Graph API trả kiểu lạ: {type(payload)!r}")
        return payload

    @staticmethod
    def _translate(resp: httpx.Response) -> MessengerError:
        """Đổi lỗi Graph API thành lỗi của app — **không** rò thân response.

        Thân lỗi Graph API chứa `fbtrace_id` và đôi khi cả phần token trong
        thông điệp. Nó chỉ được đi vào `detail` (log server), không bao giờ vào
        `message` (hiện trên UI) — plan.md §7.3.6 và luật L5.
        """
        try:
            error = (resp.json() or {}).get("error") or {}
        except ValueError:
            error = {}
        code = error.get("code")
        subcode = error.get("error_subcode")
        detail = f"Graph API {resp.status_code} code={code} subcode={subcode}"

        if subcode == _SUBCODE_OUTSIDE_WINDOW:
            return MessengerWindowExpired(detail=detail)
        if code in _CODES_AUTH:
            return MessengerDisabled(
                "Page Access Token đã hết hạn hoặc bị thu hồi. "
                "Vào Cài đặt → Kết nối Facebook Page để dán token mới.",
                detail=detail,
            )
        # 400 kèm "No matching user found" = PSID không thuộc Page này.
        if resp.status_code == 400 and code == 100:
            return MessengerNotLinked(detail=detail)
        return MessengerError(detail=detail)
