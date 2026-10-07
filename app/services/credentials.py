"""Lưu/đọc secret của người dùng (Google API key, cookie Facebook).

Hợp đồng của module này: **API không bao giờ** nhận lại plaintext từ đây qua
đường response. `get_secret()` chỉ dành cho tầng gọi cổng model; mọi thứ hiển
thị cho người dùng đi qua `describe()` (chỉ `is_set` + `hint`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt, hint_of
from app.core.logging import get_logger
from app.models import LlmCredential

log = get_logger(__name__)

KIND_GOOGLE_API_KEY = "google_api_key"
KIND_FB_COOKIE = "fb_cookie"
#: Page Access Token của Facebook Page (task.md X.6). Secret người dùng dán
#: trên UI → bắt buộc mã hoá at-rest như mọi secret khác, không vào .env.
# `noqa: S105` bên dưới: đây là **tên loại** (discriminator) đi vào cột `kind`,
# không phải giá trị token. Giá trị thật chỉ tồn tại mã hoá trong DB (luật L4).
KIND_PAGE_ACCESS_TOKEN = "page_access_token"  # noqa: S105


@dataclass(frozen=True)
class CredentialInfo:
    """Thứ duy nhất được phép ra tới FE."""

    kind: str
    is_set: bool
    hint: str = ""
    created_at: datetime | None = None


async def save_secret(session: AsyncSession, kind: str, plaintext: str) -> CredentialInfo:
    """Mã hoá rồi ghi (upsert theo `kind`). Trả về mô tả an toàn, không trả key."""
    plaintext = plaintext.strip()
    if not plaintext:
        raise ValueError("Secret rỗng.")

    row = await _get_row(session, kind)
    if row is None:
        row = LlmCredential(kind=kind)
        session.add(row)

    row.secret_enc = encrypt(plaintext)
    row.hint = hint_of(plaintext)
    await session.flush()

    # Log chỉ ghi *loại* credential, không ghi hint (hint vẫn là 4 ký tự thật).
    log.info("Đã lưu credential kind=%s", kind)
    return CredentialInfo(kind=kind, is_set=True, hint=row.hint, created_at=row.created_at)


async def get_secret(session: AsyncSession, kind: str) -> str | None:
    """Plaintext cho tầng gọi cổng model. `None` nếu chưa lưu."""
    row = await _get_row(session, kind)
    if row is None:
        return None
    return decrypt(row.secret_enc)


async def describe(session: AsyncSession, kind: str) -> CredentialInfo:
    """Mô tả an toàn cho UI — không bao giờ chứa plaintext."""
    row = await _get_row(session, kind)
    if row is None:
        return CredentialInfo(kind=kind, is_set=False)
    return CredentialInfo(kind=kind, is_set=True, hint=row.hint, created_at=row.created_at)


async def delete_secret(session: AsyncSession, kind: str) -> bool:
    """Xoá credential. Trả `True` nếu thật sự có hàng bị xoá."""
    result = await session.execute(delete(LlmCredential).where(LlmCredential.kind == kind))
    deleted = bool(result.rowcount)
    if deleted:
        log.info("Đã xoá credential kind=%s", kind)
    return deleted


async def _get_row(session: AsyncSession, kind: str) -> LlmCredential | None:
    stmt = select(LlmCredential).where(LlmCredential.kind == kind)
    return (await session.execute(stmt)).scalar_one_or_none()
