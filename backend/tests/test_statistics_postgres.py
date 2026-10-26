"""Real PostgreSQL statistics aggregates and live administrator/author/collaborator boundaries."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.models.statistics import LoginStatistic
from app.services.activity import record_event
from app.services.statistics_recording import record_login_failure
from tests.test_auth_postgres import Harness
from tests.test_lesson_documents_postgres import PAYLOAD, documents, upload  # noqa: F401
from tests.test_lessons_postgres import CourseHarness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_statistics_scope_uniques_storage_and_downloads(documents: CourseHarness) -> None:  # noqa: F811
    """Scope before aggregating, preserve distinct period totals and count real full transfers."""
    course, case = documents, documents.case
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    file = await upload(course, course.state["elements"][0]["id"])
    for _ in range(2):
        response = await case.client.get(course.path + f"/files/{file['file']['id']}")
        assert response.status_code == 200 and response.content == PAYLOAD
    response = await case.client.get(course.path + "/statistics?period=week")
    assert response.status_code == 200, response.text
    stats = response.json()
    assert stats["totals"]["downloads"] == 2 and stats["totals"]["downloaders"] == 1
    assert stats["storage"]["bytes"] == len(PAYLOAD) and stats["storage"]["files"] == 1
    assert stats["storage"]["physical_bytes"] is None
    assert stats["popular"][0]["id"] == file["file"]["id"]
    assert stats["accounts"] == [] and "logins" not in stats["totals"]
    personal = (await case.client.get("/api/v1/teaching/statistics")).json()
    assert [item["id"] for item in personal["courses"]] == [course.state["id"]]
    assert personal["totals"]["downloads"] == 2

    # Unrelated teachers may open content under the existing policy, but not its statistics.
    await course.login(course.collaborator)
    assert (await case.client.get(course.path + "/statistics")).status_code == 403
    assert (await case.client.get("/api/v1/admin/statistics")).status_code == 403
    empty = (await case.client.get("/api/v1/teaching/statistics")).json()
    assert empty["courses"] == [] and empty["storage"]["files"] == 0
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.collaborator)
    assert (await case.client.get(course.path + "/statistics")).status_code == 200
    assert (await case.client.get("/api/v1/teaching/statistics")).json()["courses"] == []
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "delete")
    await course.login(course.collaborator)
    assert (await case.client.get(course.path + "/statistics")).status_code == 403

    await course.login(course.student)
    assert (await case.client.get(course.path + "/statistics")).status_code == 403
    assert (await case.client.get("/api/v1/teaching/statistics")).status_code == 403
    case.as_admin()
    global_stats = await case.client.get("/api/v1/admin/statistics?period=month")
    assert global_stats.status_code == 200, global_stats.text
    body = global_stats.json()
    assert len(body["timestamps"]) == 30 and body["scope"] == "admin"
    assert body["totals"]["downloads"] >= 2 and body["storage"]["physical_bytes"] == len(PAYLOAD)
    assert (await case.client.get("/api/v1/admin/statistics?period=year")).status_code == 422


@pytest.mark.asyncio
async def test_statistics_kholleur_affiliation_and_grant_revocation(course: CourseHarness) -> None:
    """A currently affiliated khôlleur reads course aggregates without global account statistics."""
    case = course.case
    kholleur_id, username = await case.create("kholleur")
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{kholleur_id}", {}, "put")
    await course.login(username)
    assert (await case.client.get(course.path)).json()["can_view_statistics"] is True
    assert (await case.client.get(course.path + "/statistics")).status_code == 200
    assert (await case.client.get("/api/v1/teaching/statistics")).status_code == 403
    case.as_admin()
    profile = (await case.client.get(f"/api/v1/admin/users/{kholleur_id}/profile")).json()
    assert (
        await case.client.patch(
            f"/api/v1/admin/users/{kholleur_id}/profile",
            json={
                "expected_version": profile["profile_version"],
                "roles": ["user"],
                "acknowledge_course_impact": True,
            },
        )
    ).status_code == 200
    await course.login(username)
    assert (await case.client.get(course.path + "/statistics")).status_code == 403


@pytest.mark.asyncio
async def test_login_statistics_atomic_buckets_and_live_outcomes(auth_case: Harness) -> None:
    """Count concurrent anonymous outcomes and meter real authentication failures."""
    case = auth_case
    instant = datetime(2001, 1, 1, 12, 0, tzinfo=UTC)

    async def increment(limited: bool) -> None:
        """Write one concurrent anonymous outcome through the actual UPSERT."""
        async with case.database.sessions.begin() as session:
            await record_login_failure(session, instant, limited=limited)

    try:
        await asyncio.gather(*(increment(index % 2 == 0) for index in range(10)))
        async with case.database.sessions() as session:
            bucket = await session.get(LoginStatistic, instant)
            assert bucket.failed == 5 and bucket.limited == 5
        response = await case.client.post(
            "/api/v1/auth/login", json={"identifier": "unknown-account", "password": "incorrect"}
        )
        assert response.status_code == 401
        case.as_admin()
        statistics = (await case.client.get("/api/v1/admin/statistics?period=day")).json()
        assert statistics["totals"]["failures"] >= 1
        assert statistics["totals"]["attempts"] == sum(
            statistics["totals"][key] for key in ("logins", "failures", "limited")
        )
        assert "unknown-account" not in str(statistics)
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(LoginStatistic).where(LoginStatistic.bucket == instant))


@pytest.mark.asyncio
async def test_unique_logins_are_distinct_over_the_whole_period(auth_case: Harness) -> None:
    """A person connecting on two days contributes two points and one period-wide unique account."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    now = datetime.now(UTC)
    async with case.database.sessions.begin() as session:
        for delta in (1, 2):
            await record_event(
                session,
                "auth.login_succeeded",
                user_id,
                subject_user_id=user_id,
                occurred_at=now - timedelta(days=delta),
            )
    result = (await case.client.get("/api/v1/admin/statistics?period=week")).json()
    assert result["totals"]["logins"] > result["totals"]["unique_logins"]
    assert sum(result["series"]["unique_logins"]) > result["totals"]["unique_logins"]


@pytest.mark.asyncio
async def test_additive_statistics_upgrade_preserves_existing_installation(
    auth_case: Harness,
) -> None:
    """Run the existing-schema helper twice with migration credentials without losing accounts."""
    case = auth_case
    user_id, username = await case.create(activate=False)
    environment = {
        **os.environ,
        "DB_USER": "sophikron_migrator",
        "DB_PASSWORD_FILE": os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"],
    }
    for _ in range(2):
        upgraded = subprocess.run(
            [sys.executable, "-m", "app.cli", "upgrade-statistics"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert upgraded.returncode == 0, upgraded.stderr
    current = await case.client.get(f"/api/v1/admin/users/{user_id}")
    assert current.status_code == 200 and current.json()["username"] == username
