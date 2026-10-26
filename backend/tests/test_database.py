"""Database resource ownership, cancellation and deadline tests."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.script import ScriptDirectory
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DatabaseSettings
from app.core.database import Database, get_db
from app.main import create_app
from tests.postgres import run_alembic


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("failure")], ids=["success", "error"])
async def test_session_cleanup(
    settings_factory: Callable[..., DatabaseSettings],
    failure: BaseException | None,
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


@pytest.mark.parametrize(
    ("integration", "name", "user"),
    [
        ("0", "sophikron_test", "sophikron_app"),
        ("1", "sophikron", "sophikron_app"),
        ("1", "sophikron_test", "postgres"),
    ],
    ids=["not-enabled", "valuable-database", "wrong-role"],
)
def test_migration_helper_refuses_unsafe_targets(
    monkeypatch: pytest.MonkeyPatch,
    integration: str,
    name: str,
    user: str,
) -> None:
    """Never start a migration command outside the explicitly configured test database."""
    monkeypatch.setenv("DB_INTEGRATION", integration)
    monkeypatch.setenv("DB_NAME", name)
    monkeypatch.setenv("DB_USER", user)
    with patch("tests.postgres.subprocess.run") as execute:
        with pytest.raises(pytest.fail.Exception, match="Integration tests require"):
            run_alembic("downgrade", "base")
        execute.assert_not_called()


def test_feature_migration_chain() -> None:
    """Keep the ordered feature revisions and a single upgrade head."""
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    expected = [
        "0001_authentication",
        "0002_configuration",
        "0003_promotions",
        "0004_subjects",
        "0005_lessons",
        "0006_promotion_groups",
    ]
    revisions = list(reversed(list(scripts.walk_revisions())))
    assert [revision.revision for revision in revisions] == expected
    assert scripts.get_heads() == [expected[-1]]
    assert [revision.down_revision for revision in revisions] == [None, *expected[:-1]]
