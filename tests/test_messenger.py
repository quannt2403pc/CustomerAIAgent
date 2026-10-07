"""X.6 — gửi/nhận tự động qua Facebook Page.

Trọng tâm không phải "gọi API có chạy không", mà là **điều kiện đồng ý có thật
sự được thi hành ở mọi lối** hay không:

- Không có `psid` → không gửi được, kể cả khi mọi thứ khác đã cấu hình xong.
- Webhook không có chữ ký hợp lệ → tin bị bỏ, không ghi vào DB.
- Tin dội lại của chính Page (`is_echo`) → không bị ghi như lời khách.
- Cùng một tin đến hai lần → chỉ xử lý một lần.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest
import respx

from app.core.errors import (
    MessengerDisabled,
    MessengerError,
    MessengerNotLinked,
    MessengerWindowExpired,
)
from app.messenger import PageMessenger, SignatureInvalid, parse_inbound, verify_signature

APP_SECRET = "bi-mat-chi-de-test"
BASE_URL = "https://graph.facebook.com"
API_VERSION = "v21.0"
SEND_URL = f"{BASE_URL}/{API_VERSION}/me/messages"


def _messenger(**kwargs) -> PageMessenger:
    return PageMessenger(
        page_access_token="token-test",
        base_url=BASE_URL,
        api_version=API_VERSION,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Điều kiện đồng ý — phần quan trọng nhất
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_khong_co_psid_thi_khong_gui_duoc() -> None:
    """`psid` là **bằng chứng người nhận đã chủ động nhắn Page**.

    Không có nó thì không được gửi. Đây là chỗ luật L3 bản X.6 thật sự được thi
    hành, nên nó phải chặn **trước** khi có bất kỳ lời gọi mạng nào — test dùng
    `respx` không khai route nào, nên mọi request đều sẽ nổ.
    """
    with respx.mock(assert_all_called=False):
        with pytest.raises(MessengerNotLinked):
            await _messenger().send_text(psid="", text="chào bạn")
        with pytest.raises(MessengerNotLinked):
            await _messenger().send_text(psid="   ", text="chào bạn")


def test_khong_co_token_thi_khong_dung_duoc_client() -> None:
    """Chưa kết nối Page → lỗi 409 nói rõ phải làm gì, không phải 502 mơ hồ."""
    with pytest.raises(MessengerDisabled) as exc:
        PageMessenger(page_access_token="  ", base_url=BASE_URL, api_version=API_VERSION)
    assert exc.value.http_status == 409
    assert "Cài đặt" in exc.value.message


# ---------------------------------------------------------------------------
# Gửi
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_gui_thanh_cong_tra_ve_message_id() -> None:
    """`message_id` là bằng chứng tin đã đi thật — phải trả về, không bỏ đi."""
    route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(200, json={"recipient_id": "psid-1", "message_id": "mid.abc"})
    )
    result = await _messenger().send_text(psid="psid-1", text="chào bạn")

    assert result == "mid.abc"
    body = json.loads(route.calls.last.request.content)
    assert body["recipient"]["id"] == "psid-1"
    assert body["message"]["text"] == "chào bạn"


@pytest.mark.asyncio
@respx.mock
async def test_dung_tag_human_agent_de_noi_rong_cua_so_tra_loi() -> None:
    """Cửa sổ mặc định chỉ 24h; `HUMAN_AGENT` nới thành 7 ngày.

    Hợp lệ ở đây vì điều kiện của tag là **người thật soạn và bấm gửi** — đúng
    những gì xảy ra: mọi tin đều do người vận hành chọn.
    """
    route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(200, json={"message_id": "mid.x"})
    )
    await _messenger(use_human_agent_tag=True).send_text(psid="psid-1", text="xin chào")

    body = json.loads(route.calls.last.request.content)
    assert body["messaging_type"] == "MESSAGE_TAG"
    assert body["tag"] == "HUMAN_AGENT"


@pytest.mark.asyncio
@respx.mock
async def test_khong_bat_tag_thi_gui_dang_response() -> None:
    route = respx.post(SEND_URL).mock(
        return_value=httpx.Response(200, json={"message_id": "mid.x"})
    )
    await _messenger(use_human_agent_tag=False).send_text(psid="psid-1", text="xin chào")

    body = json.loads(route.calls.last.request.content)
    assert body["messaging_type"] == "RESPONSE"
    assert "tag" not in body


@pytest.mark.asyncio
@respx.mock
async def test_thieu_message_id_la_loi_chu_khong_phai_thanh_cong() -> None:
    """200 mà không có `message_id` nghĩa là ta **không biết** tin có đi không.

    Coi đó là thành công sẽ ghi vào lịch sử một tin khách chưa hề nhận.
    """
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"recipient_id": "psid-1"}))
    with pytest.raises(MessengerError):
        await _messenger().send_text(psid="psid-1", text="xin chào")


# ---------------------------------------------------------------------------
# Dịch lỗi Graph API — mỗi nguyên nhân một hướng xử lý khác nhau
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_qua_cua_so_cho_phep_bao_dung_nguyen_nhan() -> None:
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 10, "error_subcode": 2018278, "message": "outside window"}}
        )
    )
    with pytest.raises(MessengerWindowExpired) as exc:
        await _messenger().send_text(psid="psid-1", text="xin chào")
    assert exc.value.http_status == 409
    assert "7 ngày" in exc.value.message


@pytest.mark.asyncio
@respx.mock
async def test_token_het_han_noi_ro_phai_dan_token_moi() -> None:
    """Mã 190 = token hỏng. Thử lại vô ích, nên phải nói đi sửa cấu hình."""
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(401, json={"error": {"code": 190, "message": "expired"}})
    )
    with pytest.raises(MessengerDisabled) as exc:
        await _messenger().send_text(psid="psid-1", text="xin chào")
    assert "token mới" in exc.value.message


@pytest.mark.asyncio
@respx.mock
async def test_psid_khong_thuoc_page_nay_bao_chua_lien_ket() -> None:
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": 100, "message": "No matching user found"}}
        )
    )
    with pytest.raises(MessengerNotLinked):
        await _messenger().send_text(psid="psid-la", text="xin chào")


@pytest.mark.asyncio
@respx.mock
async def test_khong_ro_fbtrace_id_ra_thong_diep_nguoi_dung_thay() -> None:
    """Thân lỗi Graph API chỉ được vào log, không vào `message` (L5, §7.3.6)."""
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            500, json={"error": {"code": 2, "message": "loi noi bo", "fbtrace_id": "AbCd1234"}}
        )
    )
    with pytest.raises(MessengerError) as exc:
        await _messenger().send_text(psid="psid-1", text="xin chào")

    assert "AbCd1234" not in exc.value.message
    assert "loi noi bo" not in exc.value.message
    # Nhưng vẫn phải truy vết được từ log server.
    assert "code=2" in (exc.value.detail or "")


@pytest.mark.asyncio
@respx.mock
async def test_mat_mang_khong_lam_vo_bang_stacktrace() -> None:
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectError("mất mạng"))
    with pytest.raises(MessengerError):
        await _messenger().send_text(psid="psid-1", text="xin chào")


# ---------------------------------------------------------------------------
# Lấy tên hiển thị — lỗi phải thành `None`, không được làm vỡ luồng nhận tin
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@respx.mock
async def test_lay_duoc_ten_thi_tra_ten() -> None:
    respx.get(f"{BASE_URL}/{API_VERSION}/psid-1").mock(
        return_value=httpx.Response(200, json={"name": "Nguyễn Văn A"})
    )
    assert await _messenger().fetch_display_name("psid-1") == "Nguyễn Văn A"


@pytest.mark.asyncio
@respx.mock
async def test_khong_lay_duoc_ten_thi_tra_none_khong_bia_nhan() -> None:
    """Một cái tên bịa trong ô "khách hàng" là đúng thứ luật L1 cấm.

    Và nó sẽ đi tiếp vào prompt ở lượt gợi ý sau, nên sai lan ra chứ không đứng
    một chỗ.
    """
    respx.get(f"{BASE_URL}/{API_VERSION}/psid-1").mock(
        return_value=httpx.Response(403, json={"error": {"code": 190}})
    )
    assert await _messenger().fetch_display_name("psid-1") is None


@pytest.mark.asyncio
@respx.mock
async def test_ten_rong_cung_la_none() -> None:
    respx.get(f"{BASE_URL}/{API_VERSION}/psid-1").mock(
        return_value=httpx.Response(200, json={"name": "   "})
    )
    assert await _messenger().fetch_display_name("psid-1") is None


# ---------------------------------------------------------------------------
# Chữ ký webhook — không có nó thì ai cũng bơm được "khách đã trả lời" vào DB
# ---------------------------------------------------------------------------
def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_chu_ky_dung_thi_qua() -> None:
    body = b'{"object":"page"}'
    verify_signature(app_secret=APP_SECRET, raw_body=body, header=_sign(body))


def test_chu_ky_sai_thi_tu_choi() -> None:
    body = b'{"object":"page"}'
    with pytest.raises(SignatureInvalid):
        verify_signature(app_secret=APP_SECRET, raw_body=body, header=_sign(body, "secret-khac"))


def test_than_bi_sua_thi_chu_ky_khong_con_khop() -> None:
    """Chữ ký ký trên **thân thô**, nên sửa một chữ là phát hiện ngay."""
    body = b'{"object":"page","text":"that"}'
    header = _sign(body)
    with pytest.raises(SignatureInvalid):
        verify_signature(
            app_secret=APP_SECRET, raw_body=b'{"object":"page","text":"gia"}', header=header
        )


@pytest.mark.parametrize("header", [None, "", "abc123", "sha1=abc", "sha256="])
def test_header_thieu_hoac_sai_dang_thi_tu_choi(header) -> None:
    with pytest.raises(SignatureInvalid):
        verify_signature(app_secret=APP_SECRET, raw_body=b"{}", header=header)


def test_chua_cau_hinh_app_secret_thi_tu_choi_het() -> None:
    """Không có secret thì **không thể** xác thực.

    Chấp nhận tin trong trạng thái đó còn tệ hơn từ chối: nó mở đúng lối cho
    bất kỳ ai bơm dữ liệu khách giả vào hệ thống.
    """
    body = b"{}"
    with pytest.raises(SignatureInvalid) as exc:
        verify_signature(app_secret="", raw_body=body, header=_sign(body))
    assert "MESSENGER_APP_SECRET" in str(exc.value)


# ---------------------------------------------------------------------------
# Bóc tách payload webhook
# ---------------------------------------------------------------------------
def _page_event(**message) -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "time": 1,
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1700000000000,
                        "message": message,
                    }
                ],
            }
        ],
    }


def test_boc_duoc_tin_van_ban_cua_nguoi_that() -> None:
    [msg] = parse_inbound(_page_event(mid="mid.1", text="mình mới đi Đà Lạt về"))
    assert msg.psid == "psid-1"
    assert msg.text == "mình mới đi Đà Lạt về"
    assert msg.message_id == "mid.1"
    assert msg.timestamp_ms == 1700000000000


def test_bo_qua_tin_doi_lai_cua_chinh_page() -> None:
    """`is_echo` là tin **ta vừa gửi** dội về.

    Không lọc thì mỗi tin ta gửi sẽ được ghi lại như một lượt "khách trả lời",
    và lượt gợi ý kế tiếp sẽ trả lời chính mình.
    """
    assert parse_inbound(_page_event(mid="mid.1", text="xin chào", is_echo=True)) == []


def test_bo_qua_tin_chi_co_anh_khong_co_chu() -> None:
    """Không có chữ thì không có gì đưa vào ngữ cảnh; bịa nội dung là vi phạm L1."""
    event = _page_event(mid="mid.1", attachments=[{"type": "image", "payload": {"url": "x"}}])
    assert parse_inbound(event) == []


def test_bo_qua_tin_chu_rong() -> None:
    assert parse_inbound(_page_event(mid="mid.1", text="   ")) == []


def test_bo_qua_su_kien_khong_phai_loi_khach_noi() -> None:
    """`delivery`/`read`/`postback` không phải lời khách."""
    for key in ("delivery", "read", "postback"):
        payload = {
            "object": "page",
            "entry": [{"messaging": [{"sender": {"id": "psid-1"}, key: {"watermark": 1}}]}],
        }
        assert parse_inbound(payload) == []


def test_bo_qua_payload_khong_phai_cua_page() -> None:
    assert parse_inbound({"object": "instagram", "entry": []}) == []


def test_payload_meo_mo_khong_lam_no() -> None:
    """Webhook là lối vào công khai — payload lạ phải trả rỗng, không ném."""
    for payload in ({}, {"object": "page"}, {"object": "page", "entry": None}):
        assert parse_inbound(payload) == []


def test_boc_nhieu_tin_trong_mot_lo() -> None:
    payload = {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {"sender": {"id": "a"}, "message": {"mid": "m1", "text": "một"}},
                    {"sender": {"id": "b"}, "message": {"mid": "m2", "text": "hai"}},
                ]
            }
        ],
    }
    assert [m.text for m in parse_inbound(payload)] == ["một", "hai"]


# ---------------------------------------------------------------------------
# Canh gác toàn repo phát hiện từ I-54
# ---------------------------------------------------------------------------
def test_khong_goi_logger_theo_kieu_structlog() -> None:
    """`get_logger` trả `logging.Logger` chuẩn — kwargs tuỳ ý làm nó ném.

    Đặt ở đây vì lỗi này lộ ra từ handler webhook, nhưng nó quét **toàn repo**:
    kiểu lỗi này âm thầm cho tới đúng lúc dòng log ấy chạy, nên nó không được
    phát hiện bởi lint hay type check. Lần đầu, nó biến mọi webhook sai chữ ký
    thành 500 thay vì 403 — và Facebook gửi lại khi nhận 5xx (task.md I-54).
    """
    import pathlib

    from tests.source_guards import logger_kwarg_offenders

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    offenders = logger_kwarg_offenders(sorted((repo_root / "app").rglob("*.py")), root=repo_root)
    assert not offenders, (
        "Lời gọi logger dùng kwarg mà `logging` không nhận (sẽ ném TypeError "
        "lúc chạy):\n" + "\n".join(offenders)
    )
