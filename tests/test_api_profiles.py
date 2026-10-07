"""D2.3 — API profiles: tạo job nền, theo dõi tiến trình, lấy kết quả, tải JSON.

Model được **stub ở mức gateway** (không gọi mạng): cái cần kiểm ở đây là tầng
API + job nền + DB, không phải chất lượng nội dung (đã kiểm ở D1.16/D1.17).

Hai điều quan trọng nhất của bộ test này:

- `output.json` phải **giống hệt** CLI — so sánh từng byte với chuỗi mà
  `main.py` in ra cho cùng một `AnalysisOutcome`.
- Gọi lại cùng URL **không** tạo profile trùng và **không** gọi model lần nào.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.collectors.evidence import EvidenceBundle, EvidenceImage
from app.collectors.url import normalize_facebook_url
from app.core.ratelimit import analyze_rate_limit
from app.llm.base import ModelInfo
from app.llm.catalog import get_catalog
from app.llm.resolver import set_model, set_provider
from app.main import create_app
from app.models import EveningHook, JobRun, Profile, ProfileEvidence, RapportMessage, RapportRun
from app.routers.deps import get_db_session
from app.schemas.output import (
    EstimatedDemographics,
    EthicalRapport,
    EveningCadence,
    ProfileData,
    StrictOutput,
)
from app.services import jobs, persistence
from app.services.pipeline import AnalysisOutcome, ValidatedSequence
from app.services.progress import Step
from app.services.validators import ZeroSalesReport

URL = "https://www.facebook.com/nguoi_dung_gia_dinh_test"
MODEL = "model-gia-cho-test"

TEN_MESSAGES = [f"Tin nhắn số {i} — chỉ để kiểm tầng API." for i in range(1, 11)]


# ---------------------------------------------------------------------------
# Hạ tầng test
# ---------------------------------------------------------------------------
def _outcome(status: str = "SUCCESS", *, hook: str | None = "Hook 20h giả.") -> AnalysisOutcome:
    """`AnalysisOutcome` giả, đủ hình dạng để `save_analysis` làm việc thật."""
    bundle = EvidenceBundle(url_key=normalize_facebook_url(URL).url_key, facebook_url=URL)
    bundle.add_field(
        "customer_name",
        "Người Dùng Giả",
        source="og_meta",
        evidence='<meta property="og:title" content="Người Dùng Giả">',
        confidence=0.95,
    )
    output = StrictOutput(
        status=status,
        facebook_url=URL,
        profile_data=ProfileData(
            customer_name="Người Dùng Giả",
            visual_context="Ảnh một người đứng trước sân cỏ.",
            estimated_demographics=EstimatedDemographics(
                gender="Nam", estimated_age_range="25 - 35 tuổi"
            ),
        ),
        ethical_rapport=EthicalRapport(
            core_empathy_angle="Thích thể thao",
            dialogue_sequence_10=TEN_MESSAGES,
            sales_mention_check="ZERO_SALES_CONFIRMED",
        ),
        evening_cadence_20pm=EveningCadence(evening_hook_message=hook),
    )
    # `sequence` là **bắt buộc**: `save_analysis` chỉ ghi `rapport_runs` +
    # `rapport_messages` khi có nó. Thiếu, DB trông như chưa chạy lượt nào.
    sequence = ValidatedSequence(
        passed=True,
        attempts=1,
        messages=list(output.ethical_rapport.dialogue_sequence_10),
        empathy_angle="Thích thể thao",
        sales_report=ZeroSalesReport(judge_ran=True, judge_reason="sạch"),
    )
    return AnalysisOutcome(
        output=output,
        bundle=bundle,
        sequence=sequence,
        layers_used=["og_meta"],
    )


class FakeGateway:
    provider = "antigravity"

    def __init__(self) -> None:
        self.calls = 0

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=MODEL, supports_vision=True)]

    async def generate_content(self, payload: dict, *, model: str) -> dict:  # pragma: no cover
        self.calls += 1
        raise AssertionError("test này không được gọi model")

    async def health(self):  # pragma: no cover
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def _real_sessionmaker():
    """Sessionmaker **thật** trỏ về DB test (không đi qua `.env` của app)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import _test_database_url

    url = _test_database_url()
    if url is None:
        pytest.skip("Cần Postgres thật cho test job nền")
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


