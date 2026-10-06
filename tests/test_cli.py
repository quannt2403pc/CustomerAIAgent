"""D1.19 — CLI `main.py`.

Điều quan trọng nhất ở đây: **stdout chỉ có đúng một chuỗi JSON**, ở *mọi*
nhánh. Nếu một dòng log lọt vào stdout thì `python main.py … > output.json`
cho ra file không parse được — và đó là tiêu chí đầu tiên của đề bài.
"""

from __future__ import annotations

import json
import logging

import pytest

import main as cli
from app.core.errors import GatewayRateLimited, InvalidFacebookUrl
from app.schemas.output import EthicalRapport, StrictOutput
from app.services.pipeline import AnalysisOutcome

URL = "https://www.facebook.com/example_user"
TEN = [f"Tin {i} đủ dài để trông như tin nhắn thật." for i in range(1, 11)]


class FakeGateway:
    provider = "antigravity"

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def success_outcome() -> AnalysisOutcome:
    from app.collectors.evidence import EvidenceBundle

    return AnalysisOutcome(
        output=StrictOutput(
            status="SUCCESS",
            facebook_url=URL,
            ethical_rapport=EthicalRapport(
                core_empathy_angle="Tôn vinh sự tần tảo.",
                dialogue_sequence_10=TEN,
                sales_mention_check="ZERO_SALES_CONFIRMED",
            ),
        ),
        bundle=EvidenceBundle(url_key="user:example_user", facebook_url=URL),
    )


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Thay cả cổng model và pipeline — test CLI, không test lại pipeline."""
    gateway = FakeGateway()
    calls: dict[str, object] = {}

    async def fake_open(args):
        return gateway, "antigravity", args.model or "m", None

    async def fake_run(**kwargs):
        calls.update(kwargs)
        return success_outcome()

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)
    return calls, gateway


def run(argv: list[str]) -> int:
    return cli.main(argv)


# ---------------------------------------------------------------------------
# stdout chỉ có JSON — tiêu chí đầu tiên của đề bài
# ---------------------------------------------------------------------------
def test_stdout_is_exactly_one_json_object(stub_pipeline, capsys, tmp_path) -> None:
    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o.json")])

    captured = capsys.readouterr()
    assert code == 0
    # Đúng thao tác mà đề bài yêu cầu.
    parsed = json.loads(captured.out)
    assert parsed["status"] == "SUCCESS"


def test_logs_never_reach_stdout(stub_pipeline, capsys, tmp_path) -> None:
    """Nếu test này đỏ thì `main.py … > output.json` ra file không parse được."""
    logging.getLogger("app.services.pipeline").warning("một dòng log bất kỳ")

    run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o.json")])

    captured = capsys.readouterr()
    json.loads(captured.out)  # vẫn parse được
    assert "một dòng log" not in captured.out


def test_stdout_json_matches_the_written_file(stub_pipeline, capsys, tmp_path) -> None:
    path = tmp_path / "output.json"
    run(["--url", URL, "--model", "m", "--out", str(path)])

    from_stdout = json.loads(capsys.readouterr().out)
    from_file = json.loads(path.read_text(encoding="utf-8"))
    assert from_stdout == from_file


def test_file_is_written_even_with_default_name(
    stub_pipeline, capsys, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run(["--url", URL, "--model", "m"])
    capsys.readouterr()
    assert (tmp_path / "output.json").is_file()


def test_unwritable_output_path_still_prints_json(stub_pipeline, capsys, tmp_path) -> None:
    """stdout là hợp đồng chính — không ghi được tệp cũng không được mất JSON."""
    unwritable = tmp_path / "o.json"
    unwritable.mkdir()  # thư mục trùng tên → ghi tệp thất bại

    code = run(["--url", URL, "--model", "m", "--out", str(unwritable)])

    assert json.loads(capsys.readouterr().out)["status"] == "SUCCESS"
    assert code == 0


# ---------------------------------------------------------------------------
# Mọi nhánh lỗi vẫn in JSON hợp lệ
# ---------------------------------------------------------------------------
def test_no_input_gives_error_json_not_a_traceback(capsys, tmp_path) -> None:
    code = run(["--out", str(tmp_path / "o.json")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert body["status"] == "ERROR"
    assert "--url" in body["error_note"]


def test_invalid_url_gives_error_json(monkeypatch, capsys, tmp_path) -> None:
    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        raise InvalidFacebookUrl("`twitter.com` không phải domain Facebook.")

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    code = run(["--url", "https://twitter.com/x", "--model", "m", "--out", str(tmp_path / "o")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert body["status"] == "ERROR"
    assert "domain Facebook" in body["error_note"]


def test_gateway_error_gives_error_json(monkeypatch, capsys, tmp_path) -> None:
    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        raise GatewayRateLimited()

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "quota" in body["error_note"].lower()


def test_unexpected_exception_still_gives_json(monkeypatch, capsys, tmp_path) -> None:
    """Script gọi CLI không bao giờ phải xử lý "không có output"."""
    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        raise ZeroDivisionError("lỗi lập trình bất ngờ")

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert body["status"] == "ERROR"
    assert "ZeroDivisionError" in body["error_note"]


def test_gateway_is_closed_even_when_analysis_fails(monkeypatch, capsys, tmp_path) -> None:
    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        raise GatewayRateLimited()

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o")])
    capsys.readouterr()

    assert gateway.closed is True


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status, expected_code",
    [
        ("SUCCESS", 0),
        ("PARTIAL_OR_PRIVATE", 0),
        ("FAILED_VALIDATION", 1),
        ("ERROR", 1),
    ],
)
def test_exit_code_follows_status(monkeypatch, capsys, tmp_path, status, expected_code) -> None:
    from app.collectors.evidence import EvidenceBundle

    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        return AnalysisOutcome(
            output=StrictOutput(status=status, facebook_url=URL, error_note="ghi chú"),
            bundle=EvidenceBundle(url_key="k", facebook_url=URL),
        )

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o")])

    # Mọi nhánh đều in JSON hợp lệ, kể cả nhánh trả mã lỗi.
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert code == expected_code


# ---------------------------------------------------------------------------
# Cờ dòng lệnh
# ---------------------------------------------------------------------------
def test_mask_pii_hides_name_and_url(monkeypatch, capsys, tmp_path) -> None:
    from app.collectors.evidence import EvidenceBundle
    from app.schemas.output import ProfileData

    gateway = FakeGateway()

    async def fake_open(args):
        return gateway, "antigravity", "m", None

    async def fake_run(**kwargs):
        return AnalysisOutcome(
            output=StrictOutput(
                status="SUCCESS",
                facebook_url=URL,
                profile_data=ProfileData(customer_name="Nguyễn Thị Lan"),
                ethical_rapport=EthicalRapport(
                    dialogue_sequence_10=TEN, sales_mention_check="ZERO_SALES_CONFIRMED"
                ),
            ),
            bundle=EvidenceBundle(url_key="k", facebook_url=URL),
        )

    monkeypatch.setattr(cli, "_open_gateway", fake_open)
    monkeypatch.setattr("app.services.pipeline.run_analysis", fake_run)

    path = tmp_path / "o.json"
    run(["--url", URL, "--model", "m", "--mask-pii", "--out", str(path)])

    out = capsys.readouterr().out
    assert "Nguyễn Thị Lan" not in out
    assert "example_user" not in out
    assert "N*** T*** L***" in out
    # Tệp cũng phải là bản đã che, không chỉ stdout.
    assert "Nguyễn Thị Lan" not in path.read_text(encoding="utf-8")


def test_profile_file_is_read_and_passed_through(stub_pipeline, capsys, tmp_path) -> None:
    calls, _ = stub_pipeline
    paste = tmp_path / "paste.txt"
    paste.write_text("Tên: Nguyễn Thị Lan\nTiểu sử: Mẹ hai bé", encoding="utf-8")

    run(["--profile-file", str(paste), "--model", "m", "--out", str(tmp_path / "o.json")])
    capsys.readouterr()

    assert "Nguyễn Thị Lan" in calls["profile_text"]
    assert calls["url"] is None


def test_messages_flag_is_passed_through(stub_pipeline, capsys, tmp_path) -> None:
    calls, _ = stub_pipeline

    run(["--url", URL, "--model", "m", "--messages", "6", "--out", str(tmp_path / "o.json")])
    capsys.readouterr()

    assert calls["n_messages"] == 6


def test_model_flag_overrides(stub_pipeline, capsys, tmp_path) -> None:
    calls, _ = stub_pipeline

    run(["--url", URL, "--model", "mo-hinh-cu-the", "--out", str(tmp_path / "o.json")])
    capsys.readouterr()

    assert calls["model"] == "mo-hinh-cu-the"


# ---------------------------------------------------------------------------
# Luật L6 — không có model mặc định trong source
# ---------------------------------------------------------------------------
def test_missing_model_is_an_actionable_error() -> None:
    from app.core.errors import GatewayModelInvalid

    with pytest.raises(GatewayModelInvalid) as exc:
        cli._require_model(None, "antigravity")

    message = str(exc.value)
    assert "--model" in message
    assert "không có giá trị mặc định" in message


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_model_is_refused(value: str) -> None:
    from app.core.errors import GatewayModelInvalid

    with pytest.raises(GatewayModelInvalid):
        cli._require_model(value, "google_api_key")


def test_given_model_is_trimmed() -> None:
    assert cli._require_model("  gemini-x  ", "antigravity") == "gemini-x"


def test_no_db_without_provider_says_what_to_do() -> None:
    from app.core.errors import GatewayNotConfigured

    with pytest.raises(GatewayNotConfigured, match="--provider"):
        cli._gateway_without_db("")


def test_no_db_google_without_key_says_what_to_do(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.core.errors import GatewayNoCredential

    monkeypatch.setenv("GOOGLE_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(GatewayNoCredential, match="GOOGLE_API_KEY"):
        cli._gateway_without_db("google_api_key")


# ---------------------------------------------------------------------------
# Lỗi hạ tầng lúc khởi tạo cũng phải ra JSON
# ---------------------------------------------------------------------------
def test_database_unreachable_still_prints_json(monkeypatch, capsys, tmp_path) -> None:
    """Đã gặp thật: `.env` trỏ `DATABASE_URL` vào host `db` của Docker nên chạy
    CLI ngoài Docker làm psycopg nổ `OperationalError`.

    Đó **không** phải `AppError`, nên trước khi sửa nó thoát ra ngoài và CLI
    không in JSON nào — phá đúng hợp đồng chính (task.md I-20).
    """
    from sqlalchemy.exc import OperationalError

    async def fake_open(args):
        raise OperationalError("SELECT 1", {}, Exception("getaddrinfo failed"))

    monkeypatch.setattr(cli, "_open_gateway", fake_open)

    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o.json")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert body["status"] == "ERROR"
    assert "--no-db" in body["error_note"]
    assert "DATABASE_URL" in body["error_note"]


def test_any_setup_exception_still_prints_json(monkeypatch, capsys, tmp_path) -> None:
    async def fake_open(args):
        raise RuntimeError("một lỗi hạ tầng lạ")

    monkeypatch.setattr(cli, "_open_gateway", fake_open)

    code = run(["--url", URL, "--model", "m", "--out", str(tmp_path / "o.json")])

    body = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "RuntimeError" in body["error_note"]
