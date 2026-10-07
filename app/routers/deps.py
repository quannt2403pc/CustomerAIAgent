"""Dependency dùng chung cho router (task.md D2.1–D2.4).

Hai việc:

1. **Session có commit.** `app/db/engine.get_session` chỉ mở session; dùng trực
   tiếp cho endpoint ghi dữ liệu thì mọi thay đổi bị bỏ lúc đóng session — kiểu
   lỗi im lặng tệ nhất (API trả 200, DB không có gì). Dependency ở đây commit
   khi handler chạy xong, rollback khi có lỗi.
2. **Mở/đóng gateway đúng vòng đời.** `resolve_gateway` tạo `httpx.AsyncClient`
   riêng nếu không được truyền; không đóng thì mỗi request rò một connection pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_sessionmaker
from app.llm.base import LLMGateway
from app.llm.resolver import resolve_gateway


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Một session cho mỗi request, commit khi thành công."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class gateway_scope:
    """`async with gateway_scope(session) as gw:` — đóng client khi ra khỏi khối.

    Raise đúng lỗi của `resolve_gateway` (`GatewayNotConfigured` /
    `GatewayNoCredential`) để handler lỗi chuẩn hoá thành 409.
    """

    def __init__(self, session: AsyncSession, *, provider: str | None = None):
        self._session = session
        self._provider = provider
        self._gateway: LLMGateway | None = None

    async def __aenter__(self) -> LLMGateway:
        self._gateway = await resolve_gateway(self._session, provider=self._provider)
        return self._gateway

    async def __aexit__(self, *_exc: object) -> None:
        if self._gateway is not None:
            await self._gateway.aclose()
