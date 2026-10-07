"""`/api/llm/*` — cổng model: chọn cổng, OAuth, API key, danh mục, kiểm tra.

Đây là hạng mục người dùng bổ sung so với đề bài (plan.md §5.1), nên nó được đặc
tả kỹ nhất. Ba điều router này cưỡng chế:

- **Không bao giờ trả API key.** `GET /api/llm/api-key` chỉ có `{is_set, hint}`.
- **Xác thực key trước khi ghi DB.** Lưu key sai rồi để pipeline chết lúc 20h là
  kiểu lỗi tệ nhất: xảy ra khi không ai nhìn.
- **Không hardcode danh mục model** (luật L6). Mọi tên model đi qua đây đều đến
  từ cổng đang chọn lúc chạy.

Bẫy B3 (sai management key 5 lần → CLIProxy ban IP 30 phút) được tôn trọng ở
tầng dưới: `request_with_retry` **không** retry 401/403. Đừng thêm vòng retry nào
quanh các endpoint ở đây.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query

from app.collectors import facebook_cookie
from app.core.errors import GatewayError, GatewayModelInvalid, GatewayNotConfigured
from app.core.logging import get_logger
from app.core.ratelimit import llm_test_rate_limit
from app.llm import gemini_wire
from app.llm.base import GatewayHealth, LLMGateway, ModelInfo
from app.llm.catalog import get_catalog
from app.llm.cliproxy_admin import CliProxyAdmin
from app.llm.resolver import get_active_config, set_model, set_provider
from app.routers.deps import SessionDep, gateway_scope
from app.schemas.api import (
    ActionResultOut,
    CookieStatusOut,
    CredentialOut,
    GatewayTestOut,
    LlmStatusOut,
    ModelListOut,
    ModelOut,
    OAuthCallbackRequest,
    OAuthStartOut,
    OAuthStatusOut,
    SaveApiKeyRequest,
    SaveCookieRequest,
    SetModelRequest,
    SetProviderRequest,
)
from app.services import audit, credentials

log = get_logger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])

# Prompt kiểm tra cố ý **cực ngắn**: mục đích là đo "cổng có trả lời không",
# không phải đánh giá chất lượng. Dài hơn chỉ tốn quota (task.md I-25).
TEST_PROMPT = "Trả lời đúng một từ: OK"
# Hạn mức rộng dù chỉ cần một từ: thinking token của Gemini 3.x tính vào
# `maxOutputTokens`, cap chặt làm câu trả lời bị cắt sạch (task.md I-16).
TEST_MAX_OUTPUT_TOKENS = 512


# ---------------------------------------------------------------------------
# Trạng thái
# ---------------------------------------------------------------------------
@router.get("/status", response_model=LlmStatusOut)
async def get_status(session: SessionDep) -> LlmStatusOut:
    """Cổng đang chọn + đã kết nối chưa + model đang dùng.

    Cố ý **không** raise khi chưa cấu hình: trang Cài đặt phải mở được để người
    vận hành nhìn thấy "chưa chọn cổng" rồi đi sửa. Trả 409 ở đây làm UI hiện
    toast lỗi trên đúng cái trang dùng để sửa lỗi đó.
    """
    config = await get_active_config(session)
    key_info = await credentials.describe(session, credentials.KIND_GOOGLE_API_KEY)

    health: GatewayHealth | None = None
    detail = ""
    if config.is_configured:
        try:
            async with gateway_scope(session) as gateway:
                health = await gateway.health()
        except GatewayError as exc:
            # Chưa có credential là trạng thái **bình thường** của lần cài đầu,
            # không phải sự cố — hiện câu hướng dẫn, không hiện lỗi đỏ.
            detail = exc.message
    else:
        detail = GatewayNotConfigured.message

    return LlmStatusOut(
        provider=config.provider or None,
        model=config.model or None,
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
        reachable=bool(health and health.reachable),
        connected=bool(health and health.connected),
        account=health.account if health else None,
        detail=health.detail if health and health.detail else detail,
        latency_ms=health.latency_ms if health else None,
        must_choose_model=not config.model,
        api_key=_credential_out(key_info),
    )


@router.put("/provider", response_model=LlmStatusOut)
async def put_provider(body: SetProviderRequest, session: SessionDep) -> LlmStatusOut:
    """Đổi cổng. **Xoá model đang chọn** vì danh mục hai cổng gần như rời nhau.

    Đo thật (task.md I-10): cổng A có 14 model, cổng B có 44, `gemini-flash-latest`
    chỉ có ở B, `gemini-3-flash` chỉ có ở A. Giữ lại model cũ sẽ tạo một cấu hình
    **trông** hợp lệ mà gọi là lỗi; để rỗng thì UI buộc chọn lại — đúng điều cần
    xảy ra. Response mang `must_choose_model=true` để UI biết phải mở dropdown.
    """
    await set_provider(session, body.provider)
    # Danh mục cũ không còn liên quan; để lại thì dropdown hiện model của cổng kia.
    get_catalog().invalidate()
    await audit.record(session, "llm.set_provider", target=body.provider)
    return await get_status(session)


# ---------------------------------------------------------------------------
# Cổng A — OAuth Google qua CLIProxy
# ---------------------------------------------------------------------------
@router.post("/oauth/start", response_model=OAuthStartOut)
async def oauth_start(session: SessionDep) -> OAuthStartOut:
    """Xin URL đồng ý của Google + `state`.

    Không yêu cầu `provider` đang là `antigravity`: người dùng thường bấm "Đăng
    nhập Google" **trước** khi chốt chọn cổng, và chặn họ ở đây chỉ tạo một bước
    vòng vo không bảo vệ điều gì.
    """
    admin = CliProxyAdmin()
    try:
        oauth = await admin.start_oauth()
    finally:
        await admin.aclose()

    await audit.record(session, "llm.oauth_start", target="antigravity")
    # KHÔNG log `state` (plan.md §7.2) — nó là định danh phiên đăng nhập.
    log.info("Đã mở phiên đăng nhập Google")
    return OAuthStartOut(url=oauth.url, state=oauth.state)


@router.get("/oauth/status", response_model=OAuthStatusOut)
async def oauth_status(
    session: SessionDep,
    state: str = Query(min_length=1, description="state do /oauth/start trả về"),
) -> OAuthStatusOut:
    """Poll `wait` → `ok` / `error`.

    `state` là **bắt buộc** (bẫy B6): gọi thiếu `state`, CLIProxy trả
    `{"status":"ok"}` dù chưa đăng nhập bao giờ. Và khi `ok`, badge "Đã kết nối"
    vẫn đọc từ `auth-files` chứ không tin lời `get-auth-status`.
    """
    admin = CliProxyAdmin()
    try:
        status = await admin.oauth_status(state)
        if status.status != "ok":
            return OAuthStatusOut(
                status=status.status,
                message=(
                    "Đang chờ bạn đồng ý ở cửa sổ Google…"
                    if status.status == "wait"
                    # `status.error` là tiếng Anh kỹ thuật → vào log, không ra UI.
                    else "Google không hoàn tất đăng nhập. Hãy bấm “Đăng nhập Google” để thử lại."
                ),
            )

        files = await admin.auth_files()
        account = next((f.account for f in files if f.account), None)
    finally:
        await admin.aclose()

    if files:
        await audit.record(session, "llm.oauth_connected", target="antigravity")

    return OAuthStatusOut(
        status="ok",
        connected=bool(files),
        account=account,
        message=(
            f"Đã kết nối{f' ({account})' if account else ''}."
            if files
            else "Google báo xong nhưng CLIProxy chưa lưu được tài khoản nào. Hãy thử lại."
        ),
    )


@router.post("/oauth/callback", response_model=ActionResultOut)
async def oauth_callback(body: OAuthCallbackRequest, session: SessionDep) -> ActionResultOut:
    """Đường dự phòng: người dùng dán URL callback (bẫy B1).

    CLIProxy nhận `{state, code}`, không nhận `url` (task.md I-08) → backend tự
    bóc `code`. Nhờ vậy UI chỉ cần một ô dán thay vì bắt người dùng tự tìm tham
    số `code` trong URL.
    """
    admin = CliProxyAdmin()
    try:
        await admin.submit_callback(body.state, body.url)
    finally:
        await admin.aclose()

    await audit.record(session, "llm.oauth_callback_manual", target="antigravity")
    return ActionResultOut(message="Đã nạp URL callback. Hãy kiểm tra lại trạng thái kết nối.")


@router.delete("/oauth/session", response_model=ActionResultOut)
async def oauth_cancel(
    state: str = Query(min_length=1, description="state của phiên cần huỷ"),
) -> ActionResultOut:
    """Huỷ phiên đang chờ. CLIProxy chỉ giữ `state` 5 phút."""
    admin = CliProxyAdmin()
    try:
        cancelled = await admin.cancel_oauth(state)
    finally:
        await admin.aclose()
    return ActionResultOut(
        ok=cancelled,
        message=(
            "Đã huỷ phiên đăng nhập." if cancelled else "Phiên đã hết hạn hoặc không tồn tại."
        ),
    )


@router.post("/disconnect", response_model=ActionResultOut)
async def disconnect(session: SessionDep) -> ActionResultOut:
    """Ngắt kết nối Google — xoá **từng** auth-file.

    Bẫy B10: route của CLIProxy không có chế độ "xoá tất cả"; gọi thiếu `?name=`
    trả 400.
    """
    admin = CliProxyAdmin()
    try:
        removed = await admin.disconnect_all()
    finally:
        await admin.aclose()

    get_catalog().invalidate("antigravity")
    await audit.record(session, "llm.disconnect", target="antigravity", meta={"count": removed})
    return ActionResultOut(
        message=(
            f"Đã ngắt kết nối {removed} tài khoản."
            if removed
            else "Không có tài khoản nào đang kết nối."
        )
    )


# ---------------------------------------------------------------------------
# Cổng B — Google API Key
# ---------------------------------------------------------------------------
@router.get("/api-key", response_model=CredentialOut)
async def get_api_key(session: SessionDep) -> CredentialOut:
    """**Chỉ** `{is_set, hint}` — không có đường nào đọc lại key đã lưu."""
    return _credential_out(await credentials.describe(session, credentials.KIND_GOOGLE_API_KEY))


@router.put("/api-key", response_model=CredentialOut)
async def put_api_key(body: SaveApiKeyRequest, session: SessionDep) -> CredentialOut:
    """Xác thực key **trước khi** ghi DB, rồi mã hoá Fernet.

    Thứ tự này quan trọng: ghi trước rồi mới thử sẽ để lại một key sai trong DB
    mà UI vẫn hiện "đã lưu".

    Google báo key sai bằng **400** "API key not valid" chứ không phải 401
    (task.md D1.9) — `gemini_wire` đã ánh xạ về `GatewayAuthError`, và thân phản
    hồi đó **không** chứa key nên câu lỗi ra UI cũng không.
    """
    # Import tại chỗ: cổng B không được dùng ở các endpoint khác của router này.
    from app.llm.google_api_key import GoogleApiKeyGateway

    gateway = GoogleApiKeyGateway(body.api_key)
    try:
        await gateway.validate_key()
    finally:
        await gateway.aclose()

    info = await credentials.save_secret(session, credentials.KIND_GOOGLE_API_KEY, body.api_key)
    # Key mới có thể mở ra danh mục khác → cache cũ phải bỏ (task.md I-24).
    get_catalog().invalidate("google_api_key")
    await audit.record(session, "llm.save_api_key", target="google_api_key")
    return _credential_out(info)


@router.delete("/api-key", response_model=ActionResultOut)
async def delete_api_key(session: SessionDep) -> ActionResultOut:
    deleted = await credentials.delete_secret(session, credentials.KIND_GOOGLE_API_KEY)
    get_catalog().invalidate("google_api_key")
    if deleted:
        await audit.record(session, "llm.delete_api_key", target="google_api_key")
    return ActionResultOut(
        message="Đã xoá API key." if deleted else "Chưa có API key nào được lưu."
    )


# ---------------------------------------------------------------------------
# Cookie Facebook của chính người vận hành (task.md X.2)
# ---------------------------------------------------------------------------
#
# Vì sao cần: đo thật (task.md I-31, I-33) cho thấy Facebook **che caption và
# nội dung bài viết** với khách chưa đăng nhập — kể cả bài để chế độ Công khai.
# Không có cookie thì pipeline chỉ lấy được tên + ảnh.
#
# Vì sao nguy hiểm: cookie cho hệ thống đọc Facebook **dưới danh nghĩa tài khoản
# của người dùng**. Cảnh báo phải hiện **trước** khi họ dán, không phải sau.
@router.get("/fb-cookie", response_model=CookieStatusOut)
async def get_fb_cookie(session: SessionDep) -> CookieStatusOut:
    """Trạng thái cookie — **không** trả giá trị, chỉ mô tả."""
    info = await credentials.describe(session, credentials.KIND_FB_COOKIE)
    if not info.is_set:
        return CookieStatusOut(is_set=False, risk_warning=facebook_cookie.RISK_WARNING)

    raw = await credentials.get_secret(session, credentials.KIND_FB_COOKIE)
    parsed = facebook_cookie.validate(raw or "")
    return CookieStatusOut(
        is_set=True,
        masked_account=parsed.masked_account,
        names=list(parsed.names),
        created_at=info.created_at,
        risk_warning=facebook_cookie.RISK_WARNING,
    )


@router.put("/fb-cookie", response_model=CookieStatusOut)
async def put_fb_cookie(body: SaveCookieRequest, session: SessionDep) -> CookieStatusOut:
    """Kiểm hình dạng **rồi** ping Facebook, sau đó mới mã hoá và lưu.

    Thứ tự này quan trọng: lưu một cookie đã hết hạn rồi để pipeline chạy 70 giây
    và thất bại là kiểu lỗi tệ nhất — nó xảy ra khi không ai nhìn.
    """
    # Raise `CollectorError` (400) nêu rõ thiếu cookie nào nếu hình dạng sai.
    parsed = facebook_cookie.validate(body.cookie)
    normalised = facebook_cookie.to_header(body.cookie)
    alive = await facebook_cookie.check_alive(normalised)

    info = await credentials.save_secret(session, credentials.KIND_FB_COOKIE, normalised)
    # Log **tên** cookie, không bao giờ giá trị.
    await audit.record(session, "collector.save_fb_cookie", target=parsed.masked_account)

    return CookieStatusOut(
        is_set=True,
        masked_account=parsed.masked_account,
        names=list(parsed.names),
        created_at=info.created_at,
        risk_warning=facebook_cookie.RISK_WARNING,
        alive=alive,
    )


@router.delete("/fb-cookie", response_model=ActionResultOut)
async def delete_fb_cookie(session: SessionDep) -> ActionResultOut:
    deleted = await credentials.delete_secret(session, credentials.KIND_FB_COOKIE)
    if deleted:
        await audit.record(session, "collector.delete_fb_cookie")
    return ActionResultOut(
        message=(
            "Đã xoá cookie Facebook. Từ giờ hệ thống chỉ đọc được dữ liệu công khai."
            if deleted
            else "Chưa có cookie nào được lưu."
        )
    )


# ---------------------------------------------------------------------------
# Danh mục model (luật L6)
# ---------------------------------------------------------------------------
@router.get("/models", response_model=ModelListOut)
async def list_models(
    session: SessionDep,
    refresh: bool = Query(default=False, description="Bỏ qua cache 10 phút"),
) -> ModelListOut:
    """Danh mục **thật** của cổng đang chọn. Không có danh sách cứng ở đây."""
    config = await get_active_config(session)
    async with gateway_scope(session) as gateway:
        models = await get_catalog().list_models(gateway, refresh=refresh)
        provider = gateway.provider

    return ModelListOut(
        provider=provider,
        models=[_model_out(m) for m in models],
        selected=config.model or None,
    )


@router.put("/model", response_model=LlmStatusOut)
async def put_model(body: SetModelRequest, session: SessionDep) -> LlmStatusOut:
    """Chọn model — chỉ nhận model **có trong danh mục cổng đang chọn**.

    `catalog.find()` tự refetch một lần trước khi bỏ cuộc, để cache cũ không
    biến một model thật thành "không tồn tại". Không tìm thấy → 400 nêu rõ cả
    tên model lẫn tên cổng.
    """
    async with gateway_scope(session) as gateway:
        await get_catalog().find(gateway, body.model_id)

    await set_model(session, body.model_id)
    await audit.record(session, "llm.set_model", target=body.model_id)
    return await get_status(session)


@router.post(
    "/test",
    response_model=GatewayTestOut,
    dependencies=[Depends(llm_test_rate_limit.dependency)],
)
async def test_gateway(session: SessionDep) -> GatewayTestOut:
    """Gọi thật một prompt ngắn. Trả `{ok, latency_ms, model}` — **không** JSON thô.

    Endpoint này là **bắt buộc**, không phải tiện nghi (task.md I-15):
    `models.list` liệt kê cả model đã ngừng phục vụ — `gemini-2.5-flash` nằm
    trong danh mục cổng B nhưng `:generateContent` trả 404 "no longer available
    to new users". Chỉ một lần gọi thật mới phân biệt được.
    """
    config = await get_active_config(session)
    if not config.model:
        raise GatewayModelInvalid(
            "Chưa chọn model. Hãy chọn một model từ danh sách của cổng đang dùng "
            "rồi kiểm tra lại."
        )

    async with gateway_scope(session) as gateway:
        result = await _call_test_prompt(gateway, config.model, config.temperature)

    await audit.record(
        session,
        "llm.test",
        target=config.model,
        meta={"provider": result.provider, "latency_ms": result.latency_ms},
    )
    return result


async def _call_test_prompt(gateway: LLMGateway, model: str, temperature: float) -> GatewayTestOut:
    payload = gemini_wire.build_payload(
        [gemini_wire.text_part(TEST_PROMPT)],
        temperature=temperature,
        max_output_tokens=TEST_MAX_OUTPUT_TOKENS,
    )
    started = time.perf_counter()
    raw = await gateway.generate_content(payload, model=model)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # `extract_text` raise `GatewayBadResponse` nếu model bị SAFETY chặn / thiếu
    # candidates — đúng điều cần biết trước khi chạy pipeline thật.
    text = gemini_wire.extract_text(raw)
    finish = gemini_wire.extract_finish_reason(raw)

    note = f"Model đã trả lời ({len(text)} ký tự)."
    if finish == "MAX_TOKENS":
        # Gemini 3.x dùng thinking token trong cùng hạn mức (task.md I-16).
        note = (
            "Model trả lời nhưng bị cắt vì hết hạn mức token. Model này tiêu "
            "nhiều token để suy nghĩ — hãy tăng MAX_OUTPUT_TOKENS trước khi chạy thật."
        )

    return GatewayTestOut(
        ok=True,
        provider=gateway.provider,
        model=model,
        latency_ms=latency_ms,
        note=note,
    )


def _credential_out(info: credentials.CredentialInfo) -> CredentialOut:
    return CredentialOut(is_set=info.is_set, hint=info.hint, created_at=info.created_at)


def _model_out(model: ModelInfo) -> ModelOut:
    return ModelOut(
        id=model.id,
        display_name=model.display_name,
        supports_vision=model.supports_vision,
        input_token_limit=model.input_token_limit,
        output_token_limit=model.output_token_limit,
    )
