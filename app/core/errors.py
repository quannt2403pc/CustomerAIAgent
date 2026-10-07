"""Taxonomy lỗi — plan.md §5.1.5.

Mỗi lỗi mang 3 thứ: `code` ngắn (hiện được trên UI thay cho JSON thô — luật L5),
`http_status` để router trả đúng mã, và `message` **tiếng Việt hành động được**.

Nguyên tắc: lỗi "chưa cấu hình / hết phiên" (409) phải phân biệt rõ với lỗi
"gọi không được" (503). Nhập nhèm hai thứ này làm người vận hành đi sai hướng xử lý.
"""

from __future__ import annotations


class AppError(Exception):
    """Gốc của mọi lỗi có chủ đích trong app."""

    code = "E-APP-500"
    http_status = 500
    message = "Lỗi không xác định."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message = message or self.__class__.message
        # `detail` chỉ đi vào log server, KHÔNG trả ra response (plan.md §7.3.6).
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self) -> dict[str, str]:
        """Thân response chuẩn hoá — chỉ `code` + `message`, không stack trace."""
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Cổng model (LLM gateway)
# ---------------------------------------------------------------------------
class GatewayError(AppError):
    code = "E-LLM-500"
    http_status = 502
    message = "Lỗi cổng model."


class GatewayNotConfigured(GatewayError):
    code = "E-LLM-409-NOCONF"
    http_status = 409
    message = "Chưa chọn cổng model. Vào Cài đặt để đăng nhập Google hoặc nhập API key."


class GatewayNoCredential(GatewayError):
    code = "E-LLM-409-NOCRED"
    http_status = 409
    message = "Chưa có tài khoản Google nào được kết nối. Bấm Đăng nhập Google."


class GatewayAuthError(GatewayError):
    """401/403 — TUYỆT ĐỐI không retry (bẫy B3: sai key 5 lần → CLIProxy ban IP 30 phút)."""

    code = "E-LLM-409-AUTH"
    http_status = 409
    message = "Phiên đăng nhập hết hạn hoặc API key sai. Hãy kết nối lại."


class GatewayProviderBlocked(GatewayError):
    code = "E-LLM-409-BLOCKED"
    http_status = 409
    message = "Google đang chặn tài khoản này, cần xác thực lại phía Google."


class GatewayDisabled(GatewayError):
    """404 trên route quản trị — thường do `secret-key` để rỗng (bẫy B4)."""

    code = "E-LLM-409-DISABLED"
    http_status = 409
    message = (
        "Route quản trị của CLIProxy không bật. Thường do remote-management.secret-key "
        "để rỗng trong cliproxy/config.yaml — đặt khoá rồi khởi động lại cliproxy."
    )


class GatewayModelInvalid(GatewayError):
    code = "E-LLM-400-MODEL"
    http_status = 400
    message = "Model đang chọn không có trong cổng này. Hãy chọn lại từ danh sách."


class GatewayUnavailable(GatewayError):
    """Timeout / 5xx — khác hẳn 'chưa kết nối'."""

    code = "E-LLM-503"
    http_status = 503
    message = "Không gọi được cổng model, thử lại sau."


class GatewayRateLimited(GatewayError):
    code = "E-LLM-429"
    http_status = 429
    message = "Hết quota của cổng model, chờ ít phút rồi thử lại."


class GatewayBadResponse(GatewayError):
    """Model trả về cấu trúc không dùng được (thiếu candidates, bị SAFETY chặn…)."""

    code = "E-LLM-502-SHAPE"
    http_status = 502
    message = "Cổng model trả về nội dung không đọc được."


class GatewayCallbackRejected(GatewayBadResponse):
    """URL callback người dùng dán không dùng được — lỗi **đầu vào**, không phải lỗi cổng.

    Vì sao tách khỏi `GatewayBadResponse` (task.md I-36): nó mang `http_status`
    502, nghĩa là "cổng phía trên hỏng". Nhưng người dùng dán sai URL thì không
    có gì hỏng — họ cần sửa thao tác. UI nhận 502 sẽ hiện "hệ thống lỗi, thử lại
    sau" trong khi câu đúng là "dán lại URL". Kế thừa để mọi chỗ đang bắt
    `GatewayBadResponse` vẫn bắt được, chỉ `http_status` đổi thành 400.
    """

    code = "E-LLM-400-CALLBACK"
    http_status = 400
    message = "URL callback không dùng được. Hãy sao chép lại toàn bộ URL sau khi đồng ý ở Google."


