"""D1.3 — cấu hình phải nổ sớm và rõ khi thiếu thứ bắt buộc."""

from __future__ import annotations

import pytest

from app.core.config import ConfigError, Settings


def _settings(**overrides) -> Settings:
    base = {"_env_file": None}
    return Settings(**base, **overrides)


def test_defaults_do_not_choose_a_provider() -> None:
    # plan.md §12.2: lần cài đầu phải là "chưa chọn", không đoán hộ người dùng.
    assert _settings().llm_provider == ""
    assert _settings().llm_model == ""


def test_dry_run_defaults_true() -> None:
    assert _settings().dry_run is True  # luật L3


def test_require_encryption_key_raises_when_missing() -> None:
    with pytest.raises(ConfigError) as exc:
        _settings(app_encryption_key="").require_encryption_key()
    assert "APP_ENCRYPTION_KEY" in str(exc.value)


def test_require_encryption_key_rejects_placeholder() -> None:
    # Giá trị mẫu trong .env.example không được coi là khoá thật.
    with pytest.raises(ConfigError):
        _settings(app_encryption_key="SINH-NGAU-NHIEN").require_encryption_key()


def test_require_encryption_key_returns_real_value() -> None:
    assert _settings(app_encryption_key="test-only-not-a-secret").require_encryption_key() == (
        "test-only-not-a-secret"
    )


def test_require_cliproxy_mgmt_key_mentions_trap_b4() -> None:
    with pytest.raises(ConfigError) as exc:
        _settings(cliproxy_mgmt_key="").require_cliproxy_mgmt_key()
    assert "404" in str(exc.value)


def test_invalid_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        _settings(llm_provider="openai")


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        _settings(log_level="verbose")


def test_log_level_is_normalised_to_upper() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_cors_origin_list_splits_and_trims() -> None:
    s = _settings(cors_origins="http://a:1 , http://b:2,")
    assert s.cors_origin_list == ["http://a:1", "http://b:2"]


def test_rapport_message_count_bounded_to_brief_range() -> None:
    # Đề bài cho 5–10 tin; ngoài khoảng là sai đặc tả.
    with pytest.raises(ValueError):
        _settings(rapport_message_count=11)
    with pytest.raises(ValueError):
        _settings(rapport_message_count=4)
