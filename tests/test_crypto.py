"""D1.5 — Fernet round-trip, không fallback plaintext, không lộ secret vào log."""

from __future__ import annotations

import base64
import logging

import pytest

from app.core import crypto
from app.core.config import ConfigError, get_settings
from app.core.errors import CryptoError
from app.core.logging import setup_logging

SECRET = "AIza-test-only-not-a-secret-1234"


def test_round_trip(fernet_env) -> None:
    assert crypto.decrypt(crypto.encrypt(SECRET)) == SECRET


def test_ciphertext_does_not_contain_plaintext(fernet_env) -> None:
    assert SECRET not in crypto.encrypt(SECRET)


def test_two_encryptions_differ(fernet_env) -> None:
    # Fernet nhúng IV + timestamp → cùng plaintext ra ciphertext khác nhau.
    assert crypto.encrypt(SECRET) != crypto.encrypt(SECRET)


def test_missing_key_raises_instead_of_storing_plaintext(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    crypto.reset_cache()

    with pytest.raises(ConfigError) as exc:
        crypto.encrypt(SECRET)
    assert "APP_ENCRYPTION_KEY" in str(exc.value)


def test_malformed_key_gives_actionable_message(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "khong-phai-base64-32-byte")
    get_settings.cache_clear()
    crypto.reset_cache()

    with pytest.raises(ConfigError) as exc:
        crypto.encrypt(SECRET)
    assert "Fernet" in str(exc.value)


def test_empty_plaintext_is_refused(fernet_env) -> None:
    with pytest.raises(CryptoError):
        crypto.encrypt("")


def test_decrypt_with_rotated_key_fails_without_echoing_ciphertext(fernet_env, monkeypatch) -> None:
    token = crypto.encrypt(SECRET)

    other = base64.urlsafe_b64encode(b"other-key-test-only-not-secret!!").decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", other)
    get_settings.cache_clear()
    crypto.reset_cache()

    with pytest.raises(CryptoError) as exc:
        crypto.decrypt(token)
    message = str(exc.value)
    assert token not in message
    assert "APP_ENCRYPTION_KEY" in message  # chỉ ra đúng nguyên nhân cho người vận hành


@pytest.mark.parametrize(
    "plaintext, expected",
    [
        ("AIzaSyAbCdEf123456", "••••3456"),
        ("abcd", "••••••••"),  # ngắn hơn/bằng `keep` → che hết
        ("ab", "••••••••"),
    ],
)
def test_hint_only_reveals_tail(plaintext: str, expected: str) -> None:
    assert crypto.hint_of(plaintext) == expected


def test_hint_never_contains_whole_secret() -> None:
    secret = "abcdefgh"
    assert secret not in crypto.hint_of(secret)


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_crypto_errors_log_nothing_at_any_level(fernet_env, capsys, level: str) -> None:
    """DoD D1.5: hàm đọc credential không ghi plaintext vào log ở mọi mức log."""
    setup_logging(level, force=True)
    logging.getLogger().setLevel(level)

    token = crypto.encrypt(SECRET)
    assert crypto.decrypt(token) == SECRET

    err = capsys.readouterr().err
    assert SECRET not in err
    assert token not in err
