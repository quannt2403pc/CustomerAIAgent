"""D2.2 — API cổng model `/api/llm/*`.

Dùng `respx` giả cả CLIProxy và Google: endpoint phải được kiểm **qua HTTP thật
của app** (TestClient) chứ không chỉ gọi hàm, vì phần dễ sai nhất nằm ở tầng
router — mã HTTP, hình dạng response, và thứ **không** được có trong response.

DB: dùng fixture `db_session` (Postgres thật, rollback cuối test) và ghi đè
dependency `get_db_session` để app dùng đúng session đó. Không có Postgres thì
`db_session` tự `skip` — xem tests/conftest.py.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi.testclient import TestClient

from app.core.ratelimit import llm_test_rate_limit
from app.llm.catalog import get_catalog
from app.llm.resolver import get_active_config, set_model, set_provider
from app.main import create_app
from app.routers.deps import get_db_session
from app.services import credentials

CLIPROXY = "http://localhost:8317"
MGMT = f"{CLIPROXY}/v0/management"
GOOGLE = "https://generativelanguage.googleapis.com"

# Key giả, cố ý **không** giống định dạng key thật của Google để gitleaks không
# báo động và người đọc không nhầm đây là key bị lộ.
FAKE_API_KEY = "test-only-not-a-secret-google-key-1234"

# Danh mục giả: tên model **không** liên quan tới tên thật của bất kỳ nhà cung
# cấp nào — luật L6 cấm hardcode tên model trong `app/`, và test cũng không nên
# tạo thói quen đó.
MODELS_ANTIGRAVITY = {
    "models": [
        {
            "id": "model-doc-duoc-anh",
            "description": "Model giả có vision",
            "supportedInputModalities": ["text", "image"],
            "context_length": 100000,
            "max_completion_tokens": 8192,
        },
        {
            "id": "model-chi-chu",
            "description": "Model giả không vision",
            "supportedInputModalities": ["text"],
        },
    ]
}
MODELS_GOOGLE = {
    "models": [
        {
            "name": "models/model-cong-b",
            "displayName": "Model giả cổng B",
            "supportedGenerationMethods": ["generateContent"],
            "inputTokenLimit": 1000,
            "outputTokenLimit": 2000,
        },
        {
            "name": "models/model-chi-nhung",
            "displayName": "Model nhúng",
            "supportedGenerationMethods": ["embedContent"],
        },
    ]
}


def mock_auth_files(files: list[dict] | None = None):
    """`PUT /provider` trả luôn `/status`, mà `/status` đọc `auth-files` (bẫy B6).

    Nghĩa là mọi test chạm cổng A đều cần route này — kể cả test không nói gì về
    kết nối.
    """
    return respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"files": files if files is not None else []})
    )


def use_antigravity(client) -> None:
    mock_auth_files()
    respx.get(f"{MGMT}/model-definitions/antigravity").mock(
        return_value=httpx.Response(200, json=MODELS_ANTIGRAVITY)
    )
    client.put("/api/llm/provider", json={"provider": "antigravity"})


def use_google_api_key(client) -> None:
    """Cổng B cần **có key đã lưu**, nếu không `/models` trả 409 NOCRED."""
    respx.get(f"{GOOGLE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_GOOGLE))
    client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})
    client.put("/api/llm/provider", json={"provider": "google_api_key"})


@pytest_asyncio.fixture
async def client(db_session, monkeypatch) -> TestClient:
    monkeypatch.setenv("CLIPROXY_MGMT_KEY", "test-only-not-a-secret-mgmt")
    # Ghi đè tường minh: `.env` của repo trỏ `CLIPROXY_BASE_URL` vào hostname
    # `cliproxy` của Docker, nên test sẽ bám theo môi trường máy chạy nếu không
    # cố định ở đây.
    monkeypatch.setenv("CLIPROXY_BASE_URL", CLIPROXY)
    monkeypatch.setenv("GOOGLE_API_BASE_URL", GOOGLE)
    # `resolve_gateway` cố ý fallback về `GOOGLE_API_KEY` trong `.env` để CLI
    # chạy được không cần DB. Trong test thì fallback đó làm "chưa có key" trở
    # thành "có key thật của người dùng" — xoá đi để test đúng nhánh mình nói.
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    app = create_app()

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    llm_test_rate_limit.reset()
    get_catalog().invalidate()
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
def test_status_khi_chua_chon_cong_khong_bao_loi(client) -> None:
    """Trang Cài đặt phải mở được để người vận hành đi sửa — không 409 ở đây."""
    body = client.get("/api/llm/status").json()
    assert body["provider"] is None
    assert body["connected"] is False
    assert body["must_choose_model"] is True
    assert "Cài đặt" in body["detail"]
    assert body["api_key"] == {"is_set": False, "hint": "", "created_at": None}


@respx.mock
def test_status_doc_trang_thai_ket_noi_tu_auth_files(client) -> None:
    """Bẫy B6: `get-auth-status` không phải nguồn sự thật, `auth-files` mới là."""
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"name": "antigravity-nguoi@example.com.json"}]}
        )
    )
    client.put("/api/llm/provider", json={"provider": "antigravity"})

    body = client.get("/api/llm/status").json()
    assert body["provider"] == "antigravity"
    assert body["reachable"] is True
    assert body["connected"] is True
    assert body["account"] == "nguoi@example.com"


@respx.mock
def test_status_phan_biet_reachable_va_connected(client) -> None:
    """Cổng sống nhưng chưa đăng nhập ≠ cổng chết. Hai câu hướng dẫn khác nhau."""
    respx.get(f"{MGMT}/auth-files").mock(return_value=httpx.Response(200, json={"files": []}))
    client.put("/api/llm/provider", json={"provider": "antigravity"})

    body = client.get("/api/llm/status").json()
    assert body["reachable"] is True
    assert body["connected"] is False
    assert "Chưa có tài khoản Google" in body["detail"]


@respx.mock
def test_status_khi_cong_chet_thi_reachable_false(client) -> None:
    respx.get(f"{MGMT}/auth-files").mock(side_effect=httpx.ConnectError("cliproxy chết"))
    client.put("/api/llm/provider", json={"provider": "antigravity"})

    body = client.get("/api/llm/status").json()
    assert body["reachable"] is False
    assert body["connected"] is False


# ---------------------------------------------------------------------------
# PUT /provider — đổi cổng buộc chọn lại model
# ---------------------------------------------------------------------------
@respx.mock
def test_doi_cong_xoa_model_dang_chon_va_buoc_chon_lai(client, db_session) -> None:
    """Luật L6 + I-10: hai danh mục gần như rời nhau nên giữ model cũ là sai.

    DoD D2.2 "đổi cổng khi model không tương thích → 400 nói rõ phải chọn lại":
    chỗ trả 400 là **thao tác dùng model** sau khi đổi (xem test kế tiếp), còn
    bản thân việc đổi cổng phải thành công — nếu không thì không ai đổi được cổng.
    """
    use_antigravity(client)
    respx.get(f"{GOOGLE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_GOOGLE))
    client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})

    chosen = client.put("/api/llm/model", json={"model": "model-doc-duoc-anh"})
    assert chosen.status_code == 200
    assert chosen.json()["model"] == "model-doc-duoc-anh"
    assert chosen.json()["must_choose_model"] is False

    # Đổi sang cổng B: model của cổng A không còn ý nghĩa.
    switched = client.put("/api/llm/provider", json={"provider": "google_api_key"})
    assert switched.status_code == 200
    assert switched.json()["model"] is None
    assert switched.json()["must_choose_model"] is True


@respx.mock
def test_dung_model_cua_cong_khac_tra_400_neu_ten_ca_hai_cong_khong_trung(client) -> None:
    """Model của cổng A không có trong danh mục cổng B → 400 nêu cả model + cổng."""
    use_google_api_key(client)

    resp = client.put("/api/llm/model", json={"model": "model-doc-duoc-anh"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "E-LLM-400-MODEL"
    assert "model-doc-duoc-anh" in body["message"]
    assert "google_api_key" in body["message"]
    assert "chọn lại" in body["message"].lower()


# ---------------------------------------------------------------------------
# Cổng B — API key
# ---------------------------------------------------------------------------
@respx.mock
def test_luu_api_key_xac_thuc_truoc_khi_ghi_db(client, db_session) -> None:
    route = respx.get(f"{GOOGLE}/v1beta/models").mock(
        return_value=httpx.Response(200, json=MODELS_GOOGLE)
    )

    resp = client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})
    assert resp.status_code == 200
    assert route.called, "phải ping Google TRƯỚC khi ghi DB"

    body = resp.json()
    assert body["is_set"] is True
    assert body["hint"].endswith(FAKE_API_KEY[-4:])
    # Response không bao giờ mang key.
    assert FAKE_API_KEY not in resp.text


@respx.mock
def test_key_sai_khong_duoc_ghi_vao_db_va_khong_bi_echo(client) -> None:
    """Google báo key sai bằng **400** "API key not valid", không phải 401."""
    respx.get(f"{GOOGLE}/v1beta/models").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}
            },
        )
    )

    resp = client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})
    assert resp.status_code == 409  # GatewayAuthError
    assert FAKE_API_KEY not in resp.text

    # DB vẫn trống — không lưu key sai rồi để pipeline chết lúc 20h.
    assert client.get("/api/llm/api-key").json()["is_set"] is False


@respx.mock
def test_get_api_key_chi_tra_is_set_va_hint(client) -> None:
    respx.get(f"{GOOGLE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_GOOGLE))
    client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})

    resp = client.get("/api/llm/api-key")
    body = resp.json()
    assert set(body) == {"is_set", "hint", "created_at"}
    assert body["is_set"] is True
    assert FAKE_API_KEY not in resp.text
    assert "secret" not in resp.text.lower()


@respx.mock
def test_xoa_api_key(client) -> None:
    respx.get(f"{GOOGLE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_GOOGLE))
    client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})

    assert client.delete("/api/llm/api-key").json()["ok"] is True
    assert client.get("/api/llm/api-key").json()["is_set"] is False
    # Xoá lần hai nói thật là không có gì để xoá.
    assert "Chưa có API key" in client.delete("/api/llm/api-key").json()["message"]


# ---------------------------------------------------------------------------
# Danh mục model (luật L6)
# ---------------------------------------------------------------------------
@respx.mock
def test_danh_muc_cong_b_loc_model_khong_generate_content(client) -> None:
    use_google_api_key(client)

    body = client.get("/api/llm/models").json()
    ids = [m["id"] for m in body["models"]]
    assert ids == ["model-cong-b"]  # model embedding bị loại
    assert body["provider"] == "google_api_key"
    # I-15: danh mục ≠ model gọi được → response phải nhắc đi "Kiểm tra kết nối".
    assert "Kiểm tra kết nối" in body["note"]


@respx.mock
def test_co_vision_cong_a_la_du_lieu_that_cong_b_la_chua_biet(client) -> None:
    """I-06: cổng A có `supportedInputModalities`; cổng B **không** có cờ tương đương.

    Quy `None` về `False` sẽ chặn oan model đọc được ảnh; quy về `True` làm bước
    vision chết giữa pipeline. `None` là câu trả lời đúng.
    """
    use_antigravity(client)
    a = {m["id"]: m["supports_vision"] for m in client.get("/api/llm/models").json()["models"]}
    assert a == {"model-doc-duoc-anh": True, "model-chi-chu": False}

    use_google_api_key(client)
    b = {m["id"]: m["supports_vision"] for m in client.get("/api/llm/models").json()["models"]}
    assert b == {"model-cong-b": None}


@respx.mock
def test_danh_muc_khi_chua_chon_cong_tra_409(client) -> None:
    resp = client.get("/api/llm/models")
    assert resp.status_code == 409
    assert resp.json()["code"] == "E-LLM-409-NOCONF"


@respx.mock
def test_danh_muc_cong_b_khi_chua_co_key_tra_409_chu_khong_500(client) -> None:
    client.put("/api/llm/provider", json={"provider": "google_api_key"})
    resp = client.get("/api/llm/models")
    assert resp.status_code == 409
    assert resp.json()["code"] == "E-LLM-409-NOCRED"
    # Và nói rõ phải làm gì, không chỉ "lỗi".
    assert "API key" in resp.json()["message"]


@respx.mock
def test_refresh_bo_qua_cache(client) -> None:
    mock_auth_files()
    route = respx.get(f"{MGMT}/model-definitions/antigravity").mock(
        return_value=httpx.Response(200, json=MODELS_ANTIGRAVITY)
    )
    client.put("/api/llm/provider", json={"provider": "antigravity"})

    client.get("/api/llm/models")
    client.get("/api/llm/models")  # dùng cache
    assert route.call_count == 1

    client.get("/api/llm/models?refresh=true")
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# POST /test
# ---------------------------------------------------------------------------
@respx.mock
def test_test_tra_do_tre_va_khong_tra_json_tho_cua_model(client) -> None:
    use_antigravity(client)
    respx.post(f"{CLIPROXY}/v1beta/models/model-doc-duoc-anh:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "OK"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"totalTokenCount": 1234, "candidatesTokenCount": 2},
                "modelVersion": "bi-mat-noi-bo-khong-duoc-lo",
            },
        )
    )
    client.put("/api/llm/model", json={"model": "model-doc-duoc-anh"})

    resp = client.post("/api/llm/test")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"ok", "provider", "model", "latency_ms", "note"}
    assert body["ok"] is True
    assert body["model"] == "model-doc-duoc-anh"
    assert isinstance(body["latency_ms"], int)

    # Luật L5: không mẩu JSON thô nào của model lọt ra.
    assert "candidates" not in resp.text
    assert "usageMetadata" not in resp.text
    assert "bi-mat-noi-bo" not in resp.text


@respx.mock
def test_test_khi_chua_chon_model_tra_400_noi_ro_phai_chon(client) -> None:
    use_antigravity(client)

    resp = client.post("/api/llm/test")
    assert resp.status_code == 400
    assert resp.json()["code"] == "E-LLM-400-MODEL"
    assert "Chưa chọn model" in resp.json()["message"]


@respx.mock
def test_test_bat_duoc_model_co_trong_danh_muc_nhung_404_khi_goi(client) -> None:
    """I-15 — đúng lý do `POST /test` là **bắt buộc**, không phải tiện nghi.

    Câu gợi ý của Google phải được giữ nguyên: nó nói luôn nên dùng model nào
    thay thế. Tên model đó đến từ phản hồi **lúc chạy** → không vi phạm L6.
    """
    use_antigravity(client)
    respx.post(f"{CLIPROXY}/v1beta/models/model-chi-chu:generateContent").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "code": 404,
                    "message": (
                        "This model is no longer available to new users. "
                        "Please update your code to use model-thay-the."
                    ),
                }
            },
        )
    )
    client.put("/api/llm/model", json={"model": "model-chi-chu"})

    resp = client.post("/api/llm/test")
    assert resp.status_code == 400
    assert "model-thay-the" in resp.json()["message"]


@respx.mock
def test_test_bi_rate_limit_sau_khi_vuot_han_muc(client) -> None:
    """plan.md §7.4 — endpoint gọi model thật phải có hạn mức."""
    use_antigravity(client)
    respx.post(f"{CLIPROXY}/v1beta/models/model-doc-duoc-anh:generateContent").mock(
        return_value=httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
        )
    )
    client.put("/api/llm/model", json={"model": "model-doc-duoc-anh"})

    responses = [client.post("/api/llm/test") for _ in range(12)]
    codes = [r.status_code for r in responses]
    assert codes.count(200) == llm_test_rate_limit.limiter.limit
    assert 429 in codes

    blocked = next(r for r in responses if r.status_code == 429)
    # 429 của ta phải khác 429 "hết quota Google" để UI chỉ đúng việc cần làm.
    assert blocked.json()["code"] == "E-APP-429"
    assert "quá nhiều yêu cầu" in blocked.json()["message"]


# ---------------------------------------------------------------------------
# Luồng OAuth
# ---------------------------------------------------------------------------
@respx.mock
def test_luong_oauth_di_het_start_wait_ok(client) -> None:
    respx.get(f"{MGMT}/antigravity-auth-url").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "url": "https://accounts.google.com/o/oauth2/auth?x=1",
                "state": "st-123",
            },
        )
    )
    start = client.post("/api/llm/oauth/start")
    assert start.status_code == 200
    assert start.json()["state"] == "st-123"
    assert start.json()["url"].startswith("https://accounts.google.com/")

    respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(200, json={"status": "wait"})
    )
    waiting = client.get("/api/llm/oauth/status", params={"state": "st-123"})
    assert waiting.json()["status"] == "wait"
    assert waiting.json()["connected"] is False

    respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(
            200, json={"files": [{"name": "antigravity-nguoi@example.com.json"}]}
        )
    )
    done = client.get("/api/llm/oauth/status", params={"state": "st-123"})
    assert done.json() == {
        "status": "ok",
        "message": "Đã kết nối (nguoi@example.com).",
        "connected": True,
        "account": "nguoi@example.com",
    }


def test_oauth_status_bat_buoc_co_state(client) -> None:
    """Bẫy B6: thiếu `state`, CLIProxy trả `{"status":"ok"}` dù chưa đăng nhập bao giờ."""
    assert client.get("/api/llm/oauth/status").status_code == 400


@respx.mock
def test_oauth_status_loi_bao_bang_http_200_van_bi_bat(client) -> None:
    """Bẫy B7: `{"status":"error"}` kèm HTTP 200. Đọc theo status code sẽ tưởng xong."""
    respx.get(f"{MGMT}/get-auth-status").mock(
        return_value=httpx.Response(
            200, json={"status": "error", "error": "Failed to exchange token"}
        )
    )
    body = client.get("/api/llm/oauth/status", params={"state": "st-1"}).json()
    assert body["status"] == "error"
    assert body["connected"] is False
    # Câu tiếng Anh kỹ thuật của CLIProxy không được đổ ra UI.
    assert "Failed to exchange token" not in body["message"]


@respx.mock
def test_oauth_callback_du_phong_boc_code_khoi_url_nguoi_dung_dan(client) -> None:
    """I-08: CLIProxy nhận `{state, code}`, không nhận `url`."""
    route = respx.post(f"{MGMT}/oauth-callback").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    resp = client.post(
        "/api/llm/oauth/callback",
        json={
            "state": "st-9",
            "url": "http://localhost:51121/oauth-callback?state=st-9&code=ma-xac-thuc-gia",
        },
    )
    assert resp.status_code == 200
    sent = route.calls[0].request
    import json as _json

    assert _json.loads(sent.content) == {"state": "st-9", "code": "ma-xac-thuc-gia"}


@respx.mock
def test_oauth_callback_url_cua_phien_khac_bi_tu_choi(client) -> None:
    resp = client.post(
        "/api/llm/oauth/callback",
        json={"state": "st-moi", "url": "http://localhost:51121/oauth-callback?state=st-cu&code=x"},
    )
    # 400 chứ không 502: người dùng dán sai URL là lỗi **đầu vào**, không phải
    # cổng phía trên hỏng (task.md I-36).
    assert resp.status_code == 400
    assert "phiên đăng nhập khác" in resp.json()["message"]


@respx.mock
def test_huy_phien_oauth(client) -> None:
    respx.delete(f"{MGMT}/oauth-session").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    assert client.delete("/api/llm/oauth/session", params={"state": "st-1"}).json()["ok"] is True


@respx.mock
def test_ngat_ket_noi_xoa_tung_auth_file(client) -> None:
    """Bẫy B10: không có chế độ "xoá tất cả"; phải lấy danh sách rồi xoá từng file."""
    respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(200, json={"files": [{"name": "a.json"}, {"name": "b.json"}]})
    )
    deleted = respx.delete(f"{MGMT}/auth-files").mock(return_value=httpx.Response(200, json={}))

    resp = client.post("/api/llm/disconnect")
    assert resp.status_code == 200
    assert deleted.call_count == 2
    names = sorted(c.request.url.params["name"] for c in deleted.calls)
    assert names == ["a.json", "b.json"]


@respx.mock
def test_sai_management_key_tra_409_va_dung_mot_request(client) -> None:
    """Bẫy B3: sai key 5 lần → CLIProxy ban IP 30 phút. **Không được retry.**"""
    route = respx.get(f"{MGMT}/auth-files").mock(
        return_value=httpx.Response(401, json={"error": "invalid management key"})
    )
    resp = client.post("/api/llm/disconnect")
    assert resp.status_code == 409
    assert resp.json()["code"] == "E-LLM-409-AUTH"
    assert route.call_count == 1, "retry ở đây là tự khoá IP của chính mình"


# ---------------------------------------------------------------------------
# Không rò secret qua log
# ---------------------------------------------------------------------------
@respx.mock
def test_khong_log_api_key_va_khong_log_state(client, caplog) -> None:
    import logging

    respx.get(f"{GOOGLE}/v1beta/models").mock(return_value=httpx.Response(200, json=MODELS_GOOGLE))
    respx.get(f"{MGMT}/antigravity-auth-url").mock(
        return_value=httpx.Response(
            200, json={"status": "ok", "url": "https://accounts.google.com/x", "state": "st-bi-mat"}
        )
    )

    with caplog.at_level(logging.DEBUG):
        client.put("/api/llm/api-key", json={"api_key": FAKE_API_KEY})
        client.post("/api/llm/oauth/start")

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert FAKE_API_KEY not in joined
    assert "st-bi-mat" not in joined


# ---------------------------------------------------------------------------
# Resolver đọc DB mỗi lần — đổi cổng không cần restart
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_doi_cong_trong_db_co_hieu_luc_ngay(db_session) -> None:
    await set_provider(db_session, "antigravity")
    await set_model(db_session, "model-x")
    assert (await get_active_config(db_session)).provider == "antigravity"

    await set_provider(db_session, "google_api_key")
    config = await get_active_config(db_session)
    assert config.provider == "google_api_key"
    assert config.model == ""  # buộc chọn lại


@pytest.mark.asyncio
async def test_api_key_trong_db_la_ciphertext(db_session, fernet_env) -> None:
    """Luật L4/§7.2 — key không bao giờ ở dạng plaintext trong DB."""
    from sqlalchemy import select

    from app.models import LlmCredential

    await credentials.save_secret(db_session, credentials.KIND_GOOGLE_API_KEY, FAKE_API_KEY)
    row = (
        await db_session.execute(
            select(LlmCredential).where(LlmCredential.kind == credentials.KIND_GOOGLE_API_KEY)
        )
    ).scalar_one()
    assert FAKE_API_KEY not in row.secret_enc
    assert row.secret_enc.startswith("gAAAAA")
