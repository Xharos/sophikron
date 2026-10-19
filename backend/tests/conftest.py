"""Isolated settings and event-loop fixtures for backend tests."""

import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.config import DatabaseSettings


@pytest.fixture
def settings_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., DatabaseSettings]:
    """Build settings using synthetic secrets and no inherited DB_* configuration."""
    for name in list(os.environ):
        if name.startswith("DB_"):
            monkeypatch.delenv(name)
    secret = tmp_path / "password"
    secret.write_text("unit-test-only-password", encoding="utf-8")

    def build(**overrides: object) -> DatabaseSettings:
        """Return settings with optional per-test overrides."""
        values = {
            "host": "127.0.0.1", "name": "unit_test", "user": "unit_test",
            "password_file": secret,
        }
        values.update(overrides)
        return DatabaseSettings(**values)

    return build


if sys.platform == "win32":

    def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
        """Use psycopg-compatible selector loops for native Windows tests."""
        return {"selector": asyncio.SelectorEventLoop}
