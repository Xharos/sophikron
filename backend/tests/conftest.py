"""Isolated settings and event-loop fixtures for backend tests."""

import asyncio
import base64
import json
import os
import secrets
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from coverage import Coverage
from sqlalchemy import delete, select

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models import AccountInvitation, User
from tests.support.authentication import auth_case  # noqa: F401
from tests.support.cleanup import clear_test_events
from tests.support.lessons import course  # noqa: F401
from tests.support.postgres import run_alembic


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    """Associate setup, asynchronous tasks and teardown with the exact pytest case."""
    coverage = Coverage.current()
    if coverage is not None:
        coverage.switch_context(item.nodeid)
    try:
        return (yield)
    finally:
        if coverage is not None:
            coverage.switch_context("")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep marker selection consistent with the suite directories, including future tests."""
    for item in items:
        relative = Path(item.path).relative_to(Path(__file__).parent)
        category = relative.parts[0]
        if category in {"unit", "integration", "e2e", "perf"}:
            item.add_marker(getattr(pytest.mark, category))
        if category == "e2e":
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Prepare the dedicated database once for all PostgreSQL integration test modules."""
    if os.environ.get("DB_INTEGRATION") != "1":
        pytest.skip("Configure the dedicated test database")
    run_alembic("upgrade", "head")

    async def remove_startup_fixture() -> None:
        """Remove the live verification API's bootstrap only in the guarded disposable database."""
        database = Database(DatabaseSettings())
        try:
            async with database.sessions.begin() as session:
                bootstrap_ids = list(
                    await session.scalars(select(User.id).where(User.is_bootstrap))
                )
                await clear_test_events(bootstrap_ids)
                ids = select(User.id).where(User.is_bootstrap)
                await session.execute(
                    delete(AccountInvitation).where(
                        AccountInvitation.user_id.in_(ids)
                        | AccountInvitation.issued_by_user_id.in_(ids)
                    )
                )
                await session.execute(delete(User).where(User.is_bootstrap))
        finally:
            await database.close()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(remove_startup_fixture())


@pytest.fixture(autouse=True)
def auth_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply synthetic keys and fast test settings without inherited AUTH_* values."""
    for name in list(os.environ):
        if name.startswith("AUTH_"):
            monkeypatch.delenv(name)
    key_file = tmp_path / "identity-keys.json"
    key_file.write_text(
        json.dumps(
            {
                "active_key": "test",
                "encryption_keys": {"test": base64.b64encode(secrets.token_bytes(32)).decode()},
                "lookup_key": base64.b64encode(secrets.token_bytes(32)).decode(),
            }
        ),
        encoding="utf-8",
    )
    for name, value in {
        "DOCUMENT_ROOT": str(tmp_path / "documents"),
        "DOCUMENT_MAINTENANCE_ENABLED": "false",
        "AUTH_ENVIRONMENT": "test",
        "AUTH_KEYS_FILE": str(key_file),
        "AUTH_ALLOWED_ORIGINS": '["https://testserver"]',
        "AUTH_ARGON_MEMORY_KIB": "8192",
        "AUTH_ARGON_ITERATIONS": "1",
        "AUTH_ARGON_PARALLELISM": "1",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def settings_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., DatabaseSettings]:
    """Build settings using synthetic secrets and no inherited DB_* configuration."""
    # These unit tests intentionally have no database; installation rules have PostgreSQL tests.
    monkeypatch.setattr("app.services.auth.AuthService.initialize_installation", AsyncMock())
    for name in list(os.environ):
        if name.startswith("DB_"):
            monkeypatch.delenv(name)
    secret = tmp_path / "password"
    secret.write_text("unit-test-only-password", encoding="utf-8")

    def build(**overrides: object) -> DatabaseSettings:
        """Return settings with optional per-test overrides."""
        values = {
            "host": "127.0.0.1",
            "name": "unit_test",
            "user": "unit_test",
            "password_file": secret,
        }
        values.update(overrides)
        return DatabaseSettings(**values)

    return build


if sys.platform == "win32":

    def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
        """Use psycopg-compatible selector loops for native Windows tests."""
        return {"selector": asyncio.SelectorEventLoop}
