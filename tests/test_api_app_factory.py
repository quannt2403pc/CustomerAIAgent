"""D2.1 — app factory: handler lỗi `{code,message}`, security headers, CORS, `/docs`.

Trọng tâm là **những gì KHÔNG được xuất hiện** trong response: stack trace, tên
file nguồn, payload người dùng gửi lên. Test theo hướng đó vì đây là lỗ rò kinh
điển — một `JSONResponse(content=exc.errors())` là đủ để API tự khai cả Google
API key người dùng vừa dán.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import GatewayNoCredential, GatewayRateLimited
from app.core.middleware import SECURITY_HEADERS
from app.core.ratelimit import RateLimited, SlidingWindowLimiter
from app.db import engine as db_engine
from app.main import create_app


class _Body(BaseModel):
    secret_field: str


def _app_with_probes() -> FastAPI:
    """App thật + vài route chỉ tồn tại trong test để gây lỗi có kiểm soát.

    Cố ý **không** thêm route gây lỗi vào `create_app()`: một endpoint
    `/debug/boom` trong bản production là một đường tấn công DoS miễn phí.
    """
    app = create_app()

    @app.get("/probe/boom")
    async def _boom() -> dict:
        raise RuntimeError("mật khẩu-siêu-bí-mật-không-được-lọt-ra-response")

    @app.get("/probe/app-error")
    async def _app_error() -> dict:
        raise GatewayNoCredential()

    @app.post("/probe/validate")
    async def _validate(body: _Body) -> dict:
        return {"ok": body.secret_field}

    return app


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(db_engine, "ping", _async_true)
    # raise_server_exceptions=False → TestClient đi qua handler thật thay vì
    # ném exception ra ngoài, đúng thứ cần kiểm.
    return TestClient(_app_with_probes(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Handler lỗi
# ---------------------------------------------------------------------------
def test_loi_500_chi_tra_code_va_message(client, caplog) -> None:
    with caplog.at_level(logging.ERROR):
        resp = client.get("/probe/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "E-APP-500"

    # Thân response không được chứa bất cứ dấu vết kỹ thuật nào.
    raw = resp.text
    for leak in ("mật khẩu-siêu-bí-mật", "RuntimeError", "Traceback", "app/", "line "):
        assert leak not in raw, f"response rò {leak!r}"


def test_chi_tiet_loi_500_nam_trong_log_server(client, caplog) -> None:
    """Chi tiết không mất đi — nó chuyển sang log, nơi có bộ lọc che secret."""
    with caplog.at_level(logging.ERROR):
        client.get("/probe/boom")

    joined = "\n".join(record.getMessage() for record in caplog.records) + "\n".join(
        record.exc_text or "" for record in caplog.records if hasattr(record, "exc_text")
    )
    assert "/probe/boom" in joined


def test_app_error_giu_nguyen_http_status_va_cau_tieng_viet(client) -> None:
    resp = client.get("/probe/app-error")
    assert resp.status_code == 409  # không phải 500
    body = resp.json()
    assert body["code"] == "E-LLM-409-NOCRED"
    assert "Đăng nhập Google" in body["message"]


def test_loi_validate_khong_echo_gia_tri_nguoi_dung_gui(client) -> None:
    """Lỗ rò kinh điển: `exc.errors()` của Pydantic mang cả `input`.

    Với `PUT /api/llm/api-key` thì `input` **chính là** Google API key.
    """
    resp = client.post("/probe/validate", json={"secret_field": 12345, "AIzaFakeKeyValue": "x"})

    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"code", "message"}
    assert "secret_field" in body["message"]  # tên field thì được
    assert "AIzaFakeKeyValue" not in resp.text  # giá trị thì không
    assert "12345" not in resp.text
    assert "int_parsing" not in resp.text  # cả mã lỗi nội bộ của Pydantic


def test_404_va_405_cung_dang_code_message(client) -> None:
    not_found = client.get("/khong-ton-tai")
    assert not_found.status_code == 404
    assert set(not_found.json()) == {"code", "message"}
    assert not_found.json()["code"] == "E-APP-404"

    wrong_method = client.post("/health")
    assert wrong_method.status_code == 405
    assert set(wrong_method.json()) == {"code", "message"}


def test_moi_loi_cong_model_anh_xa_dung_http_status() -> None:
    """Taxonomy §5.1.5: 409 'chưa cấu hình' phải khác 503 'gọi không được'."""
    assert GatewayNoCredential().http_status == 409
    assert GatewayRateLimited().http_status == 429
    assert RateLimited().http_status == 429
    # Hai cái 429 nhưng `code` khác nhau — UI cần phân biệt "bạn bấm nhanh quá"
    # với "hết quota của Google".
    assert RateLimited().code != GatewayRateLimited().code


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------
def test_security_headers_co_tren_response_thanh_cong(client) -> None:
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"


def test_security_headers_co_ca_tren_response_loi(client) -> None:
    """Header thiếu ở nhánh lỗi là lỗ hổng thật: trang lỗi cũng bị nhúng iframe được."""
    resp = client.get("/probe/boom")
    for name, value in SECURITY_HEADERS.items():
        assert resp.headers.get(name) == value, f"nhánh lỗi thiếu header {name}"


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
def test_cors_chi_cho_origin_trong_whitelist(client) -> None:
    allowed = get_settings().cors_origin_list[0]
    ok = client.get("/health", headers={"Origin": allowed})
    assert ok.headers.get("access-control-allow-origin") == allowed

    blocked = client.get("/health", headers={"Origin": "https://ke-xau.example.com"})
    assert "access-control-allow-origin" not in blocked.headers


def test_cors_khong_bao_gio_la_dau_sao(client) -> None:
    """plan.md §7.4: `allow_origins=["*"]` là điều bị cấm tường minh."""
    resp = client.get("/health", headers={"Origin": get_settings().cors_origin_list[0]})
    assert resp.headers.get("access-control-allow-origin") != "*"
    # Và không bật credentials khi không cần.
    assert "access-control-allow-credentials" not in resp.headers


# ---------------------------------------------------------------------------
# /docs
# ---------------------------------------------------------------------------
def test_docs_tat_mac_dinh(client) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_docs_bat_duoc_khi_can(monkeypatch) -> None:
    """Tắt mặc định nhưng phải bật được — nếu không thì không ai kiểm chứng được API."""
    monkeypatch.setenv("DOCS_ENABLED", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        assert c.get("/docs").status_code == 200


# ---------------------------------------------------------------------------
# Rate limit (hạ tầng cho D2.2 / D2.3, nghiệm thu ở D2.12)
# ---------------------------------------------------------------------------
def test_sliding_window_chan_dung_sau_khi_het_han_muc() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60.0, clock=lambda: now[0])

    for _ in range(3):
        limiter.check("ip-1")

    with pytest.raises(RateLimited) as err:
        limiter.check("ip-1")
    assert "60s" in err.value.message

    # Khoá khác không bị ảnh hưởng.
    limiter.check("ip-2")


def test_sliding_window_mo_lai_khi_cua_so_truot_qua() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10.0, clock=lambda: now[0])
    limiter.check("ip")
    limiter.check("ip")
    with pytest.raises(RateLimited):
        limiter.check("ip")

    now[0] = 10.0  # cửa sổ đã trượt hết
    limiter.check("ip")  # không raise


def test_sliding_window_khong_phinh_bo_nho_theo_thoi_gian() -> None:
    """Không dọn mốc cũ thì deque phình vô hạn theo thời gian chạy của tiến trình."""
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window_seconds=5.0, clock=lambda: now[0])
    for step in range(100):
        now[0] = step * 10.0
        limiter.check("ip")
    assert len(limiter._hits["ip"]) == 1


def test_retry_after_noi_dung_so_giay_con_phai_cho() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=1, window_seconds=30.0, clock=lambda: now[0])
    limiter.check("ip")
    now[0] = 10.0
    assert limiter.retry_after("ip") == 20
    now[0] = 30.0
    assert limiter.retry_after("ip") == 0


async def _async_true() -> bool:
    return True
