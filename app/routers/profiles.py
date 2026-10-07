"""`/api/profiles/*` + `/api/jobs/*` — tạo job phân tích, xem kết quả, tải JSON.

Ba quyết định đáng giải thích:

1. **Phân tích chạy nền.** Một lần chạy mất hàng chục giây (đo thật D1.21: 70s)
   và gọi model 7–14 lượt. `POST` trả `job_id` ngay; UI poll `GET /api/jobs/{id}`
   để vẽ timeline 6 bước.
2. **`output.json` phục vụ nguyên văn** chuỗi đã lưu ở `profiles.last_output`,
   không dựng lại từ các bảng con (task.md I-39). DoD đòi "giống hệt CLI"; dựng
   lại chỉ đúng chừng nào hai đường code còn khớp.
3. **Gọi lại cùng URL không tạo profile trùng.** `url_key` unique, và mặc định
   `refresh=false` → trả bản ghi cũ, **không gọi model lần nào**. Mỗi lần chạy là
   tiền thật (task.md I-25), nên mặc định phải là rẻ.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.url import normalize_facebook_url
from app.core.errors import GatewayModelInvalid, InvalidFacebookUrl, NotFoundError
from app.core.logging import get_logger
from app.core.ratelimit import analyze_rate_limit
from app.llm.resolver import get_active_config
from app.models import JobRun, Profile, ProfileEvidence, RapportMessage, RapportRun
from app.routers.deps import SessionDep
from app.schemas.api import (
    AnalyzeAcceptedOut,
    AnalyzeRequest,
    DashboardStatsOut,
    EvidenceFieldOut,
    EvidenceImageOut,
    EvidencePanelOut,
    JobOut,
    ProfileDetailOut,
    ProfileListOut,
    ProfileSummaryOut,
    StepOut,
)
from app.schemas.output import TRIGGER_TIME, StrictOutput
from app.services import audit, jobs

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["profiles"])


# ---------------------------------------------------------------------------
# Tạo job phân tích
# ---------------------------------------------------------------------------
@router.post(
    "/profiles",
    response_model=AnalyzeAcceptedOut,
    status_code=202,
    dependencies=[Depends(analyze_rate_limit.dependency)],
)
async def create_analysis(body: AnalyzeRequest, session: SessionDep) -> AnalyzeAcceptedOut:
    """Nhận yêu cầu, trả `job_id` ngay (202). Không chờ model.

    Kiểm **trước** hai thứ để không tạo một job chắc chắn thất bại:
    URL đúng định dạng, và đã chọn cổng + model. Phát hiện muộn thì người dùng
    phải chờ job chạy rồi mới biết mình chưa cấu hình.
    """
    if not body.facebook_url and not body.profile_text:
        raise InvalidFacebookUrl(
            "Cần `facebook_url`, hoặc `profile_text` nếu bạn dán tay nội dung trang."
        )

    url_key: str | None = None
    if body.facebook_url:
        # Raise `InvalidFacebookUrl` (400) — lỗi của người gọi, nói ngay.
        url_key = normalize_facebook_url(body.facebook_url).url_key

    config = await get_active_config(session)
    if not config.model:
        raise GatewayModelInvalid(
            "Chưa chọn cổng model hoặc chưa chọn model. Vào Cài đặt để chọn trước khi phân tích."
        )

    if url_key:
        existing = (
            await session.execute(select(Profile).where(Profile.url_key == url_key))
        ).scalar_one_or_none()
        if existing is not None and not body.refresh:
            latest = await jobs.latest_job_for_url_key(session, url_key)
            return AnalyzeAcceptedOut(
                job_id=str(latest.id) if latest else None,
                profile_id=str(existing.id),
                reused=True,
                message=(
                    "URL này đã được phân tích. Đang hiện kết quả đã lưu — "
                    'bấm "Phân tích lại" nếu bạn muốn chạy mới.'
                ),
            )

    job = await jobs.create_job_row(
        session,
        job_name=jobs.JOB_ANALYZE,
        summary={
            "url_key": url_key or "manual:local",
            "facebook_url": body.facebook_url or "(dán tay)",
        },
    )
    await audit.record(
        session,
        "profile.analyze_requested",
        target=url_key or "manual",
        meta={"model": config.model, "provider": config.provider, "refresh": body.refresh},
    )
    # Commit **trước** khi đẩy task: job nền mở session riêng và sẽ không thấy
    # hàng `job_runs` nếu nó còn nằm trong transaction chưa commit của request.
    await session.commit()

    jobs.start_analysis_job(
        job.id,
        url=body.facebook_url,
        profile_text=body.profile_text,
        use_playwright=body.use_playwright,
        n_messages=body.messages,
    )
    return AnalyzeAcceptedOut(
        job_id=str(job.id),
        message="Đã nhận. Quá trình phân tích mất vài chục giây.",
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: SessionDep) -> JobOut:
    """Tiến trình 6 bước. `ok = null` nghĩa là đang chạy."""
    row = await jobs.get_job(session, job_id)
    if row is None:
        raise NotFoundError("Không tìm thấy lượt phân tích này.")
    return _job_out(row)


# ---------------------------------------------------------------------------
# Danh sách + chi tiết
# ---------------------------------------------------------------------------
@router.get("/profiles", response_model=ProfileListOut)
async def list_profiles(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ProfileListOut:
    """Mới nhất trước — có index `ix_profiles_created_at_desc` cho đúng chiều này."""
    total = (await session.execute(select(func.count()).select_from(Profile))).scalar_one()
    rows = (
        (
            await session.execute(
                select(Profile).order_by(Profile.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    items: list[ProfileSummaryOut] = []
    for row in rows:
        run = await _latest_run(session, row.id)
        items.append(
            ProfileSummaryOut(
                id=str(row.id),
                facebook_url=row.facebook_url,
                customer_name=row.customer_name,
                status=row.status,
                created_at=row.created_at,
                message_count=len(_messages_of(row)),
                sales_check=run.sales_check if run else None,
            )
        )
    return ProfileListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/profiles/{profile_id}", response_model=ProfileDetailOut)
async def get_profile(profile_id: uuid.UUID, session: SessionDep) -> ProfileDetailOut:
    """Kết quả đã render + panel evidence + tiến trình của lượt chạy gần nhất."""
    row = await _get_profile_or_404(session, profile_id)
    run = await _latest_run(session, row.id)
    evidence = await _latest_evidence(session, row.id)
    job = await jobs.latest_job_for_url_key(session, row.url_key)
    stored = _stored_output(row)

    return ProfileDetailOut(
        id=str(row.id),
        facebook_url=row.facebook_url,
        status=row.status,
        created_at=row.created_at,
        customer_name=row.customer_name,
        visual_context=row.visual_context,
        # `basis` là đường truy vết căn cứ suy luận, chỉ lưu DB — không ra output
        # nộp bài, nhưng **có** ra UI: người vận hành cần thấy vì sao model đoán vậy.
        demographics=dict(row.demographics or {}),
        error_note=row.error_note,
        core_empathy_angle=run.empathy_angle if run else None,
        messages=_messages_of(row, stored),
        sales_mention_check=run.sales_check if run else None,
        evening_hook_message=_hook_of(stored),
        trigger_time=TRIGGER_TIME,
        has_stored_output=bool(row.last_output),
        provider=run.provider if run else None,
        model=run.model if run else None,
        latency_ms=run.latency_ms if run else None,
        evidence=_evidence_panel(evidence),
        job=_job_out(job) if job else None,
    )


@router.get("/profiles/{profile_id}/output.json")
async def download_output_json(profile_id: uuid.UUID, session: SessionDep) -> Response:
    """Tải strict JSON — **giống hệt** CLI, vì đây là đúng chuỗi đã lưu.

    `Content-Disposition: attachment` là có chủ đích (plan.md §7.3.7): muốn xem
    JSON thì **tải file**, không in ra console trình duyệt (luật L5).
    """
    row = await _get_profile_or_404(session, profile_id)
    if not row.last_output:
        raise NotFoundError("Profile này chưa có kết quả nào để tải. Hãy chạy phân tích trước.")

    # Dựng lại qua Pydantic trước khi phục vụ: nếu dữ liệu đã lưu lệch lược đồ
    # (vd sau một lần đổi schema) thì phải lỗi ở đây, không phải phục vụ ra một
    # tệp "strict JSON" không còn strict.
    output = StrictOutput.model_validate(row.last_output)
    filename = f"output-{profile_id}.json"
    return Response(
        content=output.to_json() + "\n",
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/stats", response_model=DashboardStatsOut)
async def dashboard_stats(session: SessionDep) -> DashboardStatsOut:
    """KPI cho Dashboard — đếm thật, không ước lượng."""
    from app.models import OutboxItem

    by_status = dict(
        (await session.execute(select(Profile.status, func.count()).group_by(Profile.status))).all()
    )
    total = sum(by_status.values())
    readable = by_status.get("SUCCESS", 0) + by_status.get("PARTIAL_OR_PRIVATE", 0)
    messages_total = (
        await session.execute(select(func.count()).select_from(RapportMessage))
    ).scalar_one()
    hooks_waiting = (
        await session.execute(
            select(func.count()).select_from(OutboxItem).where(OutboxItem.status == "draft")
        )
    ).scalar_one()

    return DashboardStatsOut(
        profiles_total=total,
        profiles_success=by_status.get("SUCCESS", 0),
        profiles_partial=by_status.get("PARTIAL_OR_PRIVATE", 0),
        profiles_failed=by_status.get("FAILED_VALIDATION", 0) + by_status.get("ERROR", 0),
        # `None` khi chưa có profile nào: hiện "0%" cho một mẫu rỗng là nói sai.
        readable_rate=round(readable / total, 4) if total else None,
        hooks_waiting=hooks_waiting,
        messages_total=messages_total,
    )


# ---------------------------------------------------------------------------
# Trợ giúp
# ---------------------------------------------------------------------------
async def _get_profile_or_404(session: AsyncSession, profile_id: uuid.UUID) -> Profile:
    row = await session.get(Profile, profile_id)
    if row is None:
        raise NotFoundError("Không tìm thấy profile này.")
    return row


async def _latest_run(session: AsyncSession, profile_id: uuid.UUID) -> RapportRun | None:
    """Lượt sinh **gần nhất**. Lịch sử được giữ lại nên phải nêu rõ "gần nhất"."""
    stmt = (
        select(RapportRun)
        .where(RapportRun.profile_id == profile_id)
        .order_by(RapportRun.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _latest_evidence(session: AsyncSession, profile_id: uuid.UUID) -> ProfileEvidence | None:
    stmt = (
        select(ProfileEvidence)
        .where(ProfileEvidence.profile_id == profile_id)
        .order_by(ProfileEvidence.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _stored_output(row: Profile) -> dict[str, object]:
    return dict(row.last_output or {})


def _messages_of(row: Profile, stored: dict[str, object] | None = None) -> list[str]:
    """Chuỗi tin nhắn của lượt gần nhất, đọc từ strict JSON đã lưu.

    Cố ý **không** đọc từ `rapport_messages`: bảng đó giữ lịch sử nhiều lượt, và
    một lượt bị kiểm duyệt loại lưu 0 tin. Trộn hai lượt lại sẽ hiện nội dung của
    lượt cũ cạnh trạng thái của lượt mới — đúng kiểu nhập nhèm mà I-21/I-39 nói.
    """
    data = stored if stored is not None else _stored_output(row)
    rapport = data.get("ethical_rapport") or {}
    messages = rapport.get("dialogue_sequence_10") if isinstance(rapport, dict) else None
    return list(messages) if isinstance(messages, list) else []


def _hook_of(stored: dict[str, object]) -> str | None:
    cadence = stored.get("evening_cadence_20pm") or {}
    if not isinstance(cadence, dict):
        return None
    message = cadence.get("evening_hook_message")
    return message if isinstance(message, str) else None


def _evidence_panel(row: ProfileEvidence | None) -> EvidencePanelOut:
    if row is None:
        return EvidencePanelOut()

    bundle = row.bundle or {}
    fields = [
        EvidenceFieldOut(
            key=str(item.get("key") or ""),
            value=_as_text(item.get("value")),
            source=str(item.get("source") or ""),
            evidence=str(item.get("evidence") or ""),
            confidence=_as_number(item.get("confidence")),
        )
        for item in bundle.get("fields") or []
        if isinstance(item, dict)
    ]
    images = [
        EvidenceImageOut(
            role=str(item.get("role") or ""),
            # KHÔNG trả `url` gốc của Facebook: trình duyệt tải trực tiếp từ CDN
            # của họ là gửi referer của hệ thống ta sang đó.
            local_path=_as_text(item.get("local_path")),
            sha256=str(item.get("sha256") or ""),
        )
        for item in bundle.get("images") or []
        if isinstance(item, dict)
    ]
    return EvidencePanelOut(
        layers_used=list(row.collector_layers or []),
        blocked_reason=_as_text(bundle.get("blocked_reason")),
        screenshot_path=row.screenshot_path,
        fields=fields,
        images=images,
    )


def _job_out(row: JobRun) -> JobOut:
    summary = row.summary or {}
    steps = [
        StepOut(
            step=str(item.get("step") or ""),
            label=str(item.get("label") or ""),
            state=str(item.get("state") or "pending"),
            note=str(item.get("note") or ""),
            started_at=item.get("started_at"),
            finished_at=item.get("finished_at"),
        )
        for item in summary.get("steps") or []
        if isinstance(item, dict)
    ]
    return JobOut(
        job_id=str(row.id),
        job_name=row.job_name,
        ok=row.ok,
        started_at=row.started_at,
        finished_at=row.finished_at,
        steps=steps,
        profile_id=_as_text(summary.get("profile_id")),
        status=_as_text(summary.get("status")),
        error=_as_text(summary.get("error")),
    )


def _as_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_number(value: object) -> float | None:
    """`bool` là `int` trong Python — loại ra, nếu không `True` thành `confidence=1.0`."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None
