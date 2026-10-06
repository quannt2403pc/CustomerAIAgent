"""Mã hoá at-rest bằng Fernet (plan.md §7.2).

Hai nguyên tắc không thương lượng:

1. **Không fallback plaintext.** Thiếu `APP_ENCRYPTION_KEY` → nổ ngay, không
   âm thầm lưu secret dạng thường. Fallback kiểu đó là cách lộ key kinh điển.
2. **Không log giá trị.** Mọi lỗi ở đây chỉ nêu *loại* lỗi, không bao giờ kèm
   ciphertext hay plaintext.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import ConfigError, get_settings
from app.core.errors import CryptoError


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = get_settings().require_encryption_key()
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ConfigError(
            "APP_ENCRYPTION_KEY không đúng định dạng Fernet (32 byte urlsafe-base64). "
            'Sinh lại bằng: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        ) from exc


def encrypt(plaintext: str) -> str:
    """Mã hoá một secret. Chuỗi rỗng bị từ chối — lưu rỗng là lỗi logic ở tầng trên."""
    if not plaintext:
        raise CryptoError("Không mã hoá chuỗi rỗng.")
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Giải mã. Token sai/đổi khoá → `CryptoError`, **không** kèm ciphertext."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CryptoError(
            "Không giải mã được secret đã lưu. Thường do APP_ENCRYPTION_KEY đã bị đổi "
            "sau khi lưu — hãy nhập lại API key trong trang Cài đặt."
        ) from exc


def hint_of(plaintext: str, *, keep: int = 4) -> str:
    """Gợi nhớ an toàn để hiện trên UI: `••••abcd`.

    Secret ngắn hơn `keep` ký tự thì che hết — đừng để hint tiết lộ cả secret.
    """
    if len(plaintext) <= keep:
        return "•" * 8
    return "•" * 4 + plaintext[-keep:]


def reset_cache() -> None:
    """Xoá cache Fernet — chỉ dùng trong test khi đổi `APP_ENCRYPTION_KEY`."""
    _fernet.cache_clear()
