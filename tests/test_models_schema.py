"""D1.4 — lược đồ phải khớp plan.md §5.9 và giữ các ràng buộc của luật thép.

Test ở mức metadata (không cần Postgres) nên chạy được ở mọi máy; phần chạy
thật `upgrade head` / `downgrade base` đã kiểm chứng bằng Docker (xem Ghi chú D1.4).
"""

from __future__ import annotations

import pytest

from app.models import Base, OutboxItem, Profile, ProfileEvidence

EXPECTED_TABLES = {
    "llm_settings",
    "llm_credentials",
    "profiles",
    "profile_evidence",
    "rapport_runs",
    "rapport_messages",
    "evening_hooks",
    "outbox",
    "job_runs",
    "audit_log",
}


def test_all_ten_tables_declared() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_url_key_is_unique() -> None:
    # Cùng một người không được thành hai profile chỉ vì URL khác tham số rác.
    assert Profile.__table__.c.url_key.unique is True


@pytest.mark.parametrize(
    "column", ["customer_name", "visual_context", "demographics", "error_note"]
)
def test_profile_fact_columns_are_nullable(column: str) -> None:
    """Luật L1: không có evidence thì NULL, không được đoán → cột phải nullable."""
    assert Profile.__table__.c[column].nullable is True


def test_profile_created_at_index_is_descending() -> None:
    names = {ix.name for ix in Profile.__table__.indexes}
    assert "ix_profiles_created_at_desc" in names


def test_outbox_has_composite_index_for_due_drafts() -> None:
    target = next(
        ix for ix in OutboxItem.__table__.indexes if ix.name == "ix_outbox_status_scheduled_for"
    )
    assert [c.name for c in target.columns] == ["status", "scheduled_for"]


def test_outbox_has_no_auto_sent_status() -> None:
    """Luật L3 — không trạng thái nào mang nghĩa hệ thống đã tự gửi."""
    constraint = next(
        c for c in OutboxItem.__table__.constraints if c.name == "ck_outbox_status_known"
    )
    sql = str(constraint.sqltext)
    assert "sent_manually" in sql
    for forbidden in ("sent_auto", "auto_sent", "'sent'"):
        assert forbidden not in sql


def test_evidence_cascades_with_profile() -> None:
    # Xoá profile phải xoá bằng chứng kèm theo — PII không được sống sót mồ côi.
    fk = next(iter(ProfileEvidence.__table__.c.profile_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_llm_settings_has_no_hardcoded_model_default() -> None:
    """Luật L6 — danh mục model lấy lúc chạy, không chốt tên nào trong lược đồ."""
    default = Profile.__table__.c.status.default
    assert default is None  # status luôn do pipeline đặt tường minh

    from app.models import LlmSettings

    model_default = LlmSettings.__table__.c.model.default
    assert model_default is None or model_default.arg == ""
