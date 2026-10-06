"""X.2 — cookie Facebook của chính người vận hành.

Vì sao cần (task.md I-33, đo đối chứng cùng trang cùng lúc): một bài viết
**Công khai** vẫn bị che với khách chưa đăng nhập. Cùng bài đó, một tài khoản
lạ **đã đăng nhập** thì đọc được đủ nội dung.

Điều được canh gác chặt nhất: cookie **không bao giờ** lọt vào log hay response.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from app.collectors import facebook_cookie as fb
from app.collectors import mbasic
from app.collectors.evidence import EvidenceBundle
from app.collectors.url import normalize_facebook_url
from app.core.errors import CollectorError
from app.core.logging import setup_logging

# Giá trị giả, có dạng thật. `xs` thật là token phiên nên ở đây dùng chuỗi đánh dấu.
VALID = "c_user=100012345678901; xs=99%3Atest-only-not-a-secret%3A2; datr=abcdef; sb=ghijk"


# ---------------------------------------------------------------------------
# Bóc & kiểm hình dạng
# ---------------------------------------------------------------------------
def test_parses_a_devtools_cookie_header() -> None:
    pairs = fb.parse(VALID)
    assert pairs["c_user"] == "100012345678901"
    assert set(pairs) == {"c_user", "xs", "datr", "sb"}


def test_parses_across_line_breaks() -> None:
    """Người ta hay copy kèm ngắt dòng mà không để ý."""
    pairs = fb.parse("c_user=100012345678901;\n  xs=99%3Aabc;\n datr=xyz")
    assert set(pairs) == {"c_user", "xs", "datr"}


def test_valid_cookie_reports_a_masked_account() -> None:
    info = fb.validate(VALID)
    assert info.account_id == "100012345678901"
    assert info.masked_account == "••••8901"
    assert "100012345678901" not in info.masked_account


@pytest.mark.parametrize("raw", ["", "   ", "không phải cookie"])
def test_unparseable_input_says_where_to_find_it(raw: str) -> None:
    with pytest.raises(CollectorError) as exc:
        fb.validate(raw)
    assert "DevTools" in str(exc.value)


@pytest.mark.parametrize(
    "raw, missing",
    [
        ("xs=99%3Aabc; datr=x", "c_user"),
        ("c_user=100012345678901; datr=x", "xs"),
        ("datr=x; sb=y", "c_user"),
    ],
)
def test_missing_required_cookie_names_what_is_missing(raw: str, missing: str) -> None:
    """Thiếu `c_user`/`xs` thì không đăng nhập được — báo ngay, đừng để
    pipeline chạy xong rồi thất bại im lặng."""
    with pytest.raises(CollectorError) as exc:
        fb.validate(raw)
    assert missing in str(exc.value)


def test_non_numeric_account_id_is_refused() -> None:
    with pytest.raises(CollectorError, match="dãy số"):
        fb.validate("c_user=khong-phai-so; xs=99%3Aabc")


# ---------------------------------------------------------------------------
# Lọc bớt cookie của site khác
# ---------------------------------------------------------------------------
def test_header_keeps_only_facebook_cookies() -> None:
    """Người dùng có thể lỡ copy cookie của cả trình duyệt — không mang theo
    dữ liệu của site khác vào request."""
    header = fb.to_header(
        "c_user=1; xs=2; datr=3; _ga=UA-GOOGLE-ANALYTICS; session_id_cua_site_khac=xyz"
    )

    assert "c_user=1" in header
    assert "xs=2" in header
    assert "datr=3" in header
    assert "_ga" not in header
    assert "site_khac" not in header


def test_header_order_is_stable() -> None:
    assert fb.to_header("datr=3; xs=2; c_user=1") == "c_user=1; xs=2; datr=3"


# ---------------------------------------------------------------------------
# Cảnh báo rủi ro
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("phrase", ["khoá tài khoản", "chính bạn", "mã hoá"])
def test_risk_warning_states_the_real_risk(phrase: str) -> None:
    """Người vận hành phải biết rủi ro **trước** khi quyết định, không phải sau."""
    assert phrase in fb.RISK_WARNING


def test_risk_warning_forbids_borrowing_someone_elses_account() -> None:
    assert "người khác" in fb.RISK_WARNING


# ---------------------------------------------------------------------------
# Không bao giờ lọt vào log
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("level", ["DEBUG", "INFO"])
def test_cookie_value_never_reaches_the_log(capsys, level: str) -> None:
    setup_logging(level, force=True)
    logging.getLogger().setLevel(level)

    fb.validate(VALID)

    err = capsys.readouterr().err
    assert "100012345678901" not in err
    assert "test-only-not-a-secret" not in err
    # Tên cookie thì được — nó giúp chẩn đoán mà không lộ gì.
    assert "c_user" in err


def test_cookie_info_has_no_field_holding_the_value() -> None:
    info = fb.validate(VALID)
    assert "test-only-not-a-secret" not in str(info)
    assert not hasattr(info, "value")
    assert not hasattr(info, "raw")


# ---------------------------------------------------------------------------
# Kiểm cookie còn sống
# ---------------------------------------------------------------------------
@respx.mock
async def test_live_cookie_is_detected() -> None:
    respx.get("https://mbasic.facebook.com/").mock(
        return_value=httpx.Response(200, text="<html>Bảng feed của bạn</html>")
    )
    async with httpx.AsyncClient() as client:
        assert await fb.check_alive(VALID, client=client) is True


@respx.mock
async def test_expired_cookie_is_detected() -> None:
    respx.get("https://mbasic.facebook.com/").mock(
        return_value=httpx.Response(200, text="<html>Đăng nhập vào Facebook</html>")
    )
    async with httpx.AsyncClient() as client:
        assert await fb.check_alive(VALID, client=client) is False


@respx.mock
async def test_network_failure_counts_as_not_alive() -> None:
    """Không kiểm chứng được thì **không** được coi là còn sống."""
    respx.get("https://mbasic.facebook.com/").mock(side_effect=httpx.ConnectError("mất mạng"))
    async with httpx.AsyncClient() as client:
        assert await fb.check_alive(VALID, client=client) is False


@respx.mock
async def test_check_alive_sends_only_facebook_cookies() -> None:
    route = respx.get("https://mbasic.facebook.com/").mock(
        return_value=httpx.Response(200, text="<html>feed</html>")
    )
    async with httpx.AsyncClient() as client:
        await fb.check_alive(f"{VALID}; _ga=UA-GOOGLE", client=client)

    sent = route.calls[0].request.headers["cookie"]
    assert "_ga" not in sent


# ---------------------------------------------------------------------------
# Cookie đi tới cả hai lớp đọc chữ
# ---------------------------------------------------------------------------
@respx.mock
async def test_mbasic_receives_the_cookie() -> None:
    target = normalize_facebook_url("https://www.facebook.com/vander.374801")
    bundle = EvidenceBundle(url_key=target.url_key, facebook_url=target.canonical_url)
    route = respx.get(target.mbasic_url).mock(
        return_value=httpx.Response(200, text="<html><h1>Vander</h1></html>")
    )

    async with httpx.AsyncClient() as client:
        await mbasic.collect(target, bundle, client=client, cookie=fb.to_header(VALID))

    assert "c_user=100012345678901" in route.calls[0].request.headers["cookie"]


async def test_pipeline_passes_the_cookie_to_both_text_layers(monkeypatch) -> None:
    """L2 `mbasic` và L3 Playwright **đều** phải nhận cookie.

    Chỉ nối một lớp là mất nửa lợi ích mà vẫn chịu nguyên rủi ro.
    """
    from app.services import pipeline

    seen: dict[str, str | None] = {}

    async def fake_mbasic(target, bundle, **kwargs):
        seen["mbasic"] = kwargs.get("cookie")
        return bundle

    async def fake_playwright(target, bundle, **kwargs):
        seen["playwright"] = kwargs.get("cookie")
        return bundle

    async def fake_og(target, bundle, **kwargs):
        return bundle

    monkeypatch.setattr(pipeline.mbasic, "collect", fake_mbasic)
    monkeypatch.setattr(pipeline.playwright_dom, "collect", fake_playwright)
    monkeypatch.setattr(pipeline.og_meta, "collect", fake_og)

    class Gateway:
        provider = "antigravity"

        async def list_models(self):
            return []

        async def generate_content(self, payload, *, model):
            raise AssertionError("không nên gọi model trong test này")

    await pipeline.run_analysis(
        gateway=Gateway(),
        model="m",
        url="https://www.facebook.com/vander.374801",
        playwright_enabled=True,
        facebook_cookie="c_user=1; xs=2",
    )

    assert seen["mbasic"] == "c_user=1; xs=2"
    assert seen["playwright"] == "c_user=1; xs=2"
