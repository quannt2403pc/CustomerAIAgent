"""D1.2 / D1.7 — những ràng buộc của docker-compose.yml phải được canh gác.

Đây là các bẫy đã mất thời gian ở dự án trước (plan.md §5.1.2 B1, B2, B8) và
một yêu cầu vận hành (api phải lên được khi cliproxy chết). Để lại dưới dạng
test thì lần sửa compose sau không âm thầm phá chúng.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

COMPOSE = pathlib.Path(__file__).resolve().parents[1] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_api_does_not_wait_for_cliproxy_health(compose) -> None:
    """cliproxy chết thì api vẫn phải lên, để trang Cài đặt hiện được 'Chưa kết nối'."""
    depends = compose["services"]["api"].get("depends_on") or {}
    cliproxy_dep = depends.get("cliproxy")
    if cliproxy_dep is None:
        return  # chưa khai báo phụ thuộc — đã thoả yêu cầu
    assert cliproxy_dep.get("condition") == "service_started", (
        "api không được dùng `service_healthy` cho cliproxy: cliproxy chết sẽ "
        "chặn api lên, che mất trang Cài đặt."
    )


def test_api_waits_for_db_health(compose) -> None:
    # Ngược lại với cliproxy: không có db thì migration chết, phải chờ healthy.
    assert compose["services"]["api"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_db_has_healthcheck(compose) -> None:
    assert "healthcheck" in compose["services"]["db"]


def test_pgdata_is_a_named_volume(compose) -> None:
    assert "pgdata" in compose["volumes"]
    assert any(v.startswith("pgdata:") for v in compose["services"]["db"]["volumes"])


# ---------------------------------------------------------------------------
# cliproxy (D1.7)
# ---------------------------------------------------------------------------
def test_cliproxy_publishes_oauth_callback_port(compose) -> None:
    """Bẫy B1: Google redirect về http://localhost:51121/oauth-callback.

    Thiếu port này thì trình duyệt báo lỗi và token OAuth không bao giờ được lưu.
    """
    ports = compose["services"]["cliproxy"]["ports"]
    published = {str(p).split(":")[0] for p in ports}
    assert "8317" in published
    assert "51121" in published


def test_cliproxy_mounts_directory_not_the_config_file(compose) -> None:
    """Bẫy B8 / I-05: mount thẳng file chưa tồn tại → Docker tạo THƯ MỤC trùng tên.

    `cliproxy-init` KHÔNG cứu được vì compose phân giải bind-mount lúc *tạo*
    container, trước khi init chạy. Phải mount cả thư mục.
    """
    mounts = compose["services"]["cliproxy"]["volumes"]
    assert not any(
        "config.yaml:" in str(m) for m in mounts
    ), "Không mount riêng config.yaml — xem task.md I-05."
    assert any(str(m).startswith("./cliproxy:") for m in mounts)
    assert "-config" in compose["services"]["cliproxy"]["command"]


def test_cliproxy_auth_dir_is_a_named_volume(compose) -> None:
    # Token OAuth phải sống qua restart, nếu không người dùng đăng nhập lại mỗi lần.
    assert "cliproxy_auths" in compose["volumes"]
    assert any(
        str(m).startswith("cliproxy_auths:") for m in compose["services"]["cliproxy"]["volumes"]
    )


def test_cliproxy_init_runs_before_cliproxy(compose) -> None:
    dep = compose["services"]["cliproxy"]["depends_on"]["cliproxy-init"]
    assert dep["condition"] == "service_completed_successfully"
