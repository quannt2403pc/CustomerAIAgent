"""X.3/X.4/X.5 — phiên hội thoại nhiều lượt.

Trọng tâm:

- Gợi ý **đọc được phản hồi của khách** (khác chuỗi 10 tin tĩnh).
- Gợi ý bẩn **không lọt ra** danh sách người vận hành thấy.
- Luật L3 (bản X.6): đường gửi chỉ tồn tại trong `app/messenger/`, và không có
  đường nào tự động hoá trình duyệt để DM profile cá nhân.
- X.5: không có caption thì prompt phải đẩy sang hướng hỏi mở bám ảnh.
"""

from __future__ import annotations

import pathlib

import pytest

from app.routers.conversations import profile_url_for
from app.services.conversation import (
    SuggestionRound,
    format_captions,
    format_history,
    generate_suggestions,
)
from app.services.validators import SalesHit, ZeroSalesReport
from tests.source_guards import (
    SANCTIONED_SEND_CALL,
    SEND_CALLERS_ALLOWED,
    browser_automation_offenders,
    send_call_sites,
    send_path_offenders,
    unexpected_messenger_mentions,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _production_sources() -> list[pathlib.Path]:
    """Mọi tệp chạy trong production. `tests/` loại ra — chính nó chứa các mẫu."""
    return [
        *sorted((REPO_ROOT / "app").rglob("*.py")),
        REPO_ROOT / "main.py",
        REPO_ROOT / "run.py",
    ]


def test_duong_gui_chi_ton_tai_trong_dung_mot_module() -> None:
    """Luật L3 bản X.6: gửi được, nhưng **chỉ** từ `app/messenger/`.

    Điều kiện "chỉ gửi cho người đã chủ động nhắn Page trước" chỉ thi hành được
    nếu có đúng một lối ra để kiểm. Một `httpx.post(.../messages)` mọc ở service
    khác sẽ đi vòng qua điều kiện đó mà không ai thấy — nên nó phải làm test
    này đỏ.
    """
    offenders = send_path_offenders(_production_sources(), root=REPO_ROOT)
    assert not offenders, "Đường gửi tin NGOÀI app/messenger/ — vi phạm L3:\n" + "\n".join(
        offenders
    )


def test_khong_tu_dong_hoa_trinh_duyet_de_dm_profile_ca_nhan() -> None:
    """Thứ vẫn bị cấm tuyệt đối, kể cả trong `app/messenger/`.

    Lái phiên `messenger.com` đã đăng nhập là cách duy nhất về mặt kỹ thuật để
    nhắn một profile bất kỳ, và là cách đã bị từ chối có lý do: vi phạm ToS,
    rủi ro khoá chính tài khoản người vận hành, và là nhắn hàng loạt cho người
    chưa hề đồng ý.

    Chỉ `app/routers/conversations.py` được dựng các URL đó, và chỉ để người
    vận hành **tự mở** trong trình duyệt của họ.
    """
    offenders = browser_automation_offenders(_production_sources(), root=REPO_ROOT)
    assert not offenders, (
        "Có URL giao diện Messenger ngoài chỗ dựng link thủ công đã duyệt:\n" + "\n".join(offenders)
    )


def test_moi_cho_nhac_messenger_deu_da_duoc_diem_danh() -> None:
    """Chữ "messenger" một mình không phải vi phạm, nhưng phải có chủ đích.

    `m.me` chỉ **mở** khung chat, không gửi. Nhưng nếu mai có ai thêm một
    `messenger_client.send(...)` thì tên đó sẽ **không** nằm trong danh sách
    đã điểm danh và test này đỏ — buộc người sửa phải giải trình.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        offenders += [f"{rel}:{hit}" for hit in unexpected_messenger_mentions(source, rel_path=rel)]

    assert not offenders, (
        "Có chỗ nhắc Messenger chưa được điểm danh trong "
        "ALLOWED_MESSENGER_IDENTIFIERS:\n" + "\n".join(offenders)
    )


def test_khong_co_vai_bot_trong_hoi_thoai() -> None:
    """Mọi tin gửi đi đều do con người bấm — không có vai `bot`/`system`."""
    from app.models import MESSAGE_ROLES

    assert set(MESSAGE_ROLES) == {"operator", "customer"}
    assert "bot" not in MESSAGE_ROLES
    assert "system" not in MESSAGE_ROLES


def test_chi_co_dung_mot_loi_ra_goi_duong_gui() -> None:
    """Ngoài `app/messenger/`, chỉ **một** tệp và **một** dòng được gọi `send_text`.

    Đây là phần quan trọng nhất của L3 bản X.6. Điều kiện "chỉ gửi cho người đã
    chủ động nhắn Page trước" được thi hành bằng một câu kiểm `psid` ngay trước
    lời gọi. Một lối ra thứ hai mọc ở chỗ khác sẽ **không** có câu kiểm đó, và
    sẽ không ai phát hiện — nên số lối ra phải được khẳng định, không chỉ được
    mong đợi.
    """
    sites = send_call_sites(_production_sources(), root=REPO_ROOT)
    assert set(sites) == set(SEND_CALLERS_ALLOWED), (
        f"Lối gọi đường gửi đã thay đổi. Cho phép: {sorted(SEND_CALLERS_ALLOWED)}; "
        f"thấy: {sorted(sites)}"
    )
    hits = sites["app/routers/conversations.py"]
    assert len(hits) == 1, f"Mong đúng 1 lời gọi, thấy {len(hits)}: {hits}"
    assert SANCTIONED_SEND_CALL in hits[0], hits[0]


def test_loi_goi_gui_duoc_chan_boi_cau_kiem_psid() -> None:
    """Lời gọi gửi phải nằm **sau** một câu kiểm `psid` trong cùng hàm.

    Test này đọc AST thay vì tin vào mắt người đọc: không có `psid` thì không
    có bằng chứng người nhận đã đồng ý, và cả luật L3 bản mới sụp.
    """
    import ast

    source = (REPO_ROOT / "app" / "routers" / "conversations.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_via_page"
    )
    # Bỏ docstring trước khi đo vị trí: docstring của hàm này **giải thích** câu
    # kiểm psid và có nhắc chữ `send_text`, nên tính cả nó thì `index()` tìm
    # thấy chữ trong lời giải thích chứ không phải lời gọi thật.
    statements = func.body
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    body = "\n".join(ast.unparse(node) for node in statements)

    check_at = body.index("if not conversation.psid")
    send_at = body.index("send_text")
    assert check_at < send_at, f"Câu kiểm psid phải đứng TRƯỚC lời gọi gửi.\n{body}"


# ---------------------------------------------------------------------------
# Link mở cuộc trò chuyện (task.md I-52 → I-58 → I-60)
# ---------------------------------------------------------------------------
#
# Ba lần sửa cho **cùng một cái link**, mỗi lần vì một phép đo thật. Giữ nguyên
# chuỗi này trong test vì mỗi dạng URL bị loại đều *trông* hợp lý hơn dạng đang
# dùng — không ghi lại lý do thì chắc chắn có người thêm lại.
#
#   m.me/<username>                   → chuyển sang messenger.com (I-52)
#   www.messenger.com/t/<id>          → trang đăng nhập, origin RIÊNG (I-52)
#   facebook.com/messages/t/<username>→ "Bạn hiện không xem được nội dung" (I-58)
#   facebook.com/messages/t/<id SỐ>   → **vẫn cùng lỗi đó** (I-60)
#
# Kết luận đo được: Facebook không còn URL điều hướng được tới chat cá nhân.
# Bấm "Nhắn tin" trên trang profile mở khung chat **ngay trong trang**, URL
# không đổi. Nên trang cá nhân là đích duy nhất.
@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.facebook.com/vander.374801", "https://www.facebook.com/vander.374801"),
        ("https://facebook.com/nguoidung/", "https://www.facebook.com/nguoidung"),
        ("https://m.facebook.com/nguoidung", "https://www.facebook.com/nguoidung"),
        (
            "https://www.facebook.com/profile.php?id=100012345678901",
            "https://www.facebook.com/profile.php?id=100012345678901",
        ),
        (
            "https://www.facebook.com/people/Unclee-Vander/61575076412503/",
            "https://www.facebook.com/profile.php?id=61575076412503",
        ),
    ],
)
def test_luon_mo_duoc_trang_ca_nhan(url, expected) -> None:
    assert profile_url_for(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        # Domain giả mạo phải bị loại — nếu không, ô nhập URL biến thành một
        # đường mở link tuỳ ý.
        "https://facebook.com.evil.test/nguoidung",
        "https://evil.test/facebook.com/nguoidung",
        "không-phải-url",
        "https://facebook.com",
        "https://facebook.com/",
    ],
)
def test_khong_dung_link_tu_url_khong_dang_tin(url) -> None:
    assert profile_url_for(url) is None


def test_khong_con_ham_nao_dung_link_khung_chat() -> None:
    """Ba dạng URL đã bị loại **không được** quay lại.

    Test này canh một thứ không tồn tại, nên trông thừa — nhưng cả ba dạng đều
    tiện hơn một cú bấm so với cách đang dùng, nên chúng rất dễ được thêm lại
    bởi người chưa trả giá ba lần như lần này.
    """
    import app.routers.conversations as module

    for ten in ("messenger_url_for", "messenger_alt_url_for"):
        assert not hasattr(module, ten), f"{ten} đã bị loại — xem task.md I-60"

    for url in ("https://www.facebook.com/nguoidung", "https://facebook.com/profile.php?id=123"):
        built = profile_url_for(url) or ""
        assert "m.me" not in built
        assert "messenger.com" not in built
        assert "/messages/t/" not in built


def test_boc_id_so_doi_hai_mau_phai_nhat_tri() -> None:
    """ID số vẫn được thu thập — làm **danh tính ổn định**, không phải để dựng link.

    Username đổi được, ID số thì không. Nhưng một mẫu đơn lẻ rất dễ bắt nhầm ID
    bài đăng/ảnh: đo thật trên trang `vander.374801` thấy cả `122098783778835880`
    và `284882215` (ID app Android) nằm cạnh ID người dùng thật. Nên canh gác là
    **đòi hai mẫu độc lập cho cùng một giá trị**, không phải regex chặt hơn.
    """
    from app.collectors.og_meta import extract_user_id

    assert extract_user_id('"userID":"61575076412503" fb://profile/61575076412503') == (
        "61575076412503"
    )
    assert extract_user_id('"userID":"111111111111" fb://profile/222222222222') is None
    assert extract_user_id('"userID":"61575076412503"') is None
    assert (
        extract_user_id('"userID":"111111111111" "userID":"333333333333" fb://profile/111111111111')
        is None
    )
    assert extract_user_id("khong co gi") is None


# ---------------------------------------------------------------------------
# X.5 — không có caption thì đẩy sang hỏi mở bám ảnh
# ---------------------------------------------------------------------------
def test_khong_co_caption_thi_prompt_noi_ro_phai_hoi_mo() -> None:
    """Đo thật I-31/I-33: Facebook che caption với khách chưa đăng nhập.

    Prompt phải **nói thẳng** điều đó, nếu không model sẽ bịa ra một caption.
    """
    text = format_captions([])
    assert "không đọc được" in text
    assert "MÔ TẢ ẢNH" in text
    assert "câu hỏi mở" in text


def test_co_caption_thi_dua_nguyen_van_vao_prompt() -> None:
    text = format_captions(["Đi xem MU ở Old Trafford", "Cuối tuần vui"])
    assert "Old Trafford" in text
    assert "Cuối tuần vui" in text


def test_prompt_co_vi_du_cau_hoi_mo_bam_anh() -> None:
    """Yêu cầu người dùng: ảnh không tiêu đề → hỏi "chụp ở đâu", "đi du lịch đâu"."""
    from app.prompts import load

    prompt = load("conversation_suggest")
    assert "chụp ở đâu" in prompt
    assert "đi đâu đó xa" in prompt or "đi chơi" in prompt
    # Và phải nhắc rằng câu hỏi vẫn phải neo vào ảnh, không được phỏng đoán.
    assert "không phải từ phỏng đoán" in prompt


# ---------------------------------------------------------------------------
# Lịch sử hội thoại đi vào prompt
# ---------------------------------------------------------------------------
def test_lich_su_dung_nhan_tieng_viet_va_moi_nhat_o_cuoi() -> None:
    text = format_history([("operator", "Chào bạn"), ("customer", "Chào bạn nhé")])
    assert text.index("BẠN: Chào bạn") < text.index("KHÁCH: Chào bạn nhé")
    assert "operator" not in text


def test_chua_co_luot_nao_thi_noi_ro_la_tin_mo_dau() -> None:
    assert "tin mở đầu" in format_history([])


def test_lich_su_dai_bi_cat_con_cua_so_gan_nhat() -> None:
    """Cuộc trò chuyện dài không được đốt token vô hạn."""
    from app.services.conversation import HISTORY_WINDOW

    many = [("operator", f"tin {i}") for i in range(100)]
    text = format_history(many)
    assert text.count("\n") + 1 == HISTORY_WINDOW
    assert "tin 99" in text  # giữ phần MỚI nhất
    assert "tin 0\n" not in text


# ---------------------------------------------------------------------------
# Sinh gợi ý — gợi ý bẩn không được lọt ra
# ---------------------------------------------------------------------------
class StubGateway:
    """Gateway giả trả về đúng những câu test muốn."""

    provider = "antigravity"

    def __init__(self, rounds: list[list[str]], judge: str = "NO") -> None:
        self._rounds = rounds
        self._judge = judge
        self.calls = 0

    async def generate_content(self, payload: dict, *, model: str) -> dict:
        self.calls += 1
        prompt = payload["contents"][0]["parts"][0]["text"]
        # Lớp LLM judge của ZeroSalesValidator dùng chung gateway này.
        if "YES" in prompt or "judge" in prompt.lower() or "bán hàng" in prompt:
            if "suggestions" not in prompt:
                body = f'{{"verdict": "{self._judge}", "reason": "test"}}'
                return {"candidates": [{"content": {"parts": [{"text": body}]}}]}
        batch = self._rounds.pop(0) if self._rounds else []
        import json

        body = json.dumps({"suggestions": batch}, ensure_ascii=False)
        return {"candidates": [{"content": {"parts": [{"text": body}]}}]}

    async def aclose(self) -> None:
        return None


EVIDENCE = "customer_name: Vander\nvisual_context: Ảnh một người trên sân cỏ đông khán giả."


@pytest.mark.asyncio
async def test_gui_y_sach_thi_tra_ve_het() -> None:
    clean = [
        "Chào Vander, nhìn bức ảnh sân cỏ đông vui ghê.",
        "Bức ảnh đó gợi cảm giác bạn thích không khí đông người.",
        "Hôm nay của bạn thế nào?",
    ]
    gateway = StubGateway([clean])
    result = await generate_suggestions(
        gateway,
        model="model-gia",
        evidence_corpus=EVIDENCE,
        visual_context="Ảnh một người trên sân cỏ.",
        captions=[],
        history=[],
    )
    assert result.passed
    assert len(result.suggestions) == 3


@pytest.mark.asyncio
async def test_cau_bia_du_kien_bi_loai_khoi_danh_sach() -> None:
    """Luật L1: câu nhắc "vợ" khi bằng chứng không có **không được** hiện ra."""
    batch = [
        "Chào Vander, nhìn bức ảnh sân cỏ vui ghê.",
        "Vợ bạn chắc cũng thích bóng đá nhỉ?",  # bịa — phải bị loại
        "Hôm nay của bạn thế nào?",
    ]
    gateway = StubGateway([batch])
    result = await generate_suggestions(
        gateway,
        model="model-gia",
        evidence_corpus=EVIDENCE,
        visual_context="Ảnh một người trên sân cỏ.",
        captions=[],
        history=[],
    )
    assert "Vợ bạn" not in " ".join(result.suggestions)
    assert len(result.suggestions) == 2


@pytest.mark.asyncio
async def test_khong_cau_nao_sach_thi_tra_danh_sach_rong_khong_tra_cau_ban() -> None:
    """Thà không có gợi ý còn hơn đưa câu chưa duyệt để người ta gửi đi (I-23)."""
    dirty = ["Bên mình có sản phẩm giá chỉ 299k, inbox nhé!"] * 3
    gateway = StubGateway([dirty, dirty, dirty])
    result = await generate_suggestions(
        gateway,
        model="model-gia",
        evidence_corpus=EVIDENCE,
        visual_context=None,
        captions=[],
        history=[],
    )
    assert result.suggestions == []
    assert result.passed is False
    # Và nội dung bẩn KHÔNG được nằm trong phần trả ra UI.
    assert "299k" not in " ".join(result.suggestions)


def test_llm_judge_bao_ban_hang_thi_bo_ca_lo() -> None:
    """Judge chấm **cả lô**: báo bẩn thì không nhặt lại câu nào.

    Trạng thái thật khi judge trả YES (xem `validate_zero_sales`): `judge_ran`
    thành **False** và một `SalesHit(seq=0)` được thêm — `seq = 0` nghĩa là
    "cả lô", không chỉ được câu nào.
    """
    from app.services.conversation import _keep_clean
    from app.services.validators import GroundingReport

    sales = ZeroSalesReport(
        hits=[SalesHit(seq=0, layer="llm_judge", pattern="có ý bán hàng", excerpt="…")],
        judge_ran=False,
        judge_reason="LLM judge cho rằng có ý bán hàng.",
    )
    assert sales.passed is False
    assert _keep_clean(["a", "b"], GroundingReport(), sales) == []


def test_lop_co_hoc_bat_duoc_thi_cung_bo_ca_lo_vi_judge_bi_bo_qua() -> None:
    """Hai lớp cơ học bắt được → judge **bị bỏ qua** (`judge_ran = False`).

    Nghĩa là những câu còn lại trong lô **chưa từng được judge chấm**. Nhặt
    chúng ra rồi hiện cho người vận hành là xác nhận một điều chưa ai kiểm —
    đúng kiểu rò mà luật L2 cấm. Phải sinh lại cả lô.
    """
    from app.services.conversation import _keep_clean
    from app.services.validators import GroundingReport

    sales = ZeroSalesReport(
        hits=[SalesHit(seq=2, layer="blocklist", pattern="giá", excerpt="giá chỉ 299k")],
        judge_ran=False,
        judge_reason="Bỏ qua LLM judge vì đã bị hai lớp cơ học bắt.",
    )
    assert _keep_clean(["câu một", "giá chỉ 299k", "câu ba"], GroundingReport(), sales) == []


def test_lo_sach_ve_ban_hang_thi_chi_loai_cau_bia_du_kien() -> None:
    """Grounding phán **từng câu** nên loại đúng câu bịa, giữ phần còn lại.

    Hợp lệ vì cả lô đã được judge chấm sạch — mọi câu trong đó đều sạch về
    chào bán.
    """
    from app.services.conversation import _keep_clean
    from app.services.validators import GroundingReport, UngroundedClaim

    sales = ZeroSalesReport(hits=[], judge_ran=True, judge_reason="sạch")
    assert sales.passed is True

    grounding = GroundingReport(
        ungrounded_claims=[UngroundedClaim(seq=2, kind="gia đình", term="vợ", excerpt="Vợ bạn…")]
    )
    clean = _keep_clean(["câu một", "Vợ bạn chắc thích lắm", "câu ba"], grounding, sales)
    assert clean == ["câu một", "câu ba"]


@pytest.mark.asyncio
async def test_gui_y_doc_duoc_phan_hoi_cua_khach() -> None:
    """Điểm cốt lõi của X.3: prompt lượt sau phải chứa câu khách vừa nói."""
    captured: list[str] = []

    class SpyGateway(StubGateway):
        async def generate_content(self, payload: dict, *, model: str) -> dict:
            captured.append(payload["contents"][0]["parts"][0]["text"])
            return await super().generate_content(payload, model=model)

    gateway = SpyGateway([["Mình cũng hay đi xem bóng lắm."]])
    await generate_suggestions(
        gateway,
        model="model-gia",
        evidence_corpus=EVIDENCE,
        visual_context="Ảnh sân cỏ.",
        captions=[],
        history=[("operator", "Chào bạn"), ("customer", "Mình vừa đi xem bóng về")],
    )
    assert any("Mình vừa đi xem bóng về" in prompt for prompt in captured)
    assert any("KHÁCH:" in prompt for prompt in captured)


def test_bao_cao_kiem_duyet_duoc_luu_de_truy_vet() -> None:
    round_result = SuggestionRound(suggestions=["x"], attempts=2, rejected=["lượt 1: bẩn"])
    report = round_result.report_for_db()
    assert report["attempts"] == 2
    assert report["rejected"] == ["lượt 1: bẩn"]


# ---------------------------------------------------------------------------
# Chế độ demo (task.md X.8)
# ---------------------------------------------------------------------------
def test_demo_khong_bao_gio_cham_duong_gui_that() -> None:
    """Ràng buộc quan trọng nhất của chế độ demo.

    Bật demo thì Send API **không được gọi**, kể cả khi hội thoại đủ điều kiện
    gửi tự động. Thiếu vế `&& !demoMode`, một buổi trình bày trước khách sẽ bắn
    tin thật cho người thật — đúng thứ chế độ này sinh ra để tránh.

    Kiểm ở **mã nguồn** vì đây là một dòng điều kiện duy nhất đứng giữa "trình
    bày an toàn" và "gửi nhầm cho khách hàng".
    """
    source = (REPO_ROOT / "web" / "src" / "pages" / "conversation.tsx").read_text(encoding="utf-8")

    assert (
        "const autoSend = conversation.can_send && !demoMode" in source
    ), "demo phải vô hiệu hoá đường gửi tự động"

    # Nhánh demo phải nằm TRƯỚC `window.open` — nếu sau, Facebook vẫn bị mở.
    assert source.index("if (demoMode) {") < source.index(
        "window.open("
    ), "nhánh demo phải chặn trước khi mở Facebook"


def test_tin_demo_duoc_danh_dau_trong_du_lieu_khong_chi_tren_giao_dien() -> None:
    """Bản ghi demo phải phân biệt được với bản ghi thật, **mãi mãi**.

    Nếu chỉ tô màu ở giao diện lúc đang bật demo thì sau buổi trình bày không ai
    còn biết tin nào đã thật sự gửi cho khách. Đó đúng là kiểu dữ liệu sai mà cả
    dự án này sinh ra để chống — nên dấu phải nằm trong DB.
    """
    from app.routers.conversations import DEMO_MARK

    assert DEMO_MARK == "demo:"

    source = (REPO_ROOT / "app" / "routers" / "conversations.py").read_text(encoding="utf-8")
    # Cả hai lối ghi (tin của mình và câu trả lời giả định) đều phải đánh dấu.
    assert source.count('f"{DEMO_MARK}{uuid.uuid4()}" if body.demo else None') == 2

    # Và `is_demo` phải suy ra từ chính cột đó, không phải từ cờ do FE gửi lên.
    assert "is_demo=bool(m.external_id and m.external_id.startswith(DEMO_MARK))" in source


def test_noi_tin_phai_khoa_hoi_thoai_truoc_khi_tinh_seq() -> None:
    """Chặn lại điều kiện đua đã gây HTTP 500 thật (task.md I-63).

    Trước khi sửa, `_append_message` đọc `max(seq)+1` rồi mới chèn. Hai request
    đồng thời cùng đọc ra `3`, cùng chèn `seq=3`, và cái thứ hai nổ
    `UniqueViolation` → 500. Chỉ cần một cú **bấm đúp** là tái hiện.

    Đọc AST thay vì tin vào mắt người đọc: thứ tự hai câu lệnh này là toàn bộ
    thứ ngăn cách giữa "ghi đúng" và "500 giữa buổi demo".
    """
    import ast

    source = (REPO_ROOT / "app" / "routers" / "conversations.py").read_text(encoding="utf-8")
    func = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_append_message"
    )
    statements = func.body
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
    ):
        statements = statements[1:]  # bỏ docstring — nó *giải thích* cả hai câu
    body = "\n".join(ast.unparse(node) for node in statements)

    assert "with_for_update()" in body, "thiếu khoá hàng hội thoại — điều kiện đua quay lại"
    assert body.index("with_for_update()") < body.index(
        "func.max(ConversationMessage.seq)"
    ), "phải khoá TRƯỚC khi tính seq, nếu không khoá chẳng bảo vệ được gì"


def test_ba_nguon_goc_tin_phan_biet_duoc_bang_external_id() -> None:
    """`external_id` mang đúng ba trạng thái, không chồng lấn nhau.

    - `mid.*`  → Facebook xác nhận đã gửi thật
    - `NULL`   → người vận hành tự gửi tay bên ngoài
    - `demo:*` → chưa từng gửi, chỉ để trình bày
    """
    from app.routers.conversations import DEMO_MARK

    assert not DEMO_MARK.startswith("mid")
    for real_id in ("mid.abc123", "mid.$xyz"):
        assert not real_id.startswith(DEMO_MARK)
