"""Lưu kết quả một lần phân tích vào PostgreSQL (plan.md §5.9).

Upsert theo `profiles.url_key`: chạy lại cùng một URL thì **cập nhật** profile
cũ và thêm một `rapport_runs` mới, không tạo profile trùng. Lịch sử các lượt
sinh được giữ lại — nó là bằng chứng để so sánh chất lượng về sau.

CLI chạy `--no-db` thì không gọi module này; đường L4 dán tay vẫn ra JSON hợp lệ
mà không cần Postgres.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import (
    EveningHook,
    Profile,
    ProfileEvidence,
    RapportMessage,
    RapportRun,
)
from app.services.pipeline import AnalysisOutcome

log = get_logger(__name__)


async def save_analysis(
    session: AsyncSession,
    outcome: AnalysisOutcome,
    *,
    provider: str,
    model: str,
) -> uuid.UUID:
    """Ghi profile + evidence + lượt sinh + hook. Trả `profiles.id`."""
    output = outcome.output
    bundle = outcome.bundle

    profile_row = await _upsert_profile(session, outcome)

    # Evidence: thêm bản ghi mới mỗi lần chạy. Ghi đè sẽ mất dấu "lần trước
    # đọc được gì", đúng thứ cần khi nội dung hai lần chạy khác nhau.
    session.add(
        ProfileEvidence(
            profile_id=profile_row.id,
            bundle=bundle.to_dict(),
            collector_layers=outcome.layers_used or [],
            screenshot_path=bundle.screenshot_path,
        )
    )

    if outcome.sequence is not None:
        run = RapportRun(
            profile_id=profile_row.id,
            provider=provider,
            model=model,
            empathy_angle=outcome.sequence.empathy_angle,
            sales_check=outcome.sequence.sales_check,
            grounding_report=outcome.sequence.report_for_db(),
            latency_ms=(outcome.sequence.rapport.latency_ms if outcome.sequence.rapport else None),
            token_usage=(outcome.sequence.rapport.usage if outcome.sequence.rapport else None),
        )
        session.add(run)
        await session.flush()

        for seq, text in enumerate(output.ethical_rapport.dialogue_sequence_10, 1):
            session.add(RapportMessage(run_id=run.id, seq=seq, text=text))

    if message := output.evening_cadence_20pm.evening_hook_message:
        session.add(
            EveningHook(
                profile_id=profile_row.id,
                message=message,
                based_on=outcome.hook.report_for_db() if outcome.hook else None,
            )
        )

    await session.flush()
    log.info("Đã lưu kết quả phân tích cho profile %s", profile_row.id)
    return profile_row.id


async def _upsert_profile(session: AsyncSession, outcome: AnalysisOutcome) -> Profile:
    output = outcome.output
    bundle = outcome.bundle

    existing = (
        await session.execute(select(Profile).where(Profile.url_key == bundle.url_key))
    ).scalar_one_or_none()

    row = existing or Profile(facebook_url=output.facebook_url, url_key=bundle.url_key)
    if existing is None:
        session.add(row)

    row.facebook_url = output.facebook_url
    row.status = output.status
    row.customer_name = output.profile_data.customer_name
    row.visual_context = output.profile_data.visual_context
    # `basis` chỉ lưu DB, không ra output — nó là đường truy vết căn cứ suy luận.
    row.demographics = {
        **output.profile_data.estimated_demographics.model_dump(mode="json"),
        "basis": outcome.profile.demographics.basis if outcome.profile else {},
    }
    row.error_note = output.error_note
    # Nguyên văn strict JSON của lượt này — `GET …/output.json` phục vụ lại đúng
    # chuỗi đó, không dựng lại (task.md I-39).
    row.last_output = output.to_dict()

    await session.flush()
    return row
