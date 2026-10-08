"""`/api/conversations/*` — phiên trò chuyện nhiều lượt (task.md X.3, X.4).

**Luật L3 (bản đã sửa — task.md X.6):** chỉ được gửi tin cho người đã **chủ
động nhắn Page trước**. Điều kiện ấy do cấu trúc dữ liệu thi hành: `send` đòi
`conversation.psid`, và PSID chỉ xuất hiện khi webhook nhận được tin của chính
người đó. Không có đường nào tạo PSID từ một URL profile.

Hai vòng làm việc **song song**, tuỳ đã kết nối Page hay chưa:

    Đã kết nối Page (tự động)
      start → gợi ý lượt 1
      send(text)  → GỬI THẬT qua Send API, ghi lượt BẠN
      webhook     → khách trả lời → ghi lượt KHÁCH + sinh gợi ý lượt kế

    Chưa kết nối Page (thủ công — vẫn giữ để không mất đường lùi)
      record-sent(text) → ghi lượt BẠN (bạn tự gửi bên ngoài)
      reply(text)       → bạn chép phản hồi vào
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    GatewayModelInvalid,
    MessengerNotLinked,
    NotFoundError,
)
from app.core.logging import get_logger
from app.core.ratelimit import llm_test_rate_limit
from app.llm.resolver import get_active_config
from app.models import (
    Conversation,
    ConversationMessage,
    ConversationSuggestion,
    Profile,
    ProfileEvidence,
)
from app.routers.deps import SessionDep, gateway_scope
from app.schemas.api import (
    ActionResultOut,
    ConversationListOut,
    ConversationMessageOut,
    ConversationOut,
    ConversationSummaryOut,
    RecordReplyRequest,
    RecordSentRequest,
    SendMessageRequest,
    StartConversationRequest,
    SuggestionOut,
)
from app.services import audit, credentials
from app.services.conversation import generate_suggestions
from app.services.page_messenger import build_messenger

log = get_logger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

#: Tiền tố đánh dấu tin sinh ra ở **chế độ demo**, lưu vào
#: `conversation_messages.external_id`.
#:
#: Vì sao phải đánh dấu trong DB chứ không chỉ ở giao diện: nếu không, bản ghi
#: demo trông **y hệt** bản ghi thật. Sau buổi demo, không ai — kể cả người viết
#: ra nó — phân biệt được tin nào đã thật sự gửi cho khách. Đó đúng là kiểu dữ
#: liệu sai mà cả dự án này sinh ra để chống.
#:
#: Dùng lại cột `external_id` (đã có, nullable, UNIQUE) thay vì thêm cột mới: ba
#: giá trị của nó nói đúng ba nguồn gốc — `mid.*` là Facebook xác nhận đã gửi,
#: `NULL` là người vận hành tự gửi tay, `demo:*` là chưa từng gửi.
DEMO_MARK = "demo:"

#: Những khoá evidence mang **chữ của bài đăng**. Dùng để nạp phần "tiêu đề /
#: nội dung bài đăng" vào prompt (yêu cầu người dùng 2026-10-07, task.md X.5).
CAPTION_KEYS = ("post_text", "post_caption", "caption", "bio", "about")

#: Username Facebook: chữ, số, dấu chấm. `profile.php?id=...` không có username
#: nên không dựng được link `m.me` — khi đó trả `None` thay vì đoán.
_USERNAME = re.compile(r"^[A-Za-z0-9.]{3,}$")


def _username_from(facebook_url: str) -> str | None:
    """Bóc username khỏi URL profile. `None` khi không suy ra được."""
    try:
        parsed = urlparse(facebook_url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None

    segments = [part for part in parsed.path.split("/") if part]
    if not segments:
        return None

    candidate = segments[-1] if segments[0] in ("people", "profile.php") else segments[0]
    if candidate.endswith(".php") or not _USERNAME.match(candidate):
        return None
    return candidate


def _numeric_id_from(facebook_url: str) -> str | None:
    """Bóc **ID số** của người dùng khỏi URL. `None` khi URL chỉ có username.

    Hai dạng URL mang ID số:

        facebook.com/profile.php?id=100012345678901
        facebook.com/people/Ten-Nguoi/100012345678901

    Dùng để chuẩn hoá link trang cá nhân về dạng `profile.php?id=…`, tức dạng
    chính Facebook dùng cho những tài khoản không đặt username.
    """
    try:
        parsed = urlparse(facebook_url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None

    if parsed.path.rstrip("/").endswith("profile.php"):
        for key, value in parse_qsl(parsed.query):
            if key == "id" and value.isdigit():
                return value
        return None

    segments = [part for part in parsed.path.split("/") if part]
    if len(segments) >= 3 and segments[0] == "people" and segments[-1].isdigit():
        return segments[-1]
    return None


# ---------------------------------------------------------------------------
# Vì sao KHÔNG có hàm dựng link mở thẳng khung chat
# ---------------------------------------------------------------------------
#
# Đã thử ba dạng, **đo thật trên trình duyệt đã đăng nhập** (task.md I-60):
#
#   m.me/<username>                     → chuyển sang messenger.com
#   www.messenger.com/t/<id>            → trang đăng nhập (origin RIÊNG, I-52)
#   www.facebook.com/messages/t/<id>    → "Bạn hiện không xem được nội dung này"
#
# Dạng thứ ba hỏng **kể cả khi đã có đúng ID số** — tôi tưởng nguyên nhân là
# dùng username (I-58) nên đã bỏ công bóc ID số từ trang profile; có ID rồi vẫn
# cùng lỗi đó. Nguyên nhân thật: Facebook không còn phơi URL điều hướng được cho
# chat cá nhân. Bấm "Nhắn tin" trên trang profile mở một **khung chat ngay trong
# trang**, URL không hề đổi.
#
# Nên trang cá nhân không phải "đường lùi" — nó là đích **duy nhất** dùng được.
# Bài học trả giá ba lần cho cùng một link: **mở thử bằng phiên đăng nhập thật
# trước khi tin vào một URL**, curl và suy luận không thay được bước đó.


def profile_url_for(facebook_url: str) -> str | None:
    """Link **trang cá nhân** — đường lùi luôn mở được.

    Dùng khi không dựng được link khung chat. Người vận hành bấm "Nhắn tin"
    ngay trên trang đó; Facebook tự mở đúng cuộc trò chuyện mà ta không phải
    đoán ID của ai cả.

    Chỉ nhận URL đã xác minh là của facebook.com — trả lại nguyên văn URL người
    dùng nhập sẽ biến ô nhập thành một đường mở link tuỳ ý.
    """
    try:
        parsed = urlparse(facebook_url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if not (host == "facebook.com" or host.endswith(".facebook.com")):
        return None
    if not [part for part in parsed.path.split("/") if part]:
        return None

    numeric_id = _numeric_id_from(facebook_url)
    if numeric_id:
        return f"https://www.facebook.com/profile.php?id={numeric_id}"

    username = _username_from(facebook_url)
    return f"https://www.facebook.com/{username}" if username else None


# ---------------------------------------------------------------------------
# Phiên
# ---------------------------------------------------------------------------
@router.post("", response_model=ConversationOut, status_code=201)
async def start_conversation(
    body: StartConversationRequest, session: SessionDep
) -> ConversationOut:
    """Bắt đầu phiên làm việc và sinh gợi ý lượt đầu ngay."""
    profile = await _get_profile(session, uuid.UUID(body.profile_id))

    conversation = Conversation(profile_id=profile.id, status="active")
    session.add(conversation)
    await session.flush()

    await audit.record(session, "conversation.start", target=str(profile.id))
    await _make_suggestions(session, conversation, profile, round_index=1)
    return await _render(session, conversation, profile)


@router.get("", response_model=ConversationListOut)
async def list_conversations(session: SessionDep) -> ConversationListOut:
    stmt = (
        select(
            Conversation,
            Profile.customer_name,
            func.count(ConversationMessage.id),
            func.max(ConversationMessage.created_at),
        )
        # `outerjoin`, KHÔNG `join`: hội thoại đến từ webhook chưa có profile
        # (`profile_id IS NULL`), inner join sẽ làm chúng **mất khỏi danh sách**
        # — nghĩa là tin khách thật gửi tới mà người vận hành không hề thấy.
        .outerjoin(Profile, Profile.id == Conversation.profile_id)
        .outerjoin(ConversationMessage, ConversationMessage.conversation_id == Conversation.id)
        .group_by(Conversation.id, Profile.customer_name)
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    return ConversationListOut(
        items=[
            ConversationSummaryOut(
                id=str(conv.id),
                profile_id=str(conv.profile_id) if conv.profile_id else None,
                customer_name=name or conv.customer_label or "",
                status=conv.status,
                created_at=conv.created_at,
                message_count=count,
                last_message_at=last_at,
            )
            for conv, name, count, last_at in rows
        ],
        total=len(rows),
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationOut:
    conversation = await _get_conversation(session, conversation_id)
    profile = await _profile_of(session, conversation)
    return await _render(session, conversation, profile)


@router.post("/{conversation_id}/send", response_model=ConversationOut)
async def send_via_page(
    conversation_id: uuid.UUID, body: SendMessageRequest, session: SessionDep
) -> ConversationOut:
    """**Gửi thật** một tin qua Facebook Page (task.md X.6).

    Thứ tự ở đây quan trọng và không được đổi: **gửi trước, ghi sau**. Ghi trước
    rồi gửi thất bại sẽ để lại trong lịch sử một tin mà khách chưa bao giờ nhận
    — lượt gợi ý sau sẽ coi như đã nói điều đó rồi, và người vận hành thì tin là
    tin đã đi. Thà hỏng mà không ghi gì, còn hơn ghi một lịch sử sai.

    Không gửi được cho ai chưa nhắn Page trước: `conversation.psid` rỗng thì
    `send_text` ném `MessengerNotLinked` (409) kèm hướng dẫn cụ thể.
    """
    conversation = await _get_open_conversation(session, conversation_id)
    profile = await _profile_of(session, conversation)

    if not conversation.psid:
        raise MessengerNotLinked

    messenger = await build_messenger(session)
    message_id = await messenger.send_text(psid=conversation.psid, text=body.text)

    await _append_message(
        session, conversation, role="operator", text=body.text, external_id=message_id
    )
    if body.suggestion_id:
        suggestion = await session.get(ConversationSuggestion, uuid.UUID(body.suggestion_id))
        if suggestion is not None and suggestion.conversation_id == conversation.id:
            suggestion.chosen = True

    await audit.record(session, "conversation.send", target=str(conversation.id))
    return await _render(session, conversation, profile)


@router.post("/{conversation_id}/record-sent", response_model=ConversationOut)
async def record_sent(
    conversation_id: uuid.UUID, body: RecordSentRequest, session: SessionDep
) -> ConversationOut:
    """Ghi lại tin **bạn vừa tự gửi** trong Messenger.

    Không gửi gì (luật L3). Nếu tin đó đến từ một gợi ý, đánh dấu gợi ý ấy là
    `chosen` — về sau so được gợi ý nào hay được dùng.
    """
    conversation = await _get_open_conversation(session, conversation_id)
    profile = await _profile_of(session, conversation)

    await _append_message(
        session,
        conversation,
        role="operator",
        text=body.text,
        external_id=f"{DEMO_MARK}{uuid.uuid4()}" if body.demo else None,
    )

    if body.suggestion_id:
        suggestion = await session.get(ConversationSuggestion, uuid.UUID(body.suggestion_id))
        if suggestion is not None and suggestion.conversation_id == conversation.id:
            suggestion.chosen = True

    await audit.record(
        session,
        "conversation.sent_demo" if body.demo else "conversation.sent",
        target=str(conversation.id),
    )
    return await _render(session, conversation, profile)


@router.post(
    "/{conversation_id}/reply",
    response_model=ConversationOut,
    # Mỗi lượt gợi ý gọi model 2–6 lượt; dán phản hồi liên tục là tốn tiền thật.
    dependencies=[Depends(llm_test_rate_limit.dependency)],
)
async def record_reply(
    conversation_id: uuid.UUID, body: RecordReplyRequest, session: SessionDep
) -> ConversationOut:
    """Dán phản hồi của khách → ghi lại **và** sinh gợi ý lượt kế tiếp."""
    conversation = await _get_open_conversation(session, conversation_id)
    profile = await _profile_of(session, conversation)

    await _append_message(
        session,
        conversation,
        role="customer",
        text=body.text,
        external_id=f"{DEMO_MARK}{uuid.uuid4()}" if body.demo else None,
    )

    next_round = await _next_round(session, conversation.id)
    await audit.record(
        session,
        "conversation.reply_demo" if body.demo else "conversation.reply",
        target=str(conversation.id),
    )
    await _make_suggestions(session, conversation, profile, round_index=next_round)
    return await _render(session, conversation, profile)


@router.post("/{conversation_id}/close", response_model=ActionResultOut)
async def close_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ActionResultOut:
    conversation = await _get_open_conversation(session, conversation_id)
    conversation.status = "closed"
    conversation.closed_at = datetime.now(UTC)
    await audit.record(session, "conversation.close", target=str(conversation.id))
    return ActionResultOut(message="Đã đóng phiên hội thoại.")


# ---------------------------------------------------------------------------
# Trợ giúp
# ---------------------------------------------------------------------------
async def _make_suggestions(
    session: AsyncSession,
    conversation: Conversation,
    profile: Profile | None,
    *,
    round_index: int,
) -> None:
    """Sinh gợi ý cho một lượt rồi ghi vào DB. Gợi ý bẩn **không** được ghi."""
    config = await get_active_config(session)
    if not config.model:
        raise GatewayModelInvalid(
            "Chưa chọn cổng model hoặc chưa chọn model. Vào Cài đặt để chọn trước khi trò chuyện."
        )

    # Không có profile → không có evidence. Vẫn sinh gợi ý được, chỉ là dựa
    # **hoàn toàn** vào lịch sử trò chuyện. Đó là hành vi đúng: bịa evidence cho
    # một người ta chưa phân tích là vi phạm L1.
    bundle = await _latest_bundle(session, profile.id) if profile else None
    history = await _history(session, conversation.id)

    async with gateway_scope(session) as gateway:
        round_result = await generate_suggestions(
            gateway,
            model=config.model,
            evidence_corpus=bundle.evidence_corpus() if bundle else "",
            visual_context=profile.visual_context if profile else None,
            captions=_captions_from(bundle),
            history=history,
            temperature=config.temperature,
        )

    report = round_result.report_for_db()
    for seq, text in enumerate(round_result.suggestions, 1):
        session.add(
            ConversationSuggestion(
                conversation_id=conversation.id,
                round=round_index,
                seq=seq,
                text=text,
                report=report,
            )
        )
    await session.flush()


async def _render(
    session: AsyncSession, conversation: Conversation, profile: Profile | None
) -> ConversationOut:
    messages = (
        (
            await session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.seq)
            )
        )
        .scalars()
        .all()
    )

    latest_round = (
        await session.execute(
            select(func.max(ConversationSuggestion.round)).where(
                ConversationSuggestion.conversation_id == conversation.id
            )
        )
    ).scalar()

    suggestions: list[ConversationSuggestion] = []
    if latest_round:
        suggestions = list(
            (
                await session.execute(
                    select(ConversationSuggestion)
                    .where(
                        ConversationSuggestion.conversation_id == conversation.id,
                        ConversationSuggestion.round == latest_round,
                    )
                    .order_by(ConversationSuggestion.seq)
                )
            )
            .scalars()
            .all()
        )

    note = ""
    if not suggestions:
        # Nói thật vì sao trống, thay vì để người vận hành nhìn một danh sách rỗng
        # và tưởng hệ thống hỏng.
        note = (
            "Lượt này không có gợi ý nào qua được kiểm duyệt nên hệ thống không trả về câu nào. "
            "Bạn có thể tự viết tin ở ô bên dưới."
        )

    return ConversationOut(
        id=str(conversation.id),
        profile_id=str(conversation.profile_id) if conversation.profile_id else None,
        # Thứ tự: tên đã phân tích → tên thật lấy từ Graph API → rỗng.
        # Rỗng chứ không phải một nhãn bịa; FE nói rõ "chưa gán profile".
        customer_name=profile.customer_name if profile else (conversation.customer_label or ""),
        facebook_url=profile.facebook_url if profile else None,
        status=conversation.status,
        created_at=conversation.created_at,
        closed_at=conversation.closed_at,
        messages=[
            ConversationMessageOut(
                id=str(m.id),
                seq=m.seq,
                role=m.role,
                text=m.text,
                created_at=m.created_at,
                is_demo=bool(m.external_id and m.external_id.startswith(DEMO_MARK)),
            )
            for m in messages
        ],
        suggestions=[
            SuggestionOut(id=str(s.id), round=s.round, seq=s.seq, text=s.text, chosen=s.chosen)
            for s in suggestions
        ],
        suggestion_round=latest_round or 0,
        psid=conversation.psid,
        # `can_send` phải nghĩa là "bấm Gửi thì tin ĐI ĐƯỢC", không phải "người
        # này về nguyên tắc nhận được tin". Hai điều kiện, thiếu một là không:
        #
        #   - có `psid`  → Facebook cho phép gửi tới người này
        #   - có token   → ta thật sự gọi được Send API
        #
        # Chỉ xét `psid` (bản đầu) làm UI mời bấm "Gửi" trong khi chưa kết nối
        # Page — bấm xong nhận 409. Đo thật trên trình duyệt mới lộ ra.
        can_send=bool(conversation.psid) and await _page_connected(session),
        profile_url=profile_url_for(profile.facebook_url) if profile else None,
        suggestion_note=note,
    )


async def _append_message(
    session: AsyncSession,
    conversation: Conversation,
    *,
    role: str,
    text: str,
    external_id: str | None = None,
) -> None:
    """Nối một lượt vào cuối hội thoại, `seq` liên tục và không trùng.

    **Khoá hàng hội thoại trước khi tính `seq`** (task.md I-63, đo thật từ lỗi
    500 trong log). Trước đây đây là một tranh chấp đọc-rồi-ghi kinh điển:

        request A: SELECT max(seq)+1 → 3
        request B: SELECT max(seq)+1 → 3     (A chưa kịp ghi)
        request A: INSERT seq=3              ok
        request B: INSERT seq=3              → UniqueViolation → HTTP 500

    Xảy ra thật chỉ với một cú **bấm đúp** vào nút Gửi. Ràng buộc UNIQUE đã làm
    đúng việc của nó — chặn hai tin cùng số thứ tự — nhưng ứng dụng để lỗi tràn
    ra thành 500 thay vì xử lý.

    `FOR UPDATE` trên đúng **một hàng** `conversations` khiến các lần nối vào
    *cùng một hội thoại* xếp hàng, còn hội thoại khác nhau vẫn chạy song song.
    Chọn cách này thay vì bắt `IntegrityError` rồi thử lại: thử lại vẫn có thể
    trượt lần nữa, và nó biến một điều kiện đua thành một vòng lặp may rủi.
    """
    await session.execute(
        select(Conversation.id).where(Conversation.id == conversation.id).with_for_update()
    )

    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(ConversationMessage.seq), 0) + 1).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
    ).scalar_one()
    session.add(
        ConversationMessage(
            conversation_id=conversation.id,
            seq=next_seq,
            role=role,
            text=text.strip(),
            external_id=external_id,
        )
    )
    await session.flush()


async def _history(session: AsyncSession, conversation_id: uuid.UUID) -> list[tuple[str, str]]:
    rows = (
        await session.execute(
            select(ConversationMessage.role, ConversationMessage.text)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.seq)
        )
    ).all()
    return [(role, text) for role, text in rows]


async def _next_round(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    current = (
        await session.execute(
            select(func.coalesce(func.max(ConversationSuggestion.round), 0)).where(
                ConversationSuggestion.conversation_id == conversation_id
            )
        )
    ).scalar_one()
    return int(current) + 1


def _captions_from(bundle) -> list[str]:
    """Chữ của bài đăng đọc được — rỗng là bình thường (I-31/I-33)."""
    if bundle is None:
        return []
    return [field.value for field in bundle.fields if field.key in CAPTION_KEYS and field.value]


async def _latest_bundle(session: AsyncSession, profile_id: uuid.UUID):
    from app.collectors.evidence import EvidenceBundle

    row = (
        await session.execute(
            select(ProfileEvidence)
            .where(ProfileEvidence.profile_id == profile_id)
            .order_by(ProfileEvidence.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return EvidenceBundle.from_dict(row.bundle) if row and row.bundle else None


async def _page_connected(session: AsyncSession) -> bool:
    """Đã lưu Page Access Token chưa. Không đọc giá trị, chỉ hỏi có/không."""
    info = await credentials.describe(session, credentials.KIND_PAGE_ACCESS_TOKEN)
    return info.is_set


async def _get_profile(session: AsyncSession, profile_id: uuid.UUID) -> Profile:
    row = await session.get(Profile, profile_id)
    if row is None:
        raise NotFoundError("Không tìm thấy profile này.")
    return row


async def _profile_of(session: AsyncSession, conversation: Conversation) -> Profile | None:
    """Profile gắn với hội thoại, hoặc `None` nếu chưa gắn.

    Hội thoại sinh từ webhook không có profile: người đó nhắn Page trước khi ta
    kịp phân tích họ. Đòi profile ở đây sẽ làm mọi endpoint 404 trên đúng những
    hội thoại có tin thật.
    """
    if conversation.profile_id is None:
        return None
    return await _get_profile(session, conversation.profile_id)


async def _get_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    row = await session.get(Conversation, conversation_id)
    if row is None:
        raise NotFoundError("Không tìm thấy phiên hội thoại này.")
    return row


async def _get_open_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    row = await _get_conversation(session, conversation_id)
    if row.status != "active":
        raise ConflictError("Phiên hội thoại này đã đóng, không ghi thêm được nữa.")
    return row
