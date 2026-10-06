"""Giới hạn tần suất giữa các lớp collector (plan.md §5.2).

1 request/giây là **ràng buộc đạo đức**, không phải tối ưu hiệu năng: chúng ta
đọc trang công khai của người thật, không được dồn tải lên Facebook và không
được hành xử như crawler.

Khoá chung theo host → ba lớp L1/L2/L3 cùng chạm `facebook.com` thì vẫn chỉ
1 req/s *tổng*, không phải 1 req/s *mỗi lớp*.
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse


class HostRateLimiter:
    """Chờ tối thiểu `min_interval` giây giữa hai request tới cùng một host."""

    def __init__(self, min_interval: float = 1.0, clock=time.monotonic, sleep=asyncio.sleep):
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str) -> float:
        """Chờ nếu cần. Trả về số giây đã chờ (0 nếu không phải chờ)."""
        host = _host_of(url)
        lock = self._locks.setdefault(host, asyncio.Lock())

        async with lock:
            now = self._clock()
            last = self._last.get(host)
            delay = 0.0
            if last is not None:
                elapsed = now - last
                if elapsed < self._min_interval:
                    delay = self._min_interval - elapsed
                    await self._sleep(delay)
            self._last[host] = self._clock()
            return delay

    def reset(self) -> None:
        self._last.clear()


def _host_of(url: str) -> str:
    """Gộp mọi subdomain Facebook về một khoá.

    `mbasic.facebook.com` và `www.facebook.com` là **cùng** một hệ thống phía
    sau; tính hạn mức riêng cho từng subdomain là tự lách luật của chính mình.
    """
    host = (urlparse(url).hostname or "").lower()
    for root in ("facebook.com", "fb.com", "fbcdn.net"):
        if host == root or host.endswith("." + root):
            return root
    return host
