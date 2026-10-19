"""Database resource ownership, cancellation and deadline tests."""

import asyncio
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DatabaseSettings
from app.core.database import Database, get_db
from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("failure")], ids=["success", "error"])
async def test_session_cleanup(
    settings_factory: Callable[..., DatabaseSettings], failure: BaseException | None,
) -> None:
    """Close real request sessions on success and error without an implicit commit."""
    database = Database(settings_factory())
    application = create_app()
    application.state.database = database
    request = Request({"type": "http", "app": application})
    dependency = get_db(request)
    try:
        with (
            patch.object(
                AsyncSession, "close", autospec=True, side_effect=AsyncSession.close
            ) as close,
            patch.object(AsyncSession, "commit", autospec=True) as commit,
        ):
            session = await anext(dependency)
            if failure is None:
                await dependency.aclose()
            else:
                with pytest.raises(type(failure)):
                    await dependency.athrow(failure)
            close.assert_awaited_once_with(session)
            commit.assert_not_awaited()
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_health_deadline(settings_factory: Callable[..., DatabaseSettings]) -> None:
    """Bound the readiness check even when acquiring a connection stalls."""
    database = Database(settings_factory(health_timeout=0.05))
    connection = AsyncMock()
    acquired = asyncio.Event()
    cancelled = asyncio.Event()

    async def stall() -> None:
        """Wait until cancellation to simulate a stalled connection attempt."""
        acquired.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    connection.__aenter__.side_effect = stall
    real_engine = database.engine
    database.engine = MagicMock()
    database.engine.connect.return_value = connection
    try:
        with pytest.raises(TimeoutError):
            await database.check_health()
        assert acquired.is_set()
        assert cancelled.is_set()
    finally:
        await real_engine.dispose()
