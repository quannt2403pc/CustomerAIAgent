"""Client Management API của CLIProxy (`/v0/management/*`).

Các route đã **đo thật** trên `eceasy/cli-proxy-api:latest` v8.0.16 (2026-10-06):

| Việc | Route |
|---|---|
| Xin URL đăng nhập | `GET /antigravity-auth-url?is_webui=1` → `{status, url, state}` |
| Poll chờ người dùng đồng ý | `GET /get-auth-status?state=…` → `wait` / `ok` / `error` |
| Nạp callback (dự phòng) | `POST /oauth-callback` `{state, code}` |
| Huỷ phiên đang chờ | `DELETE /oauth-session?state=…` |
| Kiểm tra đã kết nối | `GET /auth-files` |
| Ngắt kết nối | `DELETE /auth-files?name=…` |
| Danh mục model | `GET /model-definitions/<channel>` |

Hai điều quan trọng về module này:

- **Không retry 401/403.** `request_with_retry` đã lo, nhưng đừng bọc thêm vòng
  retry nào quanh đây: sai management key 5 lần → CLIProxy ban IP 30 phút, và
  container `api` chỉ có một IP (bẫy B3). Gỡ ban: `docker compose restart cliproxy`.
- **Trạng thái kết nối đọc từ `auth-files`**, không từ `get-auth-status` (bẫy B6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import GatewayAuthError, GatewayBadResponse, GatewayDisabled
from app.core.logging import get_logger
from app.llm.base import ModelInfo
from app.llm.gemini_wire import request_with_retry

log = get_logger(__name__)

MANAGEMENT_PREFIX = "/v0/management"
PROVIDER_LABEL = "cliproxy-management"


@dataclass(frozen=True)
class OAuthSession:
    """URL đồng ý của Google + `state` để theo dõi phiên (CLIProxy giữ 5 phút)."""

    url: str
    state: str


@dataclass(frozen=True)
class OAuthStatus:
    status: Literal["wait", "ok", "error"]
    state: str
    error: str = ""

    @property
    def is_final(self) -> bool:
        return self.status != "wait"


@dataclass(frozen=True)
class AuthFile:
    """Một credential OAuth đã lưu trong `auth-dir` của CLIProxy."""

    name: str
    account: str | None = None

    @classmethod
    def from_wire(cls, raw: Any) -> AuthFile:
        # CLIProxy trả hoặc chuỗi tên file, hoặc object có nhiều field — nhận cả hai.
        if isinstance(raw, str):
            return cls(name=raw, account=_account_from_filename(raw))
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("file") or raw.get("filename") or "")
            account = raw.get("email") or raw.get("account") or _account_from_filename(name)
            return cls(name=name, account=account)
        raise GatewayBadResponse(detail=f"auth-file có kiểu lạ: {type(raw).__name__}")


class CliProxyAdmin:
    """Bọc `/v0/management`. Dùng một `AsyncClient` cho cả vòng đời."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None):
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))

    @property
    def base_url(self) -> str:
        return self._settings.cliproxy_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        key = self._settings.require_cliproxy_mgmt_key()
        return {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{MANAGEMENT_PREFIX}{path}"
        response = await request_with_retry(
            self._client,
            method,
            url,
            provider=PROVIDER_LABEL,
            headers=self._headers(),
            **kwargs,
        )
        return _json_body(response)

    # -- Trạng thái kết nối -------------------------------------------------
    async def auth_files(self) -> list[AuthFile]:
        """Danh sách credential đã lưu.

        **Đây** là nguồn sự thật cho badge "Đã kết nối" (bẫy B6):
        `get-auth-status` thiếu `state` sẽ trả `{"status":"ok"}` dù chưa đăng
        nhập bao giờ.
        """
        body = await self._request("GET", "/auth-files")
        raw_files = body.get("files")
        if raw_files is None:
            raise GatewayBadResponse(detail=f"/auth-files thiếu khoá `files`: {list(body)}")
        return [AuthFile.from_wire(item) for item in raw_files]

    async def is_connected(self) -> bool:
        return bool(await self.auth_files())

    async def delete_auth_file(self, name: str) -> None:
        """Ngắt kết nối một credential.

        Bẫy B10: route **không có** chế độ "xoá tất cả"; gọi thiếu `?name=` trả
        400 `{"error":"invalid name"}`. Muốn xoá hết thì lấy danh sách rồi xoá
        từng file (xem `disconnect_all`).
        """
        if not name:
            raise ValueError("Phải nêu tên auth-file cần xoá (bẫy B10: không có 'xoá tất cả').")
        await self._request("DELETE", "/auth-files", params={"name": name})
        log.info("Đã xoá auth-file")

    async def disconnect_all(self) -> int:
        """Xoá từng auth-file một. Trả số file đã xoá."""
        files = await self.auth_files()
        for item in files:
            await self.delete_auth_file(item.name)
        return len(files)

    # -- Luồng OAuth -------------------------------------------------------
    async def start_oauth(self) -> OAuthSession:
        """Xin URL đồng ý của Google + `state` để theo dõi phiên.

        `is_webui=1` để CLIProxy **không** tự mở trình duyệt phía server — trong
        container thì không có trình duyệt nào, còn ta cần URL trả về cho FE.
        """
        body = await self._request("GET", "/antigravity-auth-url", params={"is_webui": 1})
        _raise_if_body_says_error(body, what="xin URL đăng nhập")

        url = body.get("url")
        state = body.get("state")
        if not url or not state:
            raise GatewayBadResponse(detail=f"/antigravity-auth-url thiếu url/state: {list(body)}")
        return OAuthSession(url=str(url), state=str(state))

    async def oauth_status(self, state: str) -> OAuthStatus:
        """Trạng thái một phiên đang chờ: `wait` → `ok` / `error`.

        Hai bẫy cùng chỗ:

        - **B6** — gọi **thiếu `state`** trả `{"status":"ok"}` dù chưa đăng nhập
          bao giờ. Vì vậy `state` ở đây là bắt buộc, và badge "Đã kết nối" phải
          đọc từ `auth_files()`, không từ hàm này.
        - **B7** — lỗi được báo bằng **HTTP 200** kèm `{"status":"error"}`
          (đo thật: `{"error":"Failed to exchange token","status":"error"}`).
          Đọc theo status code sẽ tưởng thành công.
        """
        if not state:
            raise ValueError(
                "oauth_status() bắt buộc có `state`. Thiếu state, CLIProxy trả "
                '{"status":"ok"} dù chưa đăng nhập bao giờ (bẫy B6).'
            )
        body = await self._request("GET", "/get-auth-status", params={"state": state})
        status = str(body.get("status") or "")
        if status == "error":
            return OAuthStatus(state=state, status="error", error=str(body.get("error") or ""))
        if status not in ("wait", "ok"):
            raise GatewayBadResponse(detail=f"get-auth-status trả status lạ: {status!r}")
        return OAuthStatus(state=state, status=status)  # type: ignore[arg-type]

    async def submit_callback(self, state: str, callback_url: str) -> None:
        """Đường dự phòng: người dùng dán URL callback vào UI.

        CLIProxy nhận `{state, code}` chứ không nhận cả URL (task.md I-08), nên
        ta tự bóc `code` ra khỏi URL người dùng dán. Nhờ vậy UI chỉ cần một ô
        dán duy nhất thay vì bắt họ tự tìm tham số `code`.
        """
        code, state_in_url = _parse_callback_url(callback_url)
        if state_in_url and state_in_url != state:
            raise GatewayBadResponse(
                "URL bạn dán thuộc một phiên đăng nhập khác. Hãy bấm "
                "“Đăng nhập Google” lại rồi dán URL mới.",
                detail="state trong URL không khớp state của phiên",
            )
        body = await self._request("POST", "/oauth-callback", json={"state": state, "code": code})
        _raise_if_body_says_error(body, what="nạp URL callback")

    async def cancel_oauth(self, state: str) -> bool:
        """Huỷ phiên đang chờ. CLIProxy chỉ giữ `state` 5 phút."""
        if not state:
            raise ValueError("cancel_oauth() cần `state`.")
        body = await self._request("DELETE", "/oauth-session", params={"state": state})
        return bool(body.get("cancelled", body.get("status") == "ok"))

    # -- Danh mục model (luật L6) ------------------------------------------
    async def model_definitions(self, channel: str | None = None) -> list[ModelInfo]:
        """Danh mục model **thật** của một channel.

        Năng lực vision đọc từ `supportedInputModalities` — dữ liệu thật do
        CLIProxy trả, không suy đoán từ tên model (task.md I-06).
        """
        channel = channel or self._settings.cliproxy_auth_provider
        body = await self._request("GET", f"/model-definitions/{channel}")
        raw_models = body.get("models")
        if raw_models is None:
            raise GatewayBadResponse(
                detail=f"/model-definitions/{channel} thiếu khoá `models`: {list(body)}"
            )
        return [_model_info_from_wire(item) for item in raw_models if isinstance(item, dict)]

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _model_info_from_wire(raw: dict[str, Any]) -> ModelInfo:
    model_id = str(raw.get("id") or raw.get("name") or "")
    modalities = raw.get("supportedInputModalities")
    supports_vision = "image" in modalities if isinstance(modalities, list) else None
    return ModelInfo(
        id=model_id,
        display_name=str(raw.get("display_name") or raw.get("description") or model_id),
        supports_vision=supports_vision,
        input_token_limit=_as_int(raw.get("context_length")),
        output_token_limit=_as_int(raw.get("max_completion_tokens")),
    )


def _raise_if_body_says_error(body: dict[str, Any], *, what: str) -> None:
    """Bẫy B7: CLIProxy báo lỗi bằng **HTTP 200** + `{"status":"error"}`.

    Mọi chỗ đọc phản hồi quản trị phải đi qua đây, không đọc theo status code.
    """
    if body.get("status") != "error":
        return
    detail = str(body.get("error") or "không rõ")
    if "expired" in detail.lower() or "unknown" in detail.lower():
        raise GatewayAuthError(
            "Phiên đăng nhập đã hết hạn (CLIProxy chỉ giữ 5 phút). "
            "Hãy bấm “Đăng nhập Google” để mở phiên mới.",
            detail=f"{what}: {detail}",
        )
    raise GatewayAuthError(
        f"Không {what} được. Hãy thử đăng nhập lại.",
        detail=f"{what}: {detail}",
    )


def _parse_callback_url(callback_url: str) -> tuple[str, str | None]:
    """Bóc `code` (và `state` nếu có) khỏi URL callback người dùng dán."""
    raw = (callback_url or "").strip()
    if not raw:
        raise GatewayBadResponse("Chưa dán URL callback.", detail="callback_url rỗng")

    query = urlparse(raw).query or raw.partition("?")[2]
    params = parse_qs(query)

    if error := params.get("error"):
        raise GatewayAuthError(
            f"Google từ chối đăng nhập: {error[0]}. Hãy thử lại và chấp nhận quyền truy cập.",
            detail=f"error trong URL callback: {error[0]}",
        )

    code = (params.get("code") or [""])[0]
    if not code:
        raise GatewayBadResponse(
            "URL bạn dán không chứa tham số `code`. Hãy sao chép **toàn bộ** URL "
            "trên thanh địa chỉ sau khi đồng ý ở Google.",
            detail="thiếu code trong URL callback",
        )
    return code, (params.get("state") or [None])[0]


def _account_from_filename(name: str) -> str | None:
    """`antigravity-ten@gmail.com.json` → `ten@gmail.com`."""
    stem = name.removesuffix(".json")
    _, _, tail = stem.partition("-")
    return tail if "@" in tail else None


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        # Thân rỗng/HTML thường là dấu hiệu route quản trị không bật.
        raise GatewayDisabled(detail=f"phản hồi không phải JSON: {response.text[:200]}") from exc
    if not isinstance(body, dict):
        raise GatewayBadResponse(detail=f"phản hồi không phải object JSON: {type(body).__name__}")
    return body
