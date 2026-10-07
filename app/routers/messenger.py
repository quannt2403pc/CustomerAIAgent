"""`/api/messenger/*` — kết nối Facebook Page và nhận tin đến (task.md X.6).

Webhook là endpoint **công khai duy nhất** của hệ thống nhận dữ liệu từ bên
ngoài, nên nó được đối xử như vậy:

- Mọi POST phải qua `verify_signature` trước khi được đọc. Không có chữ ký hợp
  lệ = coi như tin giả. Thiếu bước này thì bất kỳ ai cũng bơm được "khách đã trả
  lời ABC" vào DB, và lượt gợi ý kế tiếp sẽ dựa trên dữ liệu bịa — hỏng L1.
- Sau khi chữ ký đã hợp lệ thì luôn trả **200**, kể cả khi xử lý bên trong lỗi.
  Facebook gửi lại webhook khi nhận mã 5xx, và gửi lại mãi thì thành vòng lặp.
  Lỗi xử lý đi vào log, không đi vào mã trạng thái.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings
from app.core.errors import MessengerDisabled
from app.core.logging import get_logger
from app.messenger import (
    InboundMessage,
    PageMessenger,
    SignatureInvalid,
    parse_inbound,
    verify_signature,
)
from app.routers.deps import SessionDep
from app.schemas.api import ActionResultOut, PageStatusOut, SavePageTokenRequest
from app.services import audit, credentials
from app.services.page_messenger import already_handled, build_messenger, conversation_for

log = get_logger(__name__)

router = APIRouter(prefix="/api/messenger", tags=["messenger"])

#: Đường dẫn người dùng phải dán vào Meta for Developers. Hằng số ở đây để
#: hướng dẫn trên UI và route thật không bao giờ lệch nhau.
WEBHOOK_PATH = "/api/messenger/webhook"


@router.get("/webhook")
async def verify_webhook(request: Request) -> Response:
    """Bước bắt tay một lần của Facebook khi người dùng lưu webhook.

    Facebook GET vào đây kèm `hub.verify_token`; ta phải dội lại `hub.challenge`
    **dạng text thuần**. Trả JSON thì Facebook coi là thất bại — đó là chỗ dễ
    mất thời gian nhất của cả quy trình cấu hình.
    """
    settings = get_settings()
    params = request.query_params
    expected = settings.messenger_verify_token.strip()
    supplied = (params.get("hub.verify_token") or "").strip()

    if not expected:
        log.warning("Webhook verify bị gọi nhưng MESSENGER_VERIFY_TOKEN chưa được đặt")
        return Response("Chưa cấu hình MESSENGER_VERIFY_TOKEN.", status_code=409)
    if params.get("hub.mode") != "subscribe" or supplied != expected:
        log.warning("Webhook verify bị từ chối: hub.mode hoặc verify_token không khớp")
        return Response("Verify token không khớp.", status_code=403)

    log.info("Webhook verify thành công")
    return Response(params.get("hub.challenge") or "", media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(request: Request, session: SessionDep) -> Response:
    """Nhận tin khách gửi → ghi vào hội thoại → sinh gợi ý lượt kế tiếp."""
    settings = get_settings()
    raw = await request.body()
    try:
        verify_signature(
            app_secret=settings.messenger_app_secret,
            raw_body=raw,
            header=request.headers.get("X-Hub-Signature-256"),
        )
    except SignatureInvalid as exc:
        # 403 ở đây đúng và **không** gây vòng lặp gửi lại: Facebook chỉ thử lại
        # với lỗi 5xx. Một 403 là tín hiệu cấu hình sai, cần người xem.
        log.warning("Webhook bị từ chối vì chữ ký không hợp lệ: %s", exc)
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except ValueError:
        log.warning("Webhook có chữ ký hợp lệ nhưng thân không phải JSON")
        return Response(status_code=status.HTTP_200_OK)

    for inbound in parse_inbound(payload):
        try:
            await _handle_one(session, inbound)
        except Exception:
            # Một tin lỗi không được chặn các tin còn lại, và tuyệt đối không
            # được thành 5xx — Facebook sẽ gửi lại cả lô mãi mãi.
            log.exception("Xử lý một tin đến thất bại; các tin còn lại vẫn tiếp tục")

    return Response(status_code=status.HTTP_200_OK)


async def _handle_one(session: SessionDep, inbound: InboundMessage) -> None:
    """Ghi một tin đến rồi sinh gợi ý lượt kế. Bỏ qua nếu đã xử lý rồi."""
    # Nhập khẩu tại chỗ: tránh vòng nhập khẩu router ↔ router. Hai module cần
    # nhau thật — `conversations` giữ logic sinh gợi ý, `messenger` giữ lối vào.
    from app.routers.conversations import (
        _append_message,
        _make_suggestions,
        _next_round,
        _profile_of,
    )

    if await already_handled(session, inbound.message_id):
        log.info("Bỏ qua tin đã xử lý trước đó (Facebook gửi lại)")
        return

    # Lấy tên là việc **phụ** và phải được đối xử như vậy: nếu nó hỏng (chưa có
    # token Page, token hết hạn, Graph API chập chờn) thì vẫn phải ghi tin.
    # Thứ tự cũ gọi `build_messenger` trước và để lỗi của nó thoát ra — nghĩa là
    # một tin **thật của khách** bị bỏ hẳn chỉ vì không tra được cái tên.
    display_name: str | None = None
    try:
        messenger = await build_messenger(session)
        display_name = await messenger.fetch_display_name(inbound.psid)
    except Exception:
        log.warning("Không tra được tên người gửi; vẫn ghi tin như bình thường")

    conversation = await conversation_for(session, inbound, display_name=display_name)

    await _append_message(
        session,
        conversation,
        role="customer",
        text=inbound.text,
        external_id=inbound.message_id,
    )
    profile = await _profile_of(session, conversation)
    next_round = await _next_round(session, conversation.id)
    await audit.record(session, "messenger.inbound", target=str(conversation.id))
    await _make_suggestions(session, conversation, profile, round_index=next_round)


# ---------------------------------------------------------------------------
# Cấu hình Page
# ---------------------------------------------------------------------------
@router.get("/status", response_model=PageStatusOut)
async def page_status(request: Request, session: SessionDep) -> PageStatusOut:
    """Trạng thái kết nối — **không** trả token, chỉ mô tả và lý do chưa dùng được."""
    settings = get_settings()
    info = await credentials.describe(session, credentials.KIND_PAGE_ACCESS_TOKEN)
    webhook_ready = bool(settings.messenger_app_secret and settings.messenger_verify_token)

    page_name: str | None = None
    if info.is_set:
        try:
            messenger = await build_messenger(session)
            page_name = await messenger.fetch_display_name("me")
        except MessengerDisabled:
            page_name = None

    return PageStatusOut(
        is_set=info.is_set,
        hint=info.hint,
        page_name=page_name,
        webhook_ready=webhook_ready,
        webhook_url=str(request.base_url).rstrip("/") + WEBHOOK_PATH,
        blocker=_blocker(is_set=info.is_set, page_name=page_name, webhook_ready=webhook_ready),
    )


def _blocker(*, is_set: bool, page_name: str | None, webhook_ready: bool) -> str:
    """Một câu nói **đúng việc còn thiếu**, không phải "chưa cấu hình" chung chung.

    Bốn trạng thái khác nhau cần bốn câu khác nhau; gộp lại thì người dùng đi
    sửa sai chỗ rồi tưởng hướng dẫn hỏng.
    """
    if not is_set:
        return "Chưa có Page Access Token. Làm bước 1–4 trong hướng dẫn bên dưới."
    if page_name is None:
        return (
            "Token đã lưu nhưng Facebook không nhận. Thường là token đã hết hạn, "
            "hoặc bạn dán token của User thay vì của Page — xem lại bước 4."
        )
    if not webhook_ready:
        return (
            "Gửi tin đã chạy được, nhưng chưa nhận phản hồi tự động: cần đặt "
            "MESSENGER_APP_SECRET và MESSENGER_VERIFY_TOKEN trong .env rồi khởi "
            "động lại API. Xem bước 5–7."
        )
    return ""


@router.put("/page-token", response_model=PageStatusOut)
async def put_page_token(
    body: SavePageTokenRequest, request: Request, session: SessionDep
) -> PageStatusOut:
    """Xác thực token với Facebook **trước** khi lưu.

    Lưu một token sai rồi để người dùng phát hiện lúc bấm Gửi là kiểu lỗi tệ
    nhất — nó xảy ra đúng lúc họ đang nói chuyện với khách thật.
    """
    settings = get_settings()
    probe = PageMessenger(
        page_access_token=body.token,
        base_url=settings.graph_api_base_url,
        api_version=settings.graph_api_version,
        timeout=settings.collector_timeout_seconds,
    )
    if await probe.fetch_display_name("me") is None:
        raise MessengerDisabled(
            "Facebook không nhận token này. Kiểm tra lại: phải là Page Access "
            "Token (không phải User token), và Page phải được chọn ở bước 4."
        )

    await credentials.save_secret(session, credentials.KIND_PAGE_ACCESS_TOKEN, body.token)
    await audit.record(session, "messenger.save_page_token")
    return await page_status(request, session)


@router.delete("/page-token", response_model=ActionResultOut)
async def delete_page_token(session: SessionDep) -> ActionResultOut:
    deleted = await credentials.delete_secret(session, credentials.KIND_PAGE_ACCESS_TOKEN)
    if deleted:
        await audit.record(session, "messenger.delete_page_token")
    return ActionResultOut(
        message=(
            "Đã ngắt kết nối Facebook Page. Gửi tự động tắt; các hội thoại cũ vẫn còn."
            if deleted
            else "Chưa có token nào để xoá."
        )
    )
