"""Chạy một lần phân tích ở **nền** và theo dõi tiến trình (task.md D2.3).

Vì sao chạy nền: một lần phân tích gọi model 7–14 lượt và mất hàng chục giây
(đo thật D1.21: 70s). Giữ HTTP request mở suốt thời gian đó là mời timeout của
nginx/trình duyệt, và người vận hành không thấy gì đang diễn ra.

Thiết kế có chủ đích:

- **Session riêng cho job.** Session của request đóng ngay sau khi trả `job_id`;
  dùng tiếp là `IllegalStateError` hoặc tệ hơn — commit vào một transaction đã
  rollback.
- **Giữ tham chiếu task.** `asyncio.create_task` không giữ task sống; không giữ
  reference thì GC có thể thu dọn giữa đường và job biến mất **không để lại dấu**.
- **Không raise ra ngoài.** Job nền mà raise thì exception chỉ nằm trong
  `Task.exception()` — không ai đọc. Mọi lỗi phải thành `job_runs.ok = false` +
  `summary.error`, tức là thứ UI đọc được.

Luật L3: module này **không** có đường gửi tin nhắn. Nó chỉ sinh nháp.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.engine import get_sessionmaker
from app.llm.resolver import get_active_config, resolve_gateway
from app.models import JobRun
from app.services import audit, persistence
from app.services.evening_hook import fetch_recent_hooks
from app.services.pipeline import run_analysis
from app.services.progress import ProgressTracker, State, Step

log = get_logger(__name__)

JOB_ANALYZE = "analyze_profile"

# Giữ reference tới task đang chạy. Không có nó, GC có thể thu dọn task giữa
# đường (CPython chỉ giữ weak reference trong vòng lặp sự kiện).
_running: set[asyncio.Task] = set()


@dataclass
class JobHandle:
    """Thứ `POST /api/profiles` trả về."""

    job_id: uuid.UUID
    profile_id: uuid.UUID | None = None
    reused: bool = False
    message: str = ""
    steps: list[dict[str, object]] = field(default_factory=list)


async def create_job_row(
    session: AsyncSession,
    *,
    job_name: str,
    summary: dict[str, object],
) -> JobRun:
    """Tạo bản ghi job ở trạng thái *đang chạy* (`ok = NULL`).

    `ok` để NULL thay vì False: job chưa xong thì chưa biết kết quả — NULL nói
    đúng điều đó, `False` sẽ là một lời nói sai trong suốt 70 giây.
    """
    row = JobRun(job_name=job_name, summary=summary)
    session.add(row)
    await session.flush()
    return row


def start_analysis_job(
    job_id: uuid.UUID,
    *,
    url: str | None,
    profile_text: str | None,
    use_playwright: bool,
    n_messages: int | None,
) -> None:
    """Đẩy job vào vòng lặp sự kiện. Trả ngay, không chờ."""
    task = asyncio.create_task(
        _run_analysis_job(
            job_id,
            url=url,
            profile_text=profile_text,
            use_playwright=use_playwright,
            n_messages=n_messages,
        ),
        name=f"{JOB_ANALYZE}:{job_id}",
    )
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _run_analysis_job(
    job_id: uuid.UUID,
    *,
    url: str | None,
    profile_text: str | None,
    use_playwright: bool,
    n_messages: int | None,
) -> None:
    """Thân job. **Không bao giờ** để exception thoát ra ngoài."""
    settings = get_settings()
    tracker = ProgressTracker()

    async with get_sessionmaker()() as session:
        try:
            config = await get_active_config(session)
            cookie = await _facebook_cookie(session)
            recent = await _recent_hooks_for_url(session, url)
            gateway = await resolve_gateway(session)
            # Chốt transaction đọc **trước khi** chạy pipeline: giữ nó mở suốt 70
            # giây là giữ khoá và một connection của pool suốt 70 giây, trong khi
            # phần việc dài nhất không chạm DB.
            await session.commit()

            try:
                outcome = await run_analysis(
                    gateway=gateway,
                    model=config.model,
                    url=url,
                    profile_text=profile_text,
                    n_messages=n_messages,
                    temperature=config.temperature,
                    playwright_enabled=use_playwright,
                    facebook_cookie=cookie,
                    recent_hooks=recent,
                    upload_dir=settings.upload_dir,
                    progress=_ProgressToDb(job_id, tracker),
                )
            finally:
                await gateway.aclose()

            profile_id = await persistence.save_analysis(
                session, outcome, provider=config.provider, model=config.model
            )
            await _finish_job(
                session,
                job_id,
                ok=True,
                tracker=tracker,
                extra={
                    "profile_id": str(profile_id),
                    "status": outcome.output.status,
                    "url_key": outcome.bundle.url_key,
                },
            )
            await audit.record(
                session,
                "profile.analyzed",
                target=str(profile_id),
                meta={"status": outcome.output.status, "model": config.model},
            )
            await session.commit()
            log.info("Job %s xong: status=%s", job_id, outcome.output.status)

        except Exception as exc:
            await session.rollback()
            message = exc.message if isinstance(exc, AppError) else _generic_failure(exc)
            log.error("Job %s thất bại: %s", job_id, type(exc).__name__, exc_info=True)
            tracker.mark(_first_unfinished(tracker), State.FAILED, message)
            try:
                await _finish_job(
                    session, job_id, ok=False, tracker=tracker, extra={"error": message}
                )
                await session.commit()
            except Exception:  # pragma: no cover — DB chết thì không ghi được gì
                log.error("Không ghi được kết quả thất bại của job %s", job_id, exc_info=True)


class _ProgressToDb:
    """`ProgressSink` ghi tiến trình vào DB sau **mỗi** bước.

    Giữ trong RAM rồi ghi một lần ở cuối thì UI không thấy gì trong suốt 70 giây
    — đúng cái mà tiến trình sinh ra để tránh. Ghi ngay là 6 UPDATE cho một lần
    phân tích; đó là cái giá rẻ.

    **Mỗi lần ghi mở session riêng.** Dùng chung session với job là lỗi chờ xảy
    ra: `AsyncSession` không an toàn khi dùng đồng thời, và task ghi tiến trình
    chạy xen vào đúng lúc pipeline đang `await` một thứ khác → "concurrent
    operations are not permitted".

    `mark()` của `ProgressSink` là **đồng bộ** (pipeline không nên biết DB tồn
    tại), nên việc ghi được đẩy sang một task nền nhỏ.
    """

    def __init__(self, job_id: uuid.UUID, tracker: ProgressTracker):
        self._job_id = job_id
        self._tracker = tracker

    def mark(self, step: Step, state: State, note: str = "") -> None:
        self._tracker.mark(step, state, note)
        snapshot = self._tracker.to_list()
        task = asyncio.create_task(
            _write_steps(self._job_id, snapshot),
            name=f"progress:{self._job_id}:{step}",
        )
        _running.add(task)
        task.add_done_callback(_running.discard)


async def _write_steps(job_id: uuid.UUID, steps: list[dict[str, object]]) -> None:
    """Ghi tiến trình trong session riêng, nuốt lỗi.

    Tiến trình chỉ là thông tin hiển thị — nó hỏng **không được** làm hỏng job.
    """
    try:
        async with get_sessionmaker()() as session:
            row = await session.get(JobRun, job_id)
            if row is None:
                return
            row.summary = {**(row.summary or {}), "steps": steps}
            await session.commit()
    except Exception:
        log.warning("Không ghi được tiến trình của job %s", job_id)


async def _finish_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    ok: bool,
    tracker: ProgressTracker,
    extra: dict[str, object],
) -> None:
    row = await session.get(JobRun, job_id)
    if row is None:  # pragma: no cover
        return
    row.ok = ok
    row.finished_at = datetime.now(UTC)
    row.summary = {**(row.summary or {}), **extra, "steps": tracker.to_list()}
    await session.flush()


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> JobRun | None:
    return await session.get(JobRun, job_id)


async def latest_job_for_url_key(session: AsyncSession, url_key: str) -> JobRun | None:
    """Job gần nhất của một người — UI mở lại trang profile cần thấy tiến trình cũ."""
    stmt = (
        select(JobRun)
        .where(JobRun.job_name == JOB_ANALYZE, JobRun.summary["url_key"].astext == url_key)
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _first_unfinished(tracker: ProgressTracker) -> Step:
    """Bước đang dở khi lỗi xảy ra — để UI chỉ đúng chỗ gãy."""
    for step in Step:
        if tracker.steps[step].state in (State.RUNNING, State.PENDING):
            return step
    return Step.MODERATION


def _generic_failure(exc: Exception) -> str:
    """Câu tiếng Việt cho lỗi **không** thuộc taxonomy — không lộ chi tiết kỹ thuật."""
    return (
        "Lần phân tích này gặp lỗi không lường trước và đã dừng. "
        f"Xem log server (loại lỗi: {type(exc).__name__})."
    )


async def _facebook_cookie(session: AsyncSession) -> str | None:
    """Cookie của **chính người vận hành**, nếu họ đã tự cung cấp (task X.2)."""
    from app.services import credentials

    cookie = await credentials.get_secret(session, credentials.KIND_FB_COOKIE)
    return cookie or (get_settings().facebook_cookie or None)


async def _recent_hooks_for_url(session: AsyncSession, url: str | None) -> list[str]:
    """7 hook gần nhất của **đúng người này**, để hook mới không lặp ý (plan.md §5.5).

    URL mới thì chưa có profile nào → danh sách rỗng, không phải lỗi.
    """
    if not url:
        return []

    from app.collectors.url import normalize_facebook_url
    from app.core.errors import InvalidFacebookUrl
    from app.models import Profile

    try:
        url_key = normalize_facebook_url(url).url_key
    except InvalidFacebookUrl:
        # URL sai định dạng sẽ được `run_analysis` báo đúng cách; ở đây chỉ cần
        # không làm job chết trước khi tới đó.
        return []

    profile_id = (
        await session.execute(select(Profile.id).where(Profile.url_key == url_key))
    ).scalar_one_or_none()
    if profile_id is None:
        return []
    return await fetch_recent_hooks(session, profile_id)
