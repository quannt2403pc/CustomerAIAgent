"""`/health` — luôn trả 200 kèm bức tranh thật của từng phụ thuộc.

Cố ý **không** trả 503 khi `db`/`gateway` chết: trang Cài đặt của UI phải mở
được để người vận hành nhìn thấy "Chưa kết nối" và đi sửa (task.md D1.2 DoD).
Health check trả lỗi làm orchestrator giết container, che mất đúng cái cần xem.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.db import engine as db_engine
from app.scheduler import runner as scheduler_runner

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    db_ok = await db_engine.ping()
    return {
        "status": "ok",
        "db": "ok" if db_ok else "unavailable",
        "provider": settings.llm_provider or None,  # None = chưa chọn cổng
        "model": settings.llm_model or None,
        "dry_run": settings.dry_run,  # luật L3 — luôn true ở bản này
        # Mốc 20h là một deliverable của đề bài: scheduler chết âm thầm thì
        # lịch có thể không chạy hàng tuần mà không ai biết (task.md D2.4).
        "scheduler": scheduler_runner.status().to_dict(),
    }
