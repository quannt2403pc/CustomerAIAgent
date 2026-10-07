"""Rate limit trong tiến trình cho các endpoint **tốn tiền** (plan.md §7.4).

Vì sao cần: `POST /api/profiles` gọi model 7–14 lượt mỗi lần (task.md I-25) và
`POST /api/llm/test` gọi thật một lượt. Một cú F5 liên tục trên UI đủ để đốt hết
quota, hoặc tệ hơn — với cổng A thì CLIProxy coi đó là lạm dụng.

Vì sao **không** dùng Redis: app một người vận hành, một tiến trình `api`
(plan.md §12.1). Thêm một service chỉ để đếm request là phức tạp hoá không đổi
lấy gì. Đổi lại, giới hạn này **reset khi restart** — nói thật ở đây để sau này
không ai tưởng nó bền.

Thuật toán: sliding window đếm mốc thời gian, không phải token bucket. Với hạn
mức nhỏ (vài request/phút) thì danh sách mốc thời gian vừa chính xác hơn vừa dễ
đọc; token bucket chỉ đáng khi hạn mức lớn.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimited(AppError):
    """429 của **chính app ta**, khác `GatewayRateLimited` (429 của Google).

    Hai thứ này phải phân biệt được trên UI: một cái là "bạn bấm quá nhanh",
    cái kia là "hết quota của nhà cung cấp". Gộp lại thì người vận hành không
    biết nên chờ 10 giây hay 10 phút.
    """

    code = "E-APP-429"
    http_status = 429
    message = "Bạn đang gửi quá nhiều yêu cầu. Chờ ít giây rồi thử lại."


class SlidingWindowLimiter:
    """Đếm số lần gọi của mỗi khoá trong một cửa sổ thời gian trượt."""

    def __init__(self, *, limit: int, window_seconds: float, clock=time.monotonic):
        if limit < 1:
            raise ValueError("limit phải ≥ 1")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @property
    def limit(self) -> int:
        return self._limit

    def retry_after(self, key: str) -> int:
        """Số giây còn phải chờ, làm tròn lên. 0 nghĩa là gọi được ngay."""
        hits = self._hits[key]
        if len(hits) < self._limit:
            return 0
        remaining = self._window - (self._clock() - hits[0])
        return max(1, int(remaining + 0.999)) if remaining > 0 else 0

    def check(self, key: str) -> None:
        """Ghi nhận một lần gọi, hoặc raise `RateLimited`.

        Dọn mốc cũ **trước** khi đếm: không dọn thì danh sách phình vô hạn theo
        thời gian chạy của tiến trình.
        """
        now = self._clock()
        hits = self._hits[key]
        while hits and (now - hits[0]) >= self._window:
            hits.popleft()

        if len(hits) >= self._limit:
            wait = self.retry_after(key)
            log.warning("Chặn vì rate limit: khoá=%s, chờ %ds", key, wait)
            raise RateLimited(
                f"Bạn đang gửi quá nhiều yêu cầu ({self._limit} lần/"
                f"{int(self._window)}s). Chờ {wait} giây rồi thử lại."
            )

        hits.append(now)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


def client_key(request: Request) -> str:
    """Khoá giới hạn = IP client.

    Sau nginx thì mọi request đến từ IP container `web`, nên `X-Forwarded-For`
    (do nginx đặt) mới là IP thật. Chỉ đọc **phần tử đầu** — phần còn lại có thể
    do client tự bơm vào.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitDependency:
    """Hạn mức + dependency FastAPI đi kèm: `Depends(x.dependency)`.

    **Phải dùng `x.dependency`, không phải `Depends(x)`** (task.md I-37). Module
    này có `from __future__ import annotations`, nên mọi annotation là chuỗi.
    FastAPI phân giải chuỗi đó bằng `getattr(call, "__globals__", {})`; một
    *instance* không có `__globals__`, nên `"Request"` không phân giải được và
    FastAPI coi `request` là **query parameter bắt buộc**. Hậu quả đo được: mọi
    lần gọi endpoint trả 400 "thiếu tham số request", và hàm đếm **không bao giờ
    chạy** — hạn mức im lặng mất tác dụng. Hàm lồng thì có `__globals__` của
    module nên phân giải đúng.
    """

    def __init__(self, *, limit: int, window_seconds: float, name: str):
        self.name = name
        self.limiter = SlidingWindowLimiter(limit=limit, window_seconds=window_seconds)
        self.dependency = self._build_dependency()

    def _build_dependency(self):
        limiter, name = self.limiter, self.name

        async def enforce_rate_limit(request: Request) -> None:
            limiter.check(f"{name}:{client_key(request)}")

        return enforce_rate_limit

    def reset(self) -> None:
        self.limiter.reset()


# Hạn mức cố ý **chặt**: một người vận hành không thể phân tích 5 profile trong
# một phút bằng tay, nên vượt mức gần như luôn là lỗi (double-click, vòng lặp
# trong code FE). Dễ nới về sau; thiệt hại do nới quá rộng thì đã xảy ra rồi.
analyze_rate_limit = RateLimitDependency(limit=5, window_seconds=60.0, name="analyze")
llm_test_rate_limit = RateLimitDependency(limit=10, window_seconds=60.0, name="llm-test")
