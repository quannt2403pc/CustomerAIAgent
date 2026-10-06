"""D1.5 — service `llm_credentials` chạm Postgres thật.

Skip nếu chưa có DB (xem tests/conftest.py).
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select

from app.core.logging import setup_logging
from app.models import LlmCredential
from app.services import credentials as svc

KEY = "AIzaSy-test-only-not-a-secret-9999"


async def test_save_then_read_round_trip(db_session) -> None:
    info = await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)
    assert info.is_set is True
    assert await svc.get_secret(db_session, svc.KIND_GOOGLE_API_KEY) == KEY


async def test_stored_column_is_ciphertext_not_plaintext(db_session) -> None:
    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)

    row = (
        await db_session.execute(
            select(LlmCredential).where(LlmCredential.kind == svc.KIND_GOOGLE_API_KEY)
        )
    ).scalar_one()
    assert KEY not in row.secret_enc
    assert row.secret_enc.startswith("gAAAAA")  # dấu hiệu token Fernet v1


async def test_describe_never_leaks_the_key(db_session) -> None:
    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)
    info = await svc.describe(db_session, svc.KIND_GOOGLE_API_KEY)

    assert info.is_set is True
    assert info.hint == "••••9999"
    assert KEY not in str(info)
    assert not hasattr(info, "secret_enc")


async def test_describe_when_nothing_saved(db_session) -> None:
    info = await svc.describe(db_session, svc.KIND_GOOGLE_API_KEY)
    assert info.is_set is False
    assert info.hint == ""


async def test_save_twice_updates_in_place(db_session) -> None:
    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)
    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, "AIza-test-only-second-0001")

    rows = (
        (
            await db_session.execute(
                select(LlmCredential).where(LlmCredential.kind == svc.KIND_GOOGLE_API_KEY)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1  # unique(kind) → upsert, không sinh hàng rác
    assert await svc.get_secret(db_session, svc.KIND_GOOGLE_API_KEY) == (
        "AIza-test-only-second-0001"
    )


async def test_delete_secret(db_session) -> None:
    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)
    assert await svc.delete_secret(db_session, svc.KIND_GOOGLE_API_KEY) is True
    assert await svc.get_secret(db_session, svc.KIND_GOOGLE_API_KEY) is None
    assert await svc.delete_secret(db_session, svc.KIND_GOOGLE_API_KEY) is False


async def test_empty_secret_is_refused(db_session) -> None:
    with pytest.raises(ValueError, match="rỗng"):
        await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, "   ")


@pytest.mark.parametrize("level", ["DEBUG", "INFO"])
async def test_no_plaintext_in_logs_at_any_level(db_session, capsys, level: str) -> None:
    setup_logging(level, force=True)
    logging.getLogger().setLevel(level)

    await svc.save_secret(db_session, svc.KIND_GOOGLE_API_KEY, KEY)
    await svc.get_secret(db_session, svc.KIND_GOOGLE_API_KEY)

    err = capsys.readouterr().err
    assert KEY not in err
    assert "9999" not in err  # kể cả hint cũng không vào log
