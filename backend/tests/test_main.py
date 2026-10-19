"""API readiness and application lifecycle tests without a live PostgreSQL server."""

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import DatabaseSettings
from app.main import create_app


def test_root(settings_factory: Callable[..., DatabaseSettings]) -> None:
    """Serve the root even when no PostgreSQL server is running."""
    with patch.object(AsyncEngine, "connect", autospec=True) as connect:
        with TestClient(create_app(settings_factory())) as client:
            response = client.get("/")
        connect.assert_not_called()
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Sophikron API"}


def test_health_check(settings_factory: Callable[..., DatabaseSettings]) -> None:
    """Return the existing readiness response when the database is available."""
    with patch("app.main.Database.check_health", new_callable=AsyncMock) as check:
        with TestClient(create_app(settings_factory())) as client:
            response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    check.assert_awaited_once()


@pytest.mark.parametrize(
    "failure",
    [OperationalError("SELECT 1", {}, Exception("private connection details")),
     OSError("private connection details"), TimeoutError("private connection details")],
)
def test_health_check_database_unavailable(
    settings_factory: Callable[..., DatabaseSettings], failure: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Return an anonymous 503 and recover without restarting the application."""
    with patch("app.main.Database.check_health", new_callable=AsyncMock) as check:
        check.side_effect = failure
        with TestClient(create_app(settings_factory())) as client:
            response = client.get("/health")
            assert client.get("/").status_code == 200
            check.side_effect = None
            assert client.get("/health").status_code == 200
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "private connection details" not in caplog.text


def test_lifespan_disposes_pool(settings_factory: Callable[..., DatabaseSettings]) -> None:
    """Release the engine at shutdown even if request handling raised an error."""
    application = create_app(settings_factory())

    @application.get("/failure")
    async def fail() -> None:
        """Simulate an unexpected request failure."""
        raise RuntimeError("request failure")

    with patch.object(
        AsyncEngine, "dispose", autospec=True, side_effect=AsyncEngine.dispose
    ) as dispose:
        with TestClient(application) as client:
            engine = application.state.database.engine
            with pytest.raises(RuntimeError, match="request failure"):
                client.get("/failure")
            dispose.assert_not_awaited()
        dispose.assert_awaited_once_with(engine)
    assert not hasattr(application.state, "database")
