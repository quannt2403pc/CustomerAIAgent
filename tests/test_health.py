"""D1.2 — `/health` phải luôn 200, kể cả khi phụ thuộc chết."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import engine as db_engine
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_ok_when_db_up(client, monkeypatch) -> None:
    monkeypatch.setattr(db_engine, "ping", _async_true)
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_still_200_when_db_down(client, monkeypatch) -> None:
    # Trả 503 ở đây sẽ làm orchestrator giết container, che mất đúng cái
    # người vận hành cần xem trên trang Cài đặt (task.md D1.2).
    monkeypatch.setattr(db_engine, "ping", _async_false)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["db"] == "unavailable"


def test_health_reports_no_provider_chosen_by_default(client, monkeypatch) -> None:
    monkeypatch.setattr(db_engine, "ping", _async_true)
    body = client.get("/health").json()
    assert body["provider"] is None  # plan.md §12.2 — không đoán hộ
    assert body["model"] is None
    assert body["dry_run"] is True  # luật L3


def test_docs_disabled_by_default(client) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False
