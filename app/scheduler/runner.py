"""Vòng đời APScheduler — lịch 20h sống qua restart (plan.md §5.5).

Bốn tham số không phải mặc định, mỗi cái vá một kiểu lỗi thật:

- **`jobstore` = Postgres** — lịch nằm trong RAM thì `docker compose restart` xoá
  sạch. DoD D2.4 đòi lịch còn sau restart.
- **`coalesce=True`** — máy tắt 5 tối rồi bật lại: không gộp thì APScheduler chạy
  **5 lượt liên tiếp** → 5 nháp cho mỗi khách trong một phút.
- **`misfire_grace_time=1800`** — máy bật lại lúc 20:20 vẫn nên chạy. Mặc định của
  APScheduler là 1 giây, tức là bỏ hẳn lượt đó mà không nói gì.
- **`max_instances=1`** — một lượt 20h có thể mất vài phút (mỗi hook 2–6 lượt gọi
  model). Lượt sau chồng lên lượt trước sẽ sinh nháp trùng.

Job được khai bằng **đường dẫn chuỗi** (`"app.scheduler.evening:run_evening_cadence"`),
không phải tham chiếu hàm: jobstore cần serialize được job, và pickle một hàm
đóng gói trong module sẽ vỡ ngay lần đổi tên đầu tiên.

Scheduler không lên được **không** làm API chết: người vận hành vẫn cần trang Cài
đặt và trang Phân tích. Nhưng im lặng cũng không được — `/health` phải nói ra
trạng thái thật, nếu không mốc 20h có thể chết hàng tuần mà không ai biết.
"""

from __future__ import annotations

from dataclasses import dataclass

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.core.logging import get_logger
from app.scheduler.evening import JOB_ID

log = get_logger(__name__)

EVENING_JOB_REF = "app.scheduler.evening:run_evening_cadence"
MISFIRE_GRACE_SECONDS = 1800

_scheduler: AsyncIOScheduler | None = None
_last_error: str = ""


@dataclass(frozen=True)
class SchedulerStatus:
    """Trạng thái thật để `/health` nói ra, không phải để đoán."""

    enabled: bool
    running: bool
    next_run_at: str | None = None
    cron: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "next_run_at": self.next_run_at,
            "cron": self.cron,
            "detail": self.detail,
        }


async def start() -> None:
    """Dựng scheduler và cài job 20h. Nuốt lỗi, ghi lại để `/health` báo."""
    global _scheduler, _last_error

    settings = get_settings()
    if not settings.scheduler_enabled:
        _last_error = "Đã tắt bằng SCHEDULER_ENABLED=false."
        log.info("Scheduler bị tắt theo cấu hình")
        return

    if _scheduler is not None and _scheduler.running:  # pragma: no cover
        return

    try:
        scheduler = AsyncIOScheduler(
            timezone=settings.tz,
            jobstores={
                # URL **đồng bộ**: APScheduler 3 dùng SQLAlchemy sync, truyền URL
                # async vào sẽ nổ lúc khởi động.
                "default": SQLAlchemyJobStore(url=settings.sync_database_url)
            },
            job_defaults={
                "coalesce": True,
                "misfire_grace_time": MISFIRE_GRACE_SECONDS,
                "max_instances": 1,
            },
        )
        scheduler.add_job(
            EVENING_JOB_REF,
            trigger=CronTrigger(
                hour=settings.evening_cron_hour,
                minute=settings.evening_cron_minute,
                timezone=settings.tz,
            ),
            id=JOB_ID,
            name="Sinh hook 20h vào outbox (nháp)",
            # `replace_existing`: jobstore đã giữ job từ lần chạy trước, không
            # thay thế thì mỗi lần khởi động lại là một `ConflictingIdError`.
            replace_existing=True,
        )
        scheduler.start()
        _scheduler = scheduler
        _last_error = ""
        log.info(
            "Scheduler đã chạy — lịch %02d:%02d %s, lượt kế tiếp %s",
            settings.evening_cron_hour,
            settings.evening_cron_minute,
            settings.tz,
            _next_run_text(scheduler),
        )
    except Exception as exc:
        _scheduler = None
        _last_error = f"Không dựng được scheduler ({type(exc).__name__})."
        # ERROR, không WARNING: mốc 20h là một deliverable của đề bài.
        log.error("Không dựng được scheduler", exc_info=True)


async def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
        log.info("Scheduler đã dừng")
    except Exception:
        log.warning("Lỗi khi dừng scheduler", exc_info=True)
    finally:
        _scheduler = None


def status() -> SchedulerStatus:
    settings = get_settings()
    cron = f"{settings.evening_cron_hour:02d}:{settings.evening_cron_minute:02d} {settings.tz}"

    if not settings.scheduler_enabled:
        return SchedulerStatus(
            enabled=False, running=False, cron=cron, detail="Đã tắt bằng SCHEDULER_ENABLED=false."
        )
    if _scheduler is None or not _scheduler.running:
        return SchedulerStatus(
            enabled=True,
            running=False,
            cron=cron,
            detail=_last_error or "Scheduler chưa khởi động.",
        )
    return SchedulerStatus(
        enabled=True, running=True, next_run_at=_next_run_text(_scheduler), cron=cron
    )


async def trigger_now() -> None:
    """Chạy lượt 20h **ngay**, không chờ cron.

    Dùng để kiểm chứng (task.md D2.4 DoD) và để người vận hành chạy lại khi lượt
    tối hôm trước bị bỏ. Vẫn đi qua đúng một đường code với lượt theo lịch — một
    đường "chạy tay" riêng là một đường chưa ai kiểm.
    """
    from app.scheduler.evening import run_evening_cadence

    await run_evening_cadence()


def _next_run_text(scheduler: AsyncIOScheduler) -> str | None:
    job = scheduler.get_job(JOB_ID)
    return job.next_run_time.isoformat() if job and job.next_run_time else None