async def wipe(session) -> None:
    """Xoá profile + job trong **transaction của test** (sẽ rollback sau).

    Cần vì DB dev có dữ liệu thật từ mốc D1.21 đã commit. Một test đếm
    `count(*) FROM profiles` mà không dọn thì vừa sai vừa phụ thuộc máy chạy.
    """
    from sqlalchemy import delete

    await session.execute(delete(JobRun))
    await session.execute(delete(Profile))  # cascade sang evidence/run/message/hook
    await session.flush()


@pytest_asyncio.fixture
async def setup(db_session, monkeypatch):
    """Cấu hình đủ để `POST /api/profiles` được nhận: đã chọn cổng + model."""
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    gateway = FakeGateway()
    monkeypatch.setattr("app.llm.resolver.AntigravityGateway", lambda *a, **k: gateway)
    get_catalog().invalidate()

    await wipe(db_session)
    await set_provider(db_session, "antigravity")
    await set_model(db_session, MODEL)

    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    analyze_rate_limit.reset()
    return TestClient(app, raise_server_exceptions=False), gateway


@pytest.fixture
def client(setup):
    return setup[0]


@pytest.fixture
def gateway(setup):
    return setup[1]


# ---------------------------------------------------------------------------
# POST /api/profiles — kiểm đầu vào trước khi tạo job
# ---------------------------------------------------------------------------
def test_thieu_ca_url_va_text_tra_400(client) -> None:
    resp = client.post("/api/profiles", json={})
    assert resp.status_code == 400
    assert "facebook_url" in resp.json()["message"]


