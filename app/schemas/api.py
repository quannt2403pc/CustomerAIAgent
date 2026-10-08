"""DTO của API (khác `app/schemas/output.py` — kia là strict JSON nộp bài).

Luật chung cho mọi model `*Out` ở đây: **không field nào mang secret**. Google
API key chỉ ra ngoài dưới dạng `hint` (`••••abcd`), không bao giờ plaintext
(plan.md §5.1.3). Và không model nào mang JSON thô của nhà cung cấp — tầng trên
chỉ nhận dữ liệu đã bóc tách (luật L5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderIn = Literal["antigravity", "google_api_key"]


class _Api(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Đầu vào
# ---------------------------------------------------------------------------
class SetProviderRequest(_Api):
    provider: ProviderIn


class SetModelRequest(_Api):
    model_id: str = Field(min_length=1, alias="model", serialization_alias="model")

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class SaveApiKeyRequest(_Api):
    # `min_length` nhỏ nhất có thể vẫn hữu ích: chặn chuỗi rỗng/vài ký tự dán
    # nhầm mà không giả định gì về **định dạng** key của Google (định dạng đổi
    # thì validate cứng sẽ chặn oan key thật).
    api_key: str = Field(min_length=8, max_length=512)


class OAuthCallbackRequest(_Api):
    """Đường dự phòng khi callback về `localhost:51121` thất bại (bẫy B1).

    UI chỉ có **một ô dán** — người dùng dán nguyên URL trên thanh địa chỉ.
    Backend tự bóc `code` vì CLIProxy nhận `{state, code}` chứ không nhận `url`
    (task.md I-08).
    """

    state: str = Field(min_length=1)
    url: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Đầu ra
# ---------------------------------------------------------------------------
class CredentialOut(_Api):
    """Mô tả credential — **chỉ** `is_set` + `hint`, đúng DoD D2.2."""

    is_set: bool
    hint: str = ""
    created_at: datetime | None = None


class ModelOut(_Api):
    id: str
    display_name: str = ""
    # `None` = **chưa biết** (cổng B không trả cờ vision — I-06). UI phải hiện
    # "chưa rõ" + cảnh báo, không được quy về False.
    supports_vision: bool | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None


class ModelListOut(_Api):
    provider: str
    models: list[ModelOut]
    selected: str | None = None
    # Nhắc UI rằng danh mục này **không** bảo đảm gọi được (task.md I-15):
    # `gemini-2.5-flash` có trong danh mục cổng B nhưng `:generateContent` trả 404.
    note: str = (
        "Danh mục này do cổng trả về lúc chạy. Có model nằm trong danh mục nhưng "
        "đã ngừng phục vụ — hãy bấm “Kiểm tra kết nối” trước khi chạy thật."
    )


class LlmStatusOut(_Api):
    """Mọi thứ trang Cài đặt cần để vẽ badge, không phải gọi thêm endpoint nào."""

    provider: str | None = None  # None = chưa chọn cổng (plan.md §12.2)
    model: str | None = None
    temperature: float
    max_output_tokens: int

    # `reachable` ≠ `connected`: cổng sống nhưng chưa đăng nhập thì người vận
    # hành cần bấm "Đăng nhập", không phải "thử lại sau" (plan.md §5.1.5).
    reachable: bool = False
    connected: bool = False
    account: str | None = None
    detail: str = ""
    latency_ms: int | None = None

    # Đổi cổng làm model cũ mất hiệu lực → UI buộc chọn lại, không đoán hộ.
    must_choose_model: bool = True
    api_key: CredentialOut


class OAuthStartOut(_Api):
    url: str
    state: str


class OAuthStatusOut(_Api):
    status: Literal["wait", "ok", "error"]
    # Câu tiếng Việt cho UI. `error` của CLIProxy là tiếng Anh kỹ thuật nên
    # không đưa thẳng ra; nó vào log server.
    message: str = ""
    connected: bool = False
    account: str | None = None


class GatewayTestOut(_Api):
    """Kết quả `POST /api/llm/test` — **không** chứa JSON thô của model (L5)."""

    ok: bool
    provider: str
    model: str
    latency_ms: int
    note: str = ""


class ActionResultOut(_Api):
    """Phản hồi cho các thao tác chỉ cần biết thành công/không."""

    ok: bool = True
    message: str = ""


# ---------------------------------------------------------------------------
# Profiles (D2.3)
# ---------------------------------------------------------------------------
class AnalyzeRequest(_Api):
    """Yêu cầu phân tích một trang Facebook công khai."""

    facebook_url: str | None = Field(default=None, max_length=2048)
    # Đường L4: người vận hành dán tay nội dung họ **tự** nhìn thấy. Dùng được
    # khi trang bị login wall (task.md I-14, I-22) hoặc khi không có mạng.
    profile_text: str | None = Field(default=None, max_length=20000)
    use_playwright: bool = False
    # Chạy lại một URL đã có: mặc định **không** chạy lại, trả bản ghi cũ. Mỗi
    # lần chạy tốn 7–14 lượt gọi model (task.md I-25) nên mặc định phải là rẻ.
    refresh: bool = False
    messages: int | None = Field(default=None, ge=5, le=10)


class StepOut(_Api):
    step: str
    label: str
    state: str
    note: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobOut(_Api):
    """Tiến trình một lần phân tích. `ok = None` nghĩa là **đang chạy**."""

    job_id: str
    job_name: str
    ok: bool | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    steps: list[StepOut] = Field(default_factory=list)
    profile_id: str | None = None
    status: str | None = None
    # Câu tiếng Việt khi job thất bại. Không bao giờ là stack trace (luật L5).
    error: str | None = None


class AnalyzeAcceptedOut(_Api):
    job_id: str | None = None
    profile_id: str | None = None
    # `reused = true`: URL này đã phân tích rồi và không yêu cầu làm mới → không
    # gọi model lần nào.
    reused: bool = False
    message: str = ""


class EvidenceFieldOut(_Api):
    key: str
    value: str | None = None
    source: str = ""
    evidence: str = ""
    confidence: float | None = None


class EvidenceImageOut(_Api):
    role: str = ""
    # Đường dẫn **nội bộ** đã chuẩn hoá (tên = sha256), không phải URL gốc của
    # Facebook — serve nguyên gốc là mời hotlink + rò referer.
    local_path: str | None = None
    sha256: str = ""


class EvidencePanelOut(_Api):
    """Panel bằng chứng của UI — trụ của luật L1: mỗi khẳng định phải truy vết được."""

    layers_used: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    screenshot_path: str | None = None
    fields: list[EvidenceFieldOut] = Field(default_factory=list)
    images: list[EvidenceImageOut] = Field(default_factory=list)


class ProfileSummaryOut(_Api):
    """Một dòng trong bảng Dashboard."""

    id: str
    facebook_url: str
    customer_name: str | None = None
    status: str
    created_at: datetime
    message_count: int = 0
    sales_check: str | None = None


class ProfileListOut(_Api):
    items: list[ProfileSummaryOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class ProfileDetailOut(_Api):
    """Kết quả đã render cho trang Phân tích."""

    id: str
    facebook_url: str
    status: str
    created_at: datetime
    customer_name: str | None = None
    visual_context: str | None = None
    demographics: dict[str, object] = Field(default_factory=dict)
    error_note: str | None = None

    core_empathy_angle: str | None = None
    messages: list[str] = Field(default_factory=list)
    sales_mention_check: str | None = None
    evening_hook_message: str | None = None
    trigger_time: str = "20:00"

    # Bản ghi có strict JSON lưu kèm hay không (task.md I-46).
    #
    # Cần thiết vì `messages = []` có **hai nghĩa trái ngược**: nội dung bị kiểm
    # duyệt loại (đúng, phải nói rõ), hay bản ghi tạo trước migration 0002 nên
    # không dựng lại được (chỉ là dữ liệu cũ). UI không thể phân biệt nếu thiếu
    # cờ này, và sẽ báo "0 tin nhắn" cho một lượt chạy thật sự có 10 tin.
    has_stored_output: bool = False

    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None

    evidence: EvidencePanelOut = Field(default_factory=EvidencePanelOut)
    job: JobOut | None = None


# ---------------------------------------------------------------------------
# Outbox (D2.4)
# ---------------------------------------------------------------------------
class OutboxItemOut(_Api):
    """Nháp hook 20h chờ người vận hành **tự gửi tay** (luật L3).

    Cố ý không có field nào mang nghĩa "đã gửi tự động": hệ thống không có đường
    gửi tin nào.
    """

    id: str
    profile_id: str
    customer_name: str | None = None
    facebook_url: str | None = None
    message: str | None = None
    status: str
    scheduled_for: datetime
    acted_at: datetime | None = None
    created_at: datetime


class OutboxListOut(_Api):
    items: list[OutboxItemOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0


class DashboardStatsOut(_Api):
    """KPI của Dashboard — đếm thật từ DB, không ước lượng."""

    profiles_total: int = 0
    profiles_success: int = 0
    profiles_partial: int = 0
    profiles_failed: int = 0
    # Tỉ lệ đọc được = (SUCCESS + PARTIAL) / tổng. `None` khi chưa có profile
    # nào — chia cho 0 rồi hiện "0%" là một lời nói sai.
    readable_rate: float | None = None
    hooks_waiting: int = 0
    messages_total: int = 0


# ---------------------------------------------------------------------------
# Hội thoại nhiều lượt (task.md X.3 / X.4)
# ---------------------------------------------------------------------------
class StartConversationRequest(_Api):
    profile_id: str


class SendMessageRequest(_Api):
    """Gửi **thật** một tin qua Facebook Page (task.md X.6).

    Khác `RecordSentRequest` ở chỗ: cái kia ghi lại việc đã xảy ra bên ngoài,
    cái này thật sự gọi Send API. Chỉ chạy được khi hội thoại có `psid`, tức
    người nhận đã chủ động nhắn Page trước.
    """

    text: str = Field(min_length=1, max_length=2000)
    #: Gợi ý nào đã được chọn (nếu có). Để trống nghĩa là người vận hành tự viết.
    suggestion_id: str | None = None


class PageStatusOut(_Api):
    """Trạng thái kết nối Facebook Page — **không** bao giờ chứa token."""

    is_set: bool = False
    #: Vài ký tự đầu/cuối của token, đủ để người dùng nhận ra mình dán đúng cái
    #: nào mà không lộ giá trị (luật L4).
    hint: str = ""
    #: Tên Page lấy thật từ Graph API. `None` = chưa xác thực được.
    page_name: str | None = None
    #: Đã đủ điều kiện nhận webhook chưa (cần cả App Secret + Verify Token).
    webhook_ready: bool = False
    #: Đường người dùng phải dán vào Meta for Developers.
    webhook_url: str = ""
    #: Lý do **cụ thể** vì sao chưa dùng được, rỗng nếu đã sẵn sàng.
    blocker: str = ""


class SavePageTokenRequest(_Api):
    token: str = Field(min_length=20, max_length=500)


class RecordSentRequest(_Api):
    """Ghi lại một tin **người vận hành đã tự gửi** ở Messenger.

    Đường **thủ công**, giữ lại cho trường hợp chưa kết nối Page. Tên `sent` mô
    tả *việc đã xảy ra*, không phải mệnh lệnh gửi. Muốn gửi thật thì dùng
    `SendMessageRequest`.
    """

    text: str = Field(min_length=1, max_length=2000)
    #: Gợi ý nào đã được chọn (nếu có). Để trống nghĩa là người vận hành tự viết.
    suggestion_id: str | None = None
    #: Chế độ demo: ghi lại **như thể** đã gửi, nhưng không có tin nào rời khỏi
    #: máy. Tin được đánh dấu trong DB để về sau không ai nhầm nó với tin thật.
    demo: bool = False


class RecordReplyRequest(_Api):
    """Dán phản hồi của khách vào.

    Không có webhook vì không có Facebook Page (xem task.md X.4): đường duy nhất
    để phản hồi vào hệ thống là người vận hành chép lại.
    """

    text: str = Field(min_length=1, max_length=4000)
    #: Chế độ demo — câu này do người trình bày tự nghĩ, không phải khách nói.
    demo: bool = False


class ConversationMessageOut(_Api):
    id: str
    seq: int
    role: str  # "operator" | "customer"
    text: str
    created_at: datetime
    #: Tin được tạo ở **chế độ demo** — không có tin thật nào đi hay đến.
    #: Giao diện phải hiện rõ điều này, nếu không bản ghi demo trông y hệt bản
    #: ghi thật và cả hệ thống mất tính trung thực.
    is_demo: bool = False


class SuggestionOut(_Api):
    id: str
    round: int
    seq: int
    text: str
    chosen: bool


class ConversationOut(_Api):
    """Một phiên hội thoại + lịch sử + gợi ý của lượt mới nhất."""

    id: str
    #: `None` khi hội thoại sinh từ webhook — người đó nhắn Page trước khi được
    #: phân tích, nên chưa có profile nào để trỏ tới.
    profile_id: str | None = None
    customer_name: str | None = None
    facebook_url: str | None = None
    status: str
    created_at: datetime
    closed_at: datetime | None = None

    messages: list[ConversationMessageOut] = Field(default_factory=list)
    suggestions: list[SuggestionOut] = Field(default_factory=list)
    suggestion_round: int = 0

    #: Link **trang cá nhân** — đích duy nhất dùng được cho đường thủ công.
    #: Người vận hành bấm "Nhắn tin" ở đó để mở khung chat.
    #:
    #: Không có `messenger_url`: Facebook không còn URL điều hướng được tới
    #: chat cá nhân — cả ba dạng đã thử đều hỏng (task.md I-60).
    profile_url: str | None = None

    #: Page-Scoped ID. Chỉ có khi người này đã **chủ động nhắn Page** — nên nó
    #: vừa là địa chỉ gửi, vừa là bằng chứng đồng ý (task.md X.6).
    psid: str | None = None
    #: `True` = gửi tự động được. FE dùng cờ này để chọn giữa nút "Gửi" thật và
    #: đường thủ công, thay vì tự đoán từ việc `psid` có rỗng hay không.
    can_send: bool = False

    #: Câu giải thích khi lượt gợi ý vừa rồi **không có câu nào sạch**.
    suggestion_note: str = ""


class ConversationSummaryOut(_Api):
    id: str
    profile_id: str | None = None
    customer_name: str | None = None
    status: str
    created_at: datetime
    message_count: int = 0
    last_message_at: datetime | None = None


class ConversationListOut(_Api):
    items: list[ConversationSummaryOut] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Cookie Facebook của chính người vận hành (task.md X.2)
# ---------------------------------------------------------------------------
class SaveCookieRequest(_Api):
    """Cookie của **chính bạn**, dán từ DevTools.

    Lưu Fernet trước khi ghi DB; không bao giờ trả lại qua API, không vào log
    (plan.md §5.2, §7.2).
    """

    cookie: str = Field(min_length=10, max_length=8000)


class CookieStatusOut(_Api):
    """Mô tả an toàn — **không** chứa giá trị cookie."""

    is_set: bool
    #: `100012345678901` → `••••8901`: đủ nhận ra, không đủ dùng lại.
    masked_account: str = ""
    #: Tên các cookie đã nhận (`c_user`, `xs`, …) — giá trị thì không.
    names: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    #: Cảnh báo rủi ro, hiện **trước** khi người dùng dán.
    risk_warning: str = ""
    #: Cookie còn đăng nhập được không (ping mbasic). `None` = chưa kiểm.
    alive: bool | None = None
