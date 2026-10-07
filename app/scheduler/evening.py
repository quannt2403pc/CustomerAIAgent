"""Job 20h — sinh hook mồi mới cho từng profile, đẩy vào `outbox` dạng **nháp**.

**Luật thép L3 ở đúng chỗ dễ vi phạm nhất.** Đây là nơi duy nhất trong hệ thống
chạy tự động theo giờ, nên nó cũng là nơi một dòng "gửi luôn cho tiện" dễ lọt
vào nhất. Module này:

- không import bất kỳ client Messenger / Graph API nào;
- không có tham số nào tên là `send`, `recipient`, `to`;
- kết thúc bằng `outbox(status='draft')` và dừng tại đó.

Có test grep toàn repo canh gác điều này (`tests/test_scheduler_outbox.py`).

Vì sao hook được **sinh mới** mỗi tối thay vì lấy lại hook cũ: đề bài yêu cầu
"câu chuyện mồi" dựa trên dữ liệu thật của khách, và gửi lại đúng một câu mỗi
tối là cách nhanh nhất để người nhận thấy đây là bot. Hook mới được so với 7 hook
gần nhất (plan.md §5.5) để không lặp ý.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.evidence import EvidenceBundle
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.engine import get_sessionmaker
from app.llm.resolver import get_active_config, resolve_gateway
from app.models import EveningHook, JobRun, OutboxItem, Profile, ProfileEvidence
from app.services import audit
from app.services.evening_hook import fetch_recent_hooks, generate_evening_hook
from app.services.profiler import Demographics, ProfileResult

log = get_logger(__name__)

JOB_EVENING = "evening_cadence_20pm"
JOB_ID = "evening-cadence-20pm"

# Chỉ những profile **đọc được gì đó** mới có hook có căn cứ. `FAILED_VALIDATION`
# và `ERROR` bị loại: sinh hook từ một profile chưa bao giờ đọc được dữ kiện nào
# là mời model bịa (luật L1).
ACTIVE_STATUSES = ("SUCCESS", "PARTIAL_OR_PRIVATE")


@dataclass
class EveningRunSummary:
    """Kết quả một lượt 20h — ghi vào `job_runs.summary`."""

    considered: int = 0
    drafted: int = 0
    skipped_existing: int = 0
    rejected_by_validators: int = 0
    failed: int = 0
    details: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "drafted": self.drafted,
            "skipped_existing": self.skipped_existing,
            "rejected_by_validators": self.rejected_by_validators,
            "failed": self.failed,
            "details": self.details,
        }


def scheduled_moment(now: datetime | None = None) -> datetime:
    """Mốc 20:00 **theo giờ Việt Nam** của ngày đang chạy.

    Không dùng `now` trực tiếp làm `scheduled_for`: job chạy bù (misfire) lúc
    20:17 vẫn phải mang nhãn "nháp của mốc 20:00 hôm nay", nếu không trang Outbox
    sẽ hiện hai mốc khác nhau cho cùng một tối.
    """
    settings = get_settings()
    tz = ZoneInfo(settings.tz)
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    at = time(hour=settings.evening_cron_hour, minute=settings.evening_cron_minute)
    return datetime.combine(local_now.date(), at).replace(tzinfo=tz)


async def run_evening_cadence() -> EveningRunSummary:
    """Điểm vào của APScheduler. **Không bao giờ** raise ra ngoài.

    Job raise thì APScheduler chỉ ghi một dòng log rồi đi tiếp — không ai đọc.
    Mọi thất bại phải thành `job_runs.ok = false` + `summary`, tức là thứ trang
    Nhật ký đọc được.
    """
    summary = EveningRunSummary()
    async with get_sessionmaker()() as session:
        run = JobRun(job_name=JOB_EVENING)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    ok = True
    try:
        summary = await _generate_drafts()
    except Exception as exc:
        ok = False
        message = exc.message if isinstance(exc, AppError) else type(exc).__name__
        summary.failed += 1
        summary.details.append({"error": message})
        log.error("Lượt 20h thất bại: %s", type(exc).__name__, exc_info=True)

    async with get_sessionmaker()() as session:
        row = await session.get(JobRun, run_id)
        if row is not None:
            row.ok = ok and summary.failed == 0
            row.finished_at = datetime.now(UTC)
            row.summary = summary.to_dict()
        await session.commit()

    log.info(
        "Lượt 20h xong: xét %d, nháp %d, bỏ qua %d, bị kiểm duyệt loại %d, lỗi %d",
        summary.considered,
        summary.drafted,
        summary.skipped_existing,
        summary.rejected_by_validators,
        summary.failed,
    )
    return summary


async def _generate_drafts() -> EveningRunSummary:
    settings = get_settings()
    summary = EveningRunSummary()
    moment = scheduled_moment()

    async with get_sessionmaker()() as session:
        config = await get_active_config(session)
        if not config.provider or not config.model:
            # Nói thật thay vì ghi `ok = true` cho một lượt không làm gì.
            raise AppError(
                "Lịch 20h không chạy được vì chưa chọn cổng model hoặc chưa chọn model. "
                "Vào Cài đặt để chọn."
            )

        profiles = await _active_profiles(session, limit=settings.evening_max_profiles)
        summary.considered = len(profiles)
        gateway = await resolve_gateway(session)

    try:
        for profile_row in profiles:
            async with get_sessionmaker()() as session:
                try:
                    await _draft_for_profile(
                        session,
                        profile_row,
                        gateway=gateway,
                        model=config.model,
                        temperature=config.temperature,
                        moment=moment,
                        summary=summary,
                    )
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    summary.failed += 1
                    summary.details.append(
                        {
                            "profile_id": str(profile_row.id),
                            "result": "failed",
                            "reason": (
                                exc.message if isinstance(exc, AppError) else type(exc).__name__
                            ),
                        }
                    )
                    log.error("Hook 20h cho profile %s thất bại", profile_row.id, exc_info=True)
    finally:
        await gateway.aclose()

    return summary


async def _draft_for_profile(
    session: AsyncSession,
    profile_row: Profile,
    *,
    gateway,
    model: str,
    temperature: float,
    moment: datetime,
    summary: EveningRunSummary,
) -> None:
    # Chạy hai lần trong cùng một tối (chạy bù, hoặc người vận hành bấm tay) không
    # được tạo hai nháp cho cùng một người — trang Outbox sẽ thành danh sách trùng.
    if await _draft_exists(session, profile_row.id, moment):
        summary.skipped_existing += 1
        summary.details.append({"profile_id": str(profile_row.id), "result": "skipped_existing"})
        return

    bundle = await _latest_bundle(session, profile_row.id)
    profile = _profile_result_from_row(profile_row)
    recent = await fetch_recent_hooks(session, profile_row.id)

    result = await generate_evening_hook(
        profile,
        bundle.evidence_corpus() if bundle else "",
        gateway,
        model=model,
        recent_hooks=recent,
        temperature=temperature,
    )

    if not result.passed or not result.message:
        # Hết lượt mà vẫn chưa sạch → **không** đẩy gì vào outbox. Một nháp "chưa
        # duyệt" nằm cạnh các nháp đã duyệt là mời người vận hành copy nó đi gửi.
        summary.rejected_by_validators += 1
        summary.details.append(
            {
                "profile_id": str(profile_row.id),
                "result": "rejected",
                # Chỉ nêu **số lượt**, không trích nguyên văn câu vi phạm (I-23).
                "attempts": result.attempts,
            }
        )
        return

    hook = EveningHook(
        profile_id=profile_row.id,
        message=result.message,
        # Truy vết: hook này dựa vào bằng chứng nào, qua kiểm duyệt ở lượt mấy.
        based_on=result.report_for_db(),
    )
    session.add(hook)
    await session.flush()

    session.add(
        OutboxItem(
            profile_id=profile_row.id,
            hook_id=hook.id,
            status="draft",  # luật L3 — chỉ có nháp, không có đường gửi
            scheduled_for=moment,
        )
    )
    await audit.record(
        session,
        "outbox.drafted",
        target=str(profile_row.id),
        meta={"job_name": JOB_EVENING, "model": model},
    )
    summary.drafted += 1
    summary.details.append({"profile_id": str(profile_row.id), "result": "drafted"})


async def _active_profiles(session: AsyncSession, *, limit: int) -> list[Profile]:
    stmt = (
        select(Profile)
        .where(Profile.status.in_(ACTIVE_STATUSES))
        .order_by(Profile.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def _draft_exists(session: AsyncSession, profile_id: uuid.UUID, moment: datetime) -> bool:
    """Đã có nháp cho **đúng ngày** đó chưa.

    So theo ngày, không theo giây: chạy bù lúc 20:17 mang `scheduled_for` 20:00
    nhưng một lần bấm tay lúc 21:00 thì không — vẫn phải coi là cùng một tối.
    """
    day: date = moment.date()
    stmt = (
        select(func.count())
        .select_from(OutboxItem)
        .where(
            OutboxItem.profile_id == profile_id,
            OutboxItem.scheduled_for >= datetime.combine(day, time.min, tzinfo=moment.tzinfo),
            OutboxItem.scheduled_for
            < datetime.combine(day + timedelta(days=1), time.min, tzinfo=moment.tzinfo),
        )
    )
    return bool((await session.execute(stmt)).scalar_one())


async def _latest_bundle(session: AsyncSession, profile_id: uuid.UUID) -> EvidenceBundle | None:
    stmt = (
        select(ProfileEvidence)
        .where(ProfileEvidence.profile_id == profile_id)
        .order_by(ProfileEvidence.created_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    return EvidenceBundle.from_dict(row.bundle) if row and row.bundle else None


def _profile_result_from_row(row: Profile) -> ProfileResult:
    """Dựng lại `ProfileResult` từ DB — **không** gọi lại model vision.

    Mô tả ảnh đã là bằng chứng đã lưu (task.md I-32); gọi lại vision mỗi tối cho
    cùng một ảnh là đốt quota để nhận lại gần đúng câu cũ.
    """
    demographics = row.demographics or {}
    basis = demographics.get("basis") if isinstance(demographics.get("basis"), dict) else {}
    return ProfileResult(
        status=row.status,
        customer_name=row.customer_name,
        visual_context=row.visual_context,
        demographics=Demographics(
            gender=demographics.get("gender"),
            estimated_age_range=demographics.get("estimated_age_range"),
            apparent_lifestyle=demographics.get("apparent_lifestyle"),
            basis=dict(basis or {}),
        ),
    )