# ---------------------------------------------------------------------------
# Collector Facebook
# ---------------------------------------------------------------------------
class CollectorError(AppError):
    code = "E-COL-500"
    http_status = 502
    message = "Lỗi thu thập dữ liệu."


class InvalidFacebookUrl(CollectorError):
    code = "E-COL-400-URL"
    http_status = 400
    message = "URL không phải trang Facebook hợp lệ."


class CollectorBlocked(CollectorError):
    """Login wall / 429 / chặn IP. KHÔNG phải lỗi hệ thống — là sự thật cần báo trung thực (L1)."""

    code = "E-COL-200-BLOCKED"
    http_status = 200
    message = "Facebook không cho đọc công khai trang này."


# ---------------------------------------------------------------------------
# Validator (luật thép L1/L2)
# ---------------------------------------------------------------------------
class ValidationFailed(AppError):
    code = "E-VAL-422"
    http_status = 422
    message = "Nội dung sinh ra không qua được kiểm duyệt."


class GroundingFailed(ValidationFailed):
    code = "E-VAL-422-GROUND"
    message = "Nội dung nhắc tới dữ kiện không có trong bằng chứng thu thập được."


class ZeroSalesFailed(ValidationFailed):
    code = "E-VAL-422-SALES"
    message = "Nội dung còn dấu hiệu chào bán — vi phạm luật 0% chào bán."


# ---------------------------------------------------------------------------
# Hạ tầng
# ---------------------------------------------------------------------------
class CryptoError(AppError):
    code = "E-SEC-500"
    http_status = 500
    message = "Lỗi mã hoá/giải mã dữ liệu đã lưu."


class NotFoundError(AppError):
    code = "E-APP-404"
    http_status = 404
    message = "Không tìm thấy bản ghi."


class ConflictError(AppError):
    code = "E-APP-409"
    http_status = 409
    message = "Trạng thái hiện tại không cho phép thao tác này."


# ---------------------------------------------------------------------------
# Facebook Page / Messenger (task.md X.6)
# ---------------------------------------------------------------------------
class MessengerError(AppError):
    code = "E-MSG-502"
    http_status = 502
    message = "Facebook không nhận tin. Thử lại sau ít phút."


class MessengerDisabled(MessengerError):
    """Chưa kết nối Page → không có đường gửi nào. 409, không phải 502."""

    code = "E-MSG-409-OFF"
    http_status = 409
    message = (
        "Chưa kết nối Facebook Page. Vào Cài đặt → Kết nối Facebook Page "
        "và làm theo hướng dẫn để bật gửi tự động."
    )


class MessengerNotLinked(MessengerError):
    """Hội thoại chưa có PSID.

    Không phải lỗi cấu hình mà là **giới hạn của nền tảng**: Messenger chỉ cho
    gửi tới người đã chủ động nhắn Page trước. Thông điệp phải nói đúng điều
    đó, nếu không người vận hành sẽ đi sửa cấu hình mãi mà không hiểu vì sao.
    """

    code = "E-MSG-409-NOLINK"
    http_status = 409
    message = (
        "Người này chưa từng nhắn tin cho Page của bạn, nên Facebook không cho "
        "gửi tin tới họ. Hãy mời họ nhắn Page trước (gửi link m.me của Page); "
        "ngay khi họ nhắn, hội thoại sẽ tự liên kết và nút Gửi hoạt động."
    )


class MessengerWindowExpired(MessengerError):
    """Quá cửa sổ cho phép → Facebook trả mã 10 / subcode 2018278."""

    code = "E-MSG-409-WINDOW"
    http_status = 409
    message = (
        "Đã quá thời hạn Facebook cho phép trả lời người này (7 ngày kể từ tin "
        "cuối của họ). Phải chờ họ nhắn lại mới gửi được."
    )
