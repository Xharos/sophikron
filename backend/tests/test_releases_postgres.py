"""Real PostgreSQL cache persistence, daily expiry, locking and access boundaries."""

import os
from datetime import UTC, datetime, timedelta
from urllib.error import URLError

import pytest
from sqlalchemy import text, update

from app.models.releases import ReleaseCheck
from app.services import releases
from tests.test_auth_postgres import PASSWORD, Harness

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
)]


@pytest.mark.asyncio
async def test_daily_cache(auth_case: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist results across requests, suppress concurrent checks and retain stale success."""
    case = auth_case
    calls = []

    def fetch() -> tuple[str, str]:
        """Count synthetic external calls while exercising real database transactions."""
        calls.append(True)
        return "0.2.0", f"{releases.REPOSITORY}/releases/tag/v0.2.0"

    monkeypatch.setattr(releases, "fetch_release", fetch)
    async with case.database.sessions.begin() as db:
        await db.execute(update(ReleaseCheck).values(
            attempted_at=None, checked_at=None, version=None, release_url=None, error=None
        ))
    try:
        result = await case.client.get("/api/v1/admin/versions")
        assert result.status_code == 200, result.text
        assert result.json()["latest_version"] == "0.2.0"
        assert (await case.client.get("/api/v1/admin/versions")).status_code == 200
        assert len(calls) == 1
        async with case.database.sessions.begin() as db:
            await db.execute(update(ReleaseCheck).values(
                attempted_at=datetime.now(UTC) - timedelta(days=2)
            ))
        async with case.database.sessions.begin() as locked:
            await locked.execute(text("SELECT pg_advisory_xact_lock(73482916)"))
            assert (await case.client.get("/api/v1/admin/versions")).status_code == 200
            assert len(calls) == 1

        def failed() -> None:
            """Simulate a GitHub outage without erasing the successful cache."""
            calls.append(True)
            raise URLError("offline")

        monkeypatch.setattr(releases, "fetch_release", failed)
        stale = (await case.client.get("/api/v1/admin/versions")).json()
        assert stale["error"] and stale["latest_version"] == "0.2.0"
        assert stale["checked_at"] == result.json()["checked_at"]
        await case.client.get("/api/v1/admin/versions")
        assert len(calls) == 2
    finally:
        async with case.database.sessions.begin() as db:
            await db.execute(update(ReleaseCheck).values(
                attempted_at=None, checked_at=None, version=None, release_url=None, error=None
            ))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "teacher", "kholleur"])
async def test_versions_admin_only(auth_case: Harness, role: str) -> None:
    """Deny version checks to anonymous users and all non-administrator roles."""
    case = auth_case
    case.client.cookies.clear()
    assert (await case.client.get("/api/v1/admin/versions")).status_code == 401
    _, username = await case.create(role)
    await case.client.post("/api/v1/auth/login", json={
        "identifier": username, "password": PASSWORD,
    })
    assert (await case.client.get("/api/v1/admin/versions")).status_code == 403
