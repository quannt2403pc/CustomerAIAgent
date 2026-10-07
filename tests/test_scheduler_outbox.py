"""D2.4 — lịch 20h (APScheduler + jobstore Postgres) + outbox + API outbox.

Test quan trọng nhất của file này là `test_khong_co_duong_gui_tin_nhan_nao` —
nó canh gác **luật thép L3** bằng grep toàn repo. Mọi test khác chỉ chứng minh
tính năng; test đó chứng minh ta **không** làm điều đã cam kết không làm.
"""

from __future__ import annotations

import pathlib
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.collectors.evidence import EvidenceBundle
from app.main import create_app
from app.models import EveningHook, JobRun, OutboxItem, Profile, ProfileEvidence
from app.routers.deps import get_db_session
from app.scheduler import evening, runner
from app.services.evening_hook import EveningHookResult
from app.services.validators import ZeroSalesReport
from tests.source_guards import find_in_code, scan_files

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Mẫu đúng như DoD D2.4 nêu.
SEND_PATTERN = re.compile(
    r"send_message|messenger|graph\.facebook\.com/[^\s\"']*/messages",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Luật thép L3 — canh gác bằng grep toàn repo
# ---------------------------------------------------------------------------
def test_khong_co_duong_gui_tin_nhan_nao() -> None:
    """Luật L3: hệ thống **chỉ soạn nháp**, không có đường gửi cho người thật.

    Grep theo đúng mẫu DoD D2.4 nêu. Quét `app/`, `main.py`, `run.py` — tức là
    mọi thứ chạy trong production. `tests/` được loại vì chính file này phải
    chứa các mẫu đó để tìm chúng.
    """
    targets = [
        *sorted((REPO_ROOT / "app").rglob("*.py")),
        REPO_ROOT / "main.py",
        REPO_ROOT / "run.py",
    ]
    offenders = scan_files(targets, SEND_PATTERN, root=REPO_ROOT)
    assert not offenders, "Có đường gửi tin nhắn — vi phạm luật L3:\n" + "\n".join(offenders)


def test_bo_canh_gac_l3_khong_rong_nghia() -> None:
    """Canh gác phải bắt được vi phạm thật, không chỉ luôn xanh.

    Chạy bản quét **thật** (`find_in_code`) trên source giả, chứ không chỉ thử
    regex: phần dễ sai nằm ở chỗ bỏ qua comment/docstring, không ở regex.
    """
    assert find_in_code(
        "await client.send_message(recipient_id, text)\n", SEND_PATTERN
    )
    assert find_in_code(
        'URL = "https://graph.facebook.com/v19.0/me/messages"\n', SEND_PATTERN
    )
    assert find_in_code("from fbmessenger import MessengerClient\n", SEND_PATTERN)

    # Không bắt oan từ ngữ bình thường…
    assert find_in_code("x = result.message\n", SEND_PATTERN) == []
    assert find_in_code("rapport_messages = []\n", SEND_PATTERN) == []
    # …và không bắt oan docstring/comment nói về việc KHÔNG gửi tin.
    assert (
        find_in_code(
            '"""Không import client Messenger nào."""\n'
            "x = 1  # không gọi send_message ở đâu cả\n",
            SEND_PATTERN,
        )
        == []
    )


def test_outbox_khong_co_trang_thai_nao_nghia_la_he_thong_da_gui() -> None:
    """`sent_manually` là *con người* đã gửi. Không có `sent`/`delivered`."""
    from app.models import OUTBOX_STATUSES

    assert set(OUTBOX_STATUSES) == {"draft", "approved", "sent_manually", "discarded"}
    assert "sent" not in OUTBOX_STATUSES
    assert "delivered" not in OUTBOX_STATUSES


def test_endpoint_outbox_khong_co_route_nao_ten_send() -> None:
    app = create_app()
    paths = [r.path for r in app.routes if hasattr(r, "methods")]
    assert not [p for p in paths if re.search(r"/send\b", p)], (
        "một route tên `send` là lời mời hiện thực việc gửi (luật L3)"
    )
    assert "/api/outbox/{item_id}/mark-sent" in paths


# ---------------------------------------------------------------------------
# Cấu hình scheduler
# ---------------------------------------------------------------------------
def test_tham_so_scheduler_dung_nhu_ke_hoach() -> None:
    """plan.md §5.5 — mỗi tham số vá một kiểu lỗi thật, không phải mặc định."""
    assert runner.MISFIRE_GRACE_SECONDS == 1800
    # Job khai bằng **đường dẫn chuỗi** để jobstore serialize được.
    assert runner.EVENING_JOB_REF == "app.scheduler.evening:run_evening_cadence"
    assert ":" in runner.EVENING_JOB_REF


def test_trigger_time_trong_output_la_hang_so_khong_theo_cron(monkeypatch) -> None:
    """Đổi cron để kiểm chứng **không được** làm `trigger_time` lệch khỏi "20:00".

    Đề bài khoá `evening_cadence_20pm.trigger_time = "20:00"`. Nếu hai thứ dùng
    chung một biến thì một lần đổi cron để test sẽ lọt vào JSON nộp bài.
    """
    from app.schemas.output import TRIGGER_TIME, EveningCadence

    monkeypatch.setenv("EVENING_CRON_HOUR", "9")
    monkeypatch.setenv("EVENING_CRON_MINUTE", "31")
    from app.core.config import get_settings

    get_settings.cache_clear()
    assert get_settings().evening_cron_hour == 9

    assert TRIGGER_TIME == "20:00"
    assert EveningCadence().trigger_time == "20:00"
    # Và `Literal` của Pydantic chặn hẳn việc đặt giá trị khác.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EveningCadence(trigger_time="09:31")


def test_status_noi_that_khi_scheduler_chua_chay(monkeypatch) -> None:
    """Scheduler chết âm thầm thì mốc 20h có thể không chạy hàng tuần."""
    monkeypatch.setattr(runner, "_scheduler", None)
    monkeypatch.setattr(runner, "_last_error", "")
    state = runner.status()
    assert state.enabled is True
    assert state.running is False
    assert "chưa khởi động" in state.detail
    assert state.cron.endswith("Asia/Ho_Chi_Minh")


def test_status_noi_ro_khi_bi_tat_bang_cau_hinh(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    state = runner.status()
    assert state.enabled is False
    assert "SCHEDULER_ENABLED" in state.detail


@pytest.mark.asyncio
async def test_scheduler_khong_len_duoc_thi_api_van_phuc_vu(monkeypatch) -> None:
    """Người vận hành vẫn cần trang Cài đặt để đi sửa — không được chết cả API."""
    monkeypatch.setattr(runner, "_scheduler", None)
    monkeypatch.setattr(runner, "_last_error", "")

    def _explode(*args, **kwargs):
        raise RuntimeError("jobstore không kết nối được")

    monkeypatch.setattr(runner, "AsyncIOScheduler", _explode)
    await runner.start()  # không raise

    state = runner.status()
    assert state.running is False
    assert "Không dựng được scheduler" in state.detail


# ---------------------------------------------------------------------------
# Mốc `scheduled_for`
# ---------------------------------------------------------------------------
def test_scheduled_for_la_moc_20h_gio_viet_nam_khong_phai_luc_chay(monkeypatch) -> None:
    """Chạy bù lúc 20:17 vẫn phải mang nhãn "nháp của mốc 20:00 hôm nay"."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    late = datetime(2026, 10, 7, 20, 17, 42, tzinfo=tz)

    moment = evening.scheduled_moment(late)
    assert moment.hour == 20
    assert moment.minute == 0
    assert moment.date() == late.date()
    assert moment.tzinfo is not None


def test_scheduled_for_dung_ngay_dia_phuong_khong_phai_ngay_utc() -> None:
    """23:30 giờ VN là **ngày hôm sau** theo UTC — lấy ngày UTC sẽ lệch một ngày."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    utc_moment = datetime(2026, 10, 7, 16, 30, tzinfo=UTC)  # = 23:30 ngày 7 ở VN
    moment = evening.scheduled_moment(utc_moment)
    assert moment.date() == datetime(2026, 10, 7).date()


# ---------------------------------------------------------------------------
# Job 20h chạy thật trên DB (model stub)
# ---------------------------------------------------------------------------
def _passing_hook(message: str = "Tối rồi, hôm nay của bạn thế nào?") -> EveningHookResult:
    return EveningHookResult(
        passed=True,
        attempts=1,
        message=message,
        grounded_in="customer_name",
        sales_report=ZeroSalesReport(judge_ran=True, judge_reason="sạch"),
    )


def _rejected_hook() -> EveningHookResult:
    return EveningHookResult(passed=False, attempts=3, message=None)


@pytest_asyncio.fixture
async def profile(db_session) -> Profile:
    """Một profile `SUCCESS` có evidence — đủ điều kiện sinh hook."""
    from sqlalchemy import delete

    await db_session.execute(delete(JobRun))
    await db_session.execute(delete(Profile))
    await db_session.flush()

    row = Profile(
        facebook_url="https://www.facebook.com/khach_test_20h",
        url_key="user:khach_test_20h",
        customer_name="Khách Test",
        visual_context="Ảnh một người trên sân cỏ.",
        status="SUCCESS",
        demographics={"gender": "Nam", "basis": {"gender": "mô tả ảnh"}},
    )
    db_session.add(row)
    await db_session.flush()

    bundle = EvidenceBundle(url_key=row.url_key, facebook_url=row.facebook_url)
    bundle.add_field(
        "customer_name",
        "Khách Test",
        source="og_meta",
        evidence='<meta property="og:title" content="Khách Test">',
        confidence=0.95,
    )
    db_session.add(
        ProfileEvidence(profile_id=row.id, bundle=bundle.to_dict(), collector_layers=["og_meta"])
    )
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_job_20h_sinh_nhap_vao_outbox(db_session, profile, monkeypatch) -> None:
    async def _hook(*args, **kwargs):
        return _passing_hook()

    monkeypatch.setattr(evening, "generate_evening_hook", _hook)
    summary = evening.EveningRunSummary()

    await evening._draft_for_profile(
        db_session,
        profile,
        gateway=object(),
        model="model-gia",
        temperature=0.9,
        moment=evening.scheduled_moment(),
        summary=summary,
    )
    await db_session.flush()

    assert summary.drafted == 1
    hook = (await db_session.execute(select(EveningHook))).scalars().one()
    assert hook.message == "Tối rồi, hôm nay của bạn thế nào?"
    assert hook.based_on is not None  # truy vết: dựa vào bằng chứng nào

    item = (await db_session.execute(select(OutboxItem))).scalars().one()
    assert item.status == "draft"  # luật L3 — chỉ nháp
    assert item.hook_id == hook.id
    assert item.acted_at is None
    assert item.scheduled_for.hour == 20


@pytest.mark.asyncio
async def test_hook_bi_kiem_duyet_loai_thi_khong_day_gi_vao_outbox(
    db_session, profile, monkeypatch
) -> None:
    """Một nháp "chưa duyệt" nằm cạnh nháp đã duyệt là mời copy nó đi gửi (L2)."""

    async def _hook(*args, **kwargs):
        return _rejected_hook()

    monkeypatch.setattr(evening, "generate_evening_hook", _hook)
    summary = evening.EveningRunSummary()

    await evening._draft_for_profile(
        db_session,
        profile,
        gateway=object(),
        model="model-gia",
        temperature=0.9,
        moment=evening.scheduled_moment(),
        summary=summary,
    )
    await db_session.flush()

    assert summary.rejected_by_validators == 1
    assert summary.drafted == 0
    assert (await db_session.execute(select(func.count()).select_from(OutboxItem))).scalar_one() == 0
    assert (await db_session.execute(select(func.count()).select_from(EveningHook))).scalar_one() == 0

    # Và `details` chỉ nêu số lượt, không trích nguyên văn câu vi phạm (I-23).
    detail = summary.details[0]
    assert detail["result"] == "rejected"
    assert detail["attempts"] == 3
    assert "reason" not in detail


@pytest.mark.asyncio
async def test_chay_hai_lan_cung_toi_khong_tao_nhap_trung(db_session, profile, monkeypatch) -> None:
    """Chạy bù (`coalesce`) hoặc bấm tay hai lần không được tạo hai nháp."""

    async def _hook(*args, **kwargs):
        return _passing_hook()

    monkeypatch.setattr(evening, "generate_evening_hook", _hook)
    moment = evening.scheduled_moment()

    first = evening.EveningRunSummary()
    await evening._draft_for_profile(
        db_session, profile, gateway=object(), model="m", temperature=0.9,
        moment=moment, summary=first,
    )
    await db_session.flush()

    second = evening.EveningRunSummary()
    await evening._draft_for_profile(
        db_session, profile, gateway=object(), model="m", temperature=0.9,
        moment=moment, summary=second,
    )
    await db_session.flush()

    assert first.drafted == 1
    assert second.drafted == 0
    assert second.skipped_existing == 1
    assert (await db_session.execute(select(func.count()).select_from(OutboxItem))).scalar_one() == 1


@pytest.mark.asyncio
async def test_bam_tay_luc_21h_van_tinh_la_cung_mot_toi(db_session, profile, monkeypatch) -> None:
    """So theo **ngày**, không theo giây — nếu không, một tối ra hai nháp."""

    async def _hook(*args, **kwargs):
        return _passing_hook()

    monkeypatch.setattr(evening, "generate_evening_hook", _hook)
    moment = evening.scheduled_moment()

    summary = evening.EveningRunSummary()
    await evening._draft_for_profile(
        db_session, profile, gateway=object(), model="m", temperature=0.9,
        moment=moment, summary=summary,
    )
    await db_session.flush()

    later_same_day = moment + timedelta(hours=1)
    again = evening.EveningRunSummary()
    await evening._draft_for_profile(
        db_session, profile, gateway=object(), model="m", temperature=0.9,
        moment=later_same_day, summary=again,
    )
    await db_session.flush()
    assert again.skipped_existing == 1

    # Nhưng tối **hôm sau** thì phải sinh nháp mới.
    tomorrow = moment + timedelta(days=1)
    next_day = evening.EveningRunSummary()
    await evening._draft_for_profile(
        db_session, profile, gateway=object(), model="m", temperature=0.9,
        moment=tomorrow, summary=next_day,
    )
    await db_session.flush()
    assert next_day.drafted == 1


@pytest.mark.asyncio
async def test_chi_lay_profile_doc_duoc_du_kien(db_session, profile) -> None:
    """`FAILED_VALIDATION`/`ERROR` bị loại — sinh hook từ đó là mời model bịa (L1)."""
    for i, status in enumerate(["FAILED_VALIDATION", "ERROR", "PARTIAL_OR_PRIVATE"]):
        db_session.add(
            Profile(
                facebook_url=f"https://www.facebook.com/k{i}",
                url_key=f"user:k{i}",
                status=status,
            )
        )
    await db_session.flush()

    rows = await evening._active_profiles(db_session, limit=50)
    statuses = {r.status for r in rows}
    assert statuses == {"SUCCESS", "PARTIAL_OR_PRIVATE"}
    assert "FAILED_VALIDATION" not in statuses
    assert "ERROR" not in statuses


@pytest.mark.asyncio
async def test_dung_lai_profile_tu_db_khong_goi_lai_vision(db_session, profile) -> None:
    """Gọi lại vision mỗi tối cho cùng một ảnh là đốt quota để nhận lại câu cũ (I-32)."""
    result = evening._profile_result_from_row(profile)
    assert result.customer_name == "Khách Test"
    assert result.visual_context == "Ảnh một người trên sân cỏ."
    assert result.demographics.gender == "Nam"
    assert result.demographics.basis == {"gender": "mô tả ảnh"}
    assert result.is_usable_for_rapport is True


@pytest.mark.asyncio
async def test_chua_chon_model_thi_luot_20h_bao_that_khong_bao_ok(monkeypatch) -> None:
    """Ghi `ok = true` cho một lượt không làm gì là một lời nói sai.

    Cấu hình được tiêm trực tiếp thay vì ghi vào DB: `llm_settings` chỉ có một
    hàng dùng chung, nên một test ghi vào đó sẽ phụ thuộc trạng thái máy chạy
    (máy đã cấu hình thật qua UI thì test xanh sai).
    """
    from app.core.errors import AppError
    from app.llm.resolver import ActiveConfig

    async def _no_model(_session):
        return ActiveConfig(
            provider="antigravity", model="", temperature=0.9, max_output_tokens=4096
        )

    maker = _real_sessionmaker()
    monkeypatch.setattr("app.scheduler.evening.get_sessionmaker", lambda: maker)
    monkeypatch.setattr(evening, "get_active_config", _no_model)

    with pytest.raises(AppError) as exc:
        await evening._generate_drafts()
    assert "chưa chọn" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_luot_20h_that_bai_ghi_ok_false_vao_job_runs(monkeypatch) -> None:
    """Job raise thì APScheduler chỉ ghi một dòng log — không ai đọc.

    Mọi thất bại phải thành `job_runs.ok = false` + `summary`, tức là thứ trang
    Nhật ký đọc được.
    """
    from app.models import JobRun as JobRunModel

    maker = _real_sessionmaker()
    monkeypatch.setattr("app.scheduler.evening.get_sessionmaker", lambda: maker)

    async def _explode():
        raise RuntimeError("chi-tiet-ky-thuat-khong-duoc-lo")

    monkeypatch.setattr(evening, "_generate_drafts", _explode)

    summary = await evening.run_evening_cadence()  # không raise
    assert summary.failed == 1

    async with maker() as session:
        row = (
            await session.execute(
                select(JobRunModel)
                .where(JobRunModel.job_name == evening.JOB_EVENING)
                .order_by(JobRunModel.started_at.desc())
                .limit(1)
            )
        ).scalar_one()
        try:
            assert row.ok is False
            assert row.finished_at is not None
            assert row.summary["failed"] == 1
            # Chỉ **loại** lỗi, không nguyên văn chi tiết kỹ thuật.
            assert "chi-tiet-ky-thuat-khong-duoc-lo" not in str(row.summary)
            assert "RuntimeError" in str(row.summary)
        finally:
            await session.delete(row)
            await session.commit()


def _real_sessionmaker():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import _test_database_url

    url = _test_database_url()
    if url is None:
        pytest.skip("Cần Postgres thật")
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


# ---------------------------------------------------------------------------
# API outbox
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(db_session, monkeypatch) -> TestClient:
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()

    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    return TestClient(app, raise_server_exceptions=False)


@pytest_asyncio.fixture
async def draft(db_session, profile) -> OutboxItem:
    hook = EveningHook(profile_id=profile.id, message="Tối nay bạn ổn không?")
    db_session.add(hook)
    await db_session.flush()
    item = OutboxItem(
        profile_id=profile.id,
        hook_id=hook.id,
        status="draft",
        scheduled_for=evening.scheduled_moment(),
    )
    db_session.add(item)
    await db_session.flush()
    return item


def test_danh_sach_outbox_co_du_thu_de_copy_di_gui_tay(client, draft) -> None:
    body = client.get("/api/outbox").json()
    assert body["total"] >= 1
    item = next(i for i in body["items"] if i["id"] == str(draft.id))
    assert item["message"] == "Tối nay bạn ổn không?"
    assert item["customer_name"] == "Khách Test"
    assert item["facebook_url"].endswith("khach_test_20h")
    assert item["status"] == "draft"
    assert item["acted_at"] is None


def test_loc_theo_trang_thai(client, draft) -> None:
    assert client.get("/api/outbox", params={"status": "draft"}).json()["total"] >= 1
    assert client.get("/api/outbox", params={"status": "sent_manually"}).json()["total"] == 0
    assert client.get("/api/outbox", params={"status": "khong-ton-tai"}).status_code == 404


def test_mark_sent_doi_trang_thai_va_ghi_moc_thoi_gian(client, draft) -> None:
    resp = client.post(f"/api/outbox/{draft.id}/mark-sent")
    assert resp.status_code == 200
    assert "tự gửi tay" in resp.json()["message"]

    item = next(
        i
        for i in client.get("/api/outbox").json()["items"]
        if i["id"] == str(draft.id)
    )
    assert item["status"] == "sent_manually"
    assert item["acted_at"] is not None


def test_mark_sent_hai_lan_tra_409_khong_ghi_de_moc_thoi_gian(client, draft) -> None:
    """`acted_at` là bằng chứng vận hành — bấm hai lần không được âm thầm ghi đè."""
    assert client.post(f"/api/outbox/{draft.id}/mark-sent").status_code == 200
    second = client.post(f"/api/outbox/{draft.id}/mark-sent")
    assert second.status_code == 409
    assert "sent_manually" in second.json()["message"]


def test_discard_bo_nhap(client, draft) -> None:
    assert client.post(f"/api/outbox/{draft.id}/discard").status_code == 200
    item = next(
        i for i in client.get("/api/outbox").json()["items"] if i["id"] == str(draft.id)
    )
    assert item["status"] == "discarded"


def test_nhap_khong_ton_tai_tra_404(client) -> None:
    import uuid

    resp = client.post(f"/api/outbox/{uuid.uuid4()}/mark-sent")
    assert resp.status_code == 404
    assert set(resp.json()) == {"code", "message"}


def test_health_noi_ra_trang_thai_scheduler(client) -> None:
    """Mốc 20h là deliverable của đề bài — chết âm thầm là không chấp nhận được."""
    body = client.get("/health").json()
    assert "scheduler" in body
    assert set(body["scheduler"]) == {"enabled", "running", "next_run_at", "cron", "detail"}
    assert body["scheduler"]["cron"].endswith("Asia/Ho_Chi_Minh")
