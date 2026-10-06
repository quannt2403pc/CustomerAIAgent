"""D1.3 — log phải ra stderr và không bao giờ chứa secret."""

from __future__ import annotations

import logging
import sys

import pytest

from app.core.errors import GatewayAuthError, GatewayUnavailable
from app.core.logging import (
    SecretRedactingFilter,
    StderrHandler,
    redact,
    safe_repr,
    setup_logging,
)


@pytest.fixture
def fresh_logging():
    setup_logging("DEBUG", force=True)
    yield
    logging.getLogger().handlers.clear()


# --------------------------------------------------------------------------
# Che secret
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, leaked",
    [
        ('{"Authorization": "Bearer abc123"}', "abc123"),
        ("Authorization: Bearer abc123", "abc123"),
        ('{"x-goog-api-key": "AIzaSyFAKEKEY999"}', "AIzaSyFAKEKEY999"),
        ("secret-key: s3cr3tmgmt", "s3cr3tmgmt"),
        ("GET /v1beta/models?key=AIzaLEAK123", "AIzaLEAK123"),
        ("callback?code=4/0AX4&state=st_9f2", "4/0AX4"),
        ("callback?code=4/0AX4&state=st_9f2", "st_9f2"),
        ('{"google_api_key": "AIzaInDict"}', "AIzaInDict"),
        ("Cookie: c_user=100012345; xs=99%3Aabcd", "100012345"),
        ("Cookie: c_user=100012345; xs=99%3Aabcd", "99%3Aabcd"),
        ("token = ya29.LONGTOKENVALUE", "ya29.LONGTOKENVALUE"),
    ],
)
def test_redact_removes_secret(raw: str, leaked: str) -> None:
    cleaned = redact(raw)
    assert leaked not in cleaned
    assert "***" in cleaned


def test_redact_keeps_harmless_text() -> None:
    assert redact("Đang gọi model, chờ phản hồi") == "Đang gọi model, chờ phản hồi"


def test_filter_masks_message_and_clears_args(fresh_logging, capsys) -> None:
    logging.getLogger("t.filter").info("headers=%s", {"Authorization": "Bearer abc123"})
    err = capsys.readouterr().err
    assert "abc123" not in err
    assert "***" in err


def test_filter_masks_exception_text(fresh_logging, capsys) -> None:
    log = logging.getLogger("t.exc")
    try:
        raise ValueError("key=AIzaBOOM")
    except ValueError:
        log.exception("gọi cổng thất bại")
    err = capsys.readouterr().err
    assert "AIzaBOOM" not in err


def test_filter_returns_true_so_record_is_kept() -> None:
    record = logging.LogRecord("n", logging.INFO, "f", 1, "ok", None, None)
    assert SecretRedactingFilter().filter(record) is True


def test_safe_repr_masks_and_truncates() -> None:
    out = safe_repr({"api_key": "AIzaSECRET"}, limit=40)
    assert "AIzaSECRET" not in out
    assert len(out) <= 41


# --------------------------------------------------------------------------
# stdout dành riêng cho JSON của CLI
# --------------------------------------------------------------------------
def test_all_logs_go_to_stderr_stdout_stays_clean(fresh_logging, capsys) -> None:
    log = logging.getLogger("t.stream")
    for level in (log.debug, log.info, log.warning, log.error, log.critical):
        level("dòng log %s", "bất kỳ")

    sys.stdout.write('{"status":"SUCCESS"}')

    captured = capsys.readouterr()
    assert captured.out == '{"status":"SUCCESS"}'  # stdout chỉ có JSON
    assert captured.out.count("dòng log") == 0
    assert captured.err.count("dòng log") == 5


def test_setup_logging_installs_exactly_one_stderr_handler(fresh_logging) -> None:
    # pytest tự chèn LogCaptureHandler vào root nên chỉ đếm handler của app.
    ours = [h for h in logging.getLogger().handlers if isinstance(h, StderrHandler)]
    assert len(ours) == 1
    assert ours[0].stream is sys.stderr
    assert any(isinstance(f, SecretRedactingFilter) for f in ours[0].filters)


def test_stderr_handler_refuses_to_point_at_stdout(fresh_logging) -> None:
    handler = StderrHandler()
    handler.stream = sys.stdout  # mưu toan đổi hướng
    assert handler.stream is sys.stderr


# --------------------------------------------------------------------------
# Taxonomy lỗi
# --------------------------------------------------------------------------
def test_error_payload_has_only_code_and_message() -> None:
    err = GatewayAuthError()
    assert set(err.to_payload()) == {"code", "message"}


def test_detail_never_reaches_payload() -> None:
    err = GatewayUnavailable(detail="traceback đầy đủ + payload thô")
    assert "traceback" not in str(err.to_payload())
    assert err.detail is not None  # chỉ dành cho log server


def test_auth_error_and_unavailable_are_distinct_statuses() -> None:
    # Nhập nhèm 409 "chưa kết nối" với 503 "gọi không được" làm người vận hành đi sai hướng.
    assert GatewayAuthError.http_status == 409
    assert GatewayUnavailable.http_status == 503