def test_url_khong_thuoc_facebook_bi_tu_choi_truoc_khi_tao_job(client, db_session) -> None:
    """Tạo job rồi mới phát hiện URL sai là bắt người dùng chờ để nghe một câu nói ngay được."""
    resp = client.post("/api/profiles", json={"facebook_url": "https://facebook.com.evil.test/x"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "E-COL-400-URL"


@pytest.mark.asyncio
async def test_chua_chon_model_thi_khong_tao_job(db_session, monkeypatch) -> None:
    """Phát hiện muộn thì người dùng chờ 70 giây để nghe "bạn chưa cấu hình"."""
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    await wipe(db_session)
    await set_provider(db_session, "antigravity")
    # Xoá tường minh: `set_provider` chỉ xoá model khi cổng **đổi**, và DB dev
    # có thể đã có model thật từ lần chạy trước.
    await set_model(db_session, "")

    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    analyze_rate_limit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post("/api/profiles", json={"facebook_url": URL})

    assert resp.status_code == 400
    assert resp.json()["code"] == "E-LLM-400-MODEL"
    assert (await db_session.execute(select(func.count()).select_from(JobRun))).scalar_one() == 0


def test_tao_job_tra_202_va_job_id(client, monkeypatch) -> None:
    started: list[uuid.UUID] = []
    monkeypatch.setattr(jobs, "start_analysis_job", lambda jid, **kw: started.append(jid))

    resp = client.post("/api/profiles", json={"facebook_url": URL})
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["reused"] is False
    assert started == [uuid.UUID(body["job_id"])]


def test_rate_limit_tren_endpoint_ton_tien_model(client, monkeypatch) -> None:
    """plan.md §7.4 — một lần chạy gọi model 7–14 lượt (I-25)."""
    monkeypatch.setattr(jobs, "start_analysis_job", lambda jid, **kw: None)

    codes = [
        client.post("/api/profiles", json={"facebook_url": f"{URL}{i}"}).status_code
        for i in range(8)
    ]
    assert codes.count(202) == analyze_rate_limit.limiter.limit
    assert 429 in codes


# ---------------------------------------------------------------------------
# Không tạo profile trùng
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_goi_lai_cung_url_khong_tao_profile_trung_va_khong_goi_model(
    setup, db_session
) -> None:
    client, fake = setup
    await persistence.save_analysis(db_session, _outcome(), provider="antigravity", model=MODEL)
    await db_session.flush()

    resp = client.post("/api/profiles", json={"facebook_url": URL})
    assert resp.status_code == 202
    body = resp.json()
    assert body["reused"] is True
    assert body["profile_id"]
    assert body["job_id"] is None  # chưa có job nào cho URL này
    assert "Phân tích lại" in body["message"]

    # Và quan trọng nhất: không gọi model, không tạo profile thứ hai.
    assert fake.calls == 0
    count = (await db_session.execute(select(func.count()).select_from(Profile))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_refresh_true_thi_chay_lai(setup, db_session, monkeypatch) -> None:
    client, _ = setup
    await persistence.save_analysis(db_session, _outcome(), provider="antigravity", model=MODEL)
    await db_session.flush()

    monkeypatch.setattr(jobs, "start_analysis_job", lambda jid, **kw: None)
    body = client.post("/api/profiles", json={"facebook_url": URL, "refresh": True}).json()
    assert body["reused"] is False
    assert body["job_id"]


@pytest.mark.asyncio
async def test_chay_lai_cap_nhat_profile_cu_va_them_lan_sinh_moi(db_session) -> None:
    """`url_key` unique: lượt hai **cập nhật** profile, nhưng giữ lịch sử rapport_runs."""
    await wipe(db_session)
    first = await persistence.save_analysis(
        db_session, _outcome(), provider="antigravity", model=MODEL
    )
    second = await persistence.save_analysis(
        db_session,
        _outcome(status="PARTIAL_OR_PRIVATE"),
        provider="antigravity",
        model=MODEL,
    )
    assert first == second

    profiles = (await db_session.execute(select(func.count()).select_from(Profile))).scalar_one()
    runs = (await db_session.execute(select(func.count()).select_from(RapportRun))).scalar_one()
    assert profiles == 1
    assert runs == 2  # lịch sử được giữ

    row = await db_session.get(Profile, first)
    assert row.status == "PARTIAL_OR_PRIVATE"  # trạng thái là của lượt mới nhất


# ---------------------------------------------------------------------------
# DoD: phân tích end-to-end qua API → DB có đủ bản ghi
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mot_lan_phan_tich_ghi_du_nam_bang(db_session) -> None:
    await wipe(db_session)
    profile_id = await persistence.save_analysis(
        db_session, _outcome(), provider="antigravity", model=MODEL
    )
    await db_session.flush()

    async def count(model, where=None):
        stmt = select(func.count()).select_from(model)
        return (await db_session.execute(stmt if where is None else stmt.where(where))).scalar_one()

    assert await count(Profile, Profile.id == profile_id) == 1
    assert await count(ProfileEvidence, ProfileEvidence.profile_id == profile_id) == 1
    assert await count(RapportRun, RapportRun.profile_id == profile_id) == 1
    assert await count(RapportMessage) == 10
    assert await count(EveningHook, EveningHook.profile_id == profile_id) == 1


# ---------------------------------------------------------------------------
# DoD: output.json giống hệt CLI
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_output_json_giong_het_chuoi_cli_in_ra(setup, db_session) -> None:
    client, _ = setup
    outcome = _outcome()
    profile_id = await persistence.save_analysis(
        db_session, outcome, provider="antigravity", model=MODEL
    )
    await db_session.flush()

    resp = client.get(f"/api/profiles/{profile_id}/output.json")
    assert resp.status_code == 200

    # `main.py` in ra đúng `output.to_json()` + newline (xem app/schemas/output.py).
    assert resp.text == outcome.output.to_json() + "\n"
    assert json.loads(resp.text)["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_output_json_la_file_tai_ve_khong_phai_de_in_ra_console(setup, db_session) -> None:
    """plan.md §7.3.7: muốn xem JSON thì **tải file**, không in ra console (luật L5)."""
    client, _ = setup
    profile_id = await persistence.save_analysis(
        db_session, _outcome(), provider="antigravity", model=MODEL
    )
    await db_session.flush()

    resp = client.get(f"/api/profiles/{profile_id}/output.json")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert str(profile_id) in disposition


@pytest.mark.asyncio
async def test_output_json_cua_profile_chua_chay_tra_404_co_huong_dan(setup, db_session) -> None:
    client, _ = setup
    row = Profile(facebook_url=URL, url_key="chua-chay", status="ERROR")
    db_session.add(row)
    await db_session.flush()

    resp = client.get(f"/api/profiles/{row.id}/output.json")
    assert resp.status_code == 404
    assert "chạy phân tích" in resp.json()["message"]


@pytest.mark.asyncio
async def test_output_json_nhanh_that_bai_van_la_json_hop_le(setup, db_session) -> None:
    """`FAILED_VALIDATION` → `dialogue_sequence_10` rỗng, nhưng JSON vẫn hợp lệ."""
    client, _ = setup
    outcome = _outcome(status="FAILED_VALIDATION", hook=None)
    outcome.output.ethical_rapport.dialogue_sequence_10 = []
    outcome.output.ethical_rapport.sales_mention_check = "FAILED"
    outcome.output.error_note = "Chuỗi tin nhắn không qua được kiểm duyệt."

    profile_id = await persistence.save_analysis(
        db_session, outcome, provider="antigravity", model=MODEL
    )
    await db_session.flush()

    data = json.loads(client.get(f"/api/profiles/{profile_id}/output.json").text)
    assert data["status"] == "FAILED_VALIDATION"
    assert data["ethical_rapport"]["dialogue_sequence_10"] == []
    assert data["ethical_rapport"]["sales_mention_check"] == "FAILED"
    assert data["evening_cadence_20pm"]["evening_hook_message"] is None
    assert data["evening_cadence_20pm"]["trigger_time"] == "20:00"


# ---------------------------------------------------------------------------
# GET chi tiết + danh sách
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chi_tiet_profile_co_du_thu_ui_can(setup, db_session) -> None:
    client, _ = setup
    profile_id = await persistence.save_analysis(
        db_session, _outcome(), provider="antigravity", model=MODEL
    )
    await db_session.flush()

    body = client.get(f"/api/profiles/{profile_id}").json()
    assert body["customer_name"] == "Người Dùng Giả"
    assert len(body["messages"]) == 10
    assert body["sales_mention_check"] == "ZERO_SALES_CONFIRMED"
    assert body["evening_hook_message"] == "Hook 20h giả."
    assert body["trigger_time"] == "20:00"
    assert body["model"] == MODEL

    # Panel evidence — trụ của luật L1: mỗi dữ kiện kèm nguồn + bằng chứng.
    field = body["evidence"]["fields"][0]
    assert field["key"] == "customer_name"
    assert field["source"] == "og_meta"
    assert "og:title" in field["evidence"]
    assert field["confidence"] == 0.95
    assert body["evidence"]["layers_used"] == ["og_meta"]


@pytest.mark.asyncio
async def test_chi_tiet_khong_tra_url_anh_goc_cua_facebook(setup, db_session) -> None:
    """Để trình duyệt tải ảnh trực tiếp từ CDN Facebook là gửi referer của ta sang đó."""
    client, _ = setup
    outcome = _outcome()
    outcome.bundle.images.append(
        EvidenceImage(
            role="avatar",
            url="https://scontent.xx.fbcdn.net/v/anh-goc-khong-duoc-lo.jpg",
            local_path="var/uploads/abc123.webp",
            sha256="abc123",
        )
    )
    profile_id = await persistence.save_analysis(
        db_session, outcome, provider="antigravity", model=MODEL
    )
    await db_session.flush()

    resp = client.get(f"/api/profiles/{profile_id}")
    assert "scontent.xx.fbcdn.net" not in resp.text
    assert resp.json()["evidence"]["images"][0]["local_path"] == "var/uploads/abc123.webp"


def test_profile_khong_ton_tai_tra_404_dang_code_message(client) -> None:
    resp = client.get(f"/api/profiles/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert set(resp.json()) == {"code", "message"}


@pytest.mark.asyncio
async def test_danh_sach_phan_trang_va_moi_nhat_truoc(setup, db_session) -> None:
    client, _ = setup
    for i in range(3):
        outcome = _outcome()
        outcome.bundle.url_key = f"nguoi-{i}"
        outcome.output.facebook_url = f"{URL}-{i}"
        await persistence.save_analysis(db_session, outcome, provider="antigravity", model=MODEL)
    await db_session.flush()

    page = client.get("/api/profiles", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["items"][0]["message_count"] == 10

    times = [item["created_at"] for item in page["items"]]
    assert times == sorted(times, reverse=True)

    assert len(client.get("/api/profiles", params={"limit": 2, "offset": 2}).json()["items"]) == 1


@pytest.mark.asyncio
async def test_thong_ke_dashboard_dem_that(setup, db_session) -> None:
    client, _ = setup
    for i, status in enumerate(["SUCCESS", "PARTIAL_OR_PRIVATE", "FAILED_VALIDATION"]):
        outcome = _outcome(status=status)
        outcome.bundle.url_key = f"nguoi-tk-{i}"
        await persistence.save_analysis(db_session, outcome, provider="antigravity", model=MODEL)
    await db_session.flush()

    body = client.get("/api/stats").json()
    assert body["profiles_total"] == 3
    assert body["profiles_success"] == 1
    assert body["profiles_partial"] == 1
    assert body["profiles_failed"] == 1
    assert body["readable_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert body["messages_total"] == 30


def test_thong_ke_khi_chua_co_profile_nao_tra_null_khong_phai_0_phan_tram(client) -> None:
    """Hiện "0% đọc được" cho một mẫu rỗng là một lời nói sai."""
    body = client.get("/api/stats").json()
    assert body["profiles_total"] == 0
    assert body["readable_rate"] is None


# ---------------------------------------------------------------------------
# Tiến trình 6 bước
# ---------------------------------------------------------------------------
def test_job_khong_ton_tai_tra_404(client) -> None:
    assert client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 404


@pytest.mark.asyncio
async def test_job_dang_chay_co_ok_bang_null(setup, db_session) -> None:
    client, _ = setup
    job = await jobs.create_job_row(db_session, job_name=jobs.JOB_ANALYZE, summary={"url_key": "x"})
    await db_session.flush()

    body = client.get(f"/api/jobs/{job.id}").json()
    # `null` nghĩa "chưa biết". `false` trong suốt 70 giây sẽ là một lời nói sai.
    assert body["ok"] is None
    assert body["finished_at"] is None


@pytest.mark.asyncio
async def test_tien_trinh_duoc_ghi_vao_job_runs_doc_lai_duoc_qua_api(setup, db_session) -> None:
    client, _ = setup
    job = await jobs.create_job_row(db_session, job_name=jobs.JOB_ANALYZE, summary={"url_key": "x"})
    await db_session.flush()

    from app.services.progress import ProgressTracker, State

    tracker = ProgressTracker()
    tracker.mark(Step.COLLECT, State.DONE, "1 dữ kiện từ og_meta")
    tracker.mark(Step.IMAGES, State.SKIPPED, "không lấy được ảnh công khai nào")
    tracker.mark(Step.PROFILE, State.RUNNING)
    job.summary = {**job.summary, "steps": tracker.to_list()}
    await db_session.flush()

    steps = client.get(f"/api/jobs/{job.id}").json()["steps"]
    assert [s["step"] for s in steps] == [
        "collect",
        "images",
        "profile",
        "messages",
        "hook",
        "moderation",
    ]
    assert steps[0]["state"] == "done"
    assert steps[0]["label"] == "Thu thập"
    # `skipped` khác `failed`: trang không có ảnh thì không có gì để làm, đó không
    # phải lỗi. Gộp lại làm UI báo đỏ một kết quả đúng.
    assert steps[1]["state"] == "skipped"
    assert steps[2]["state"] == "running"
    assert steps[3]["state"] == "pending"


@pytest.mark.asyncio
async def test_job_that_bai_ghi_cau_tieng_viet_khong_ghi_stack_trace(
    setup, db_session, monkeypatch
) -> None:
    """Job nền raise thì exception chỉ nằm trong `Task.exception()` — không ai đọc.

    Test này dùng **session thật** (không phải fixture rollback): job nền cố ý
    mở session riêng, nên hàng `job_runs` phải thật sự được commit mới thấy
    được từ bên trong job. Dọn tay ở `finally`.
    """
    from app.models import JobRun as JobRunModel

    # `get_sessionmaker()` của app đọc `DATABASE_URL` trong `.env`, mà biến đó
    # trỏ hostname `db` của Docker → chạy từ host thì `getaddrinfo failed`
    # (đúng task.md I-20). Dựng sessionmaker riêng trỏ về DB test, và vá vào
    # module `jobs` để job nền dùng đúng nó.
    maker = _real_sessionmaker()
    monkeypatch.setattr("app.services.jobs.get_sessionmaker", lambda: maker)
    async with maker() as s:
        row = JobRunModel(job_name=jobs.JOB_ANALYZE, summary={"url_key": "job-that-bai"})
        s.add(row)
        await s.commit()
        job_id = row.id

    async def _explode(*args, **kwargs):
        raise RuntimeError("chi-tiet-ky-thuat-khong-duoc-lo")

    monkeypatch.setattr("app.services.jobs.run_analysis", _explode)
    try:
        await jobs._run_analysis_job(
            job_id, url=URL, profile_text=None, use_playwright=False, n_messages=None
        )
        async with maker() as s:
            saved = await s.get(JobRunModel, job_id)
            assert saved is not None
            summary = saved.summary or {}

            # Lỗi phải thành dữ liệu UI đọc được, không phải exception chìm.
            assert saved.ok is False
            assert saved.finished_at is not None
            error = summary.get("error") or ""
            assert error
            assert "chi-tiet-ky-thuat-khong-duoc-lo" not in error
            assert "RuntimeError" in error  # chỉ **loại** lỗi, để đối chiếu log
            assert "Traceback" not in json.dumps(summary)

            # Và bước đang dở được đánh `failed` để UI chỉ đúng chỗ gãy.
            failed = [s for s in summary.get("steps", []) if s["state"] == "failed"]
            assert len(failed) == 1
    finally:
        async with maker() as s:
            stale = await s.get(JobRunModel, job_id)
            if stale is not None:
                await s.delete(stale)
                await s.commit()


@pytest.mark.asyncio
async def test_job_nen_khong_bi_gc_thu_don_giua_duong() -> None:
    """`asyncio.create_task` không giữ task sống — không giữ reference thì job biến mất."""
    ran = asyncio.Event()

    async def _work(*args, **kwargs):
        await asyncio.sleep(0)
        ran.set()

    import app.services.jobs as jobs_module

    original = jobs_module._run_analysis_job
    jobs_module._run_analysis_job = _work
    try:
        jobs.start_analysis_job(
            uuid.uuid4(), url=URL, profile_text=None, use_playwright=False, n_messages=None
        )
        assert jobs_module._running, "task phải được giữ reference ngay sau khi tạo"
        await asyncio.wait_for(ran.wait(), timeout=2)
    finally:
        jobs_module._run_analysis_job = original
