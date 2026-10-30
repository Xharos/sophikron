"""Real calendar credential lifecycle, administrator boundaries and complete annual feeds."""

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from icalendar import Calendar
from sqlalchemy import delete, select

from app.core.security import new_token, token_digest
from app.models import AuthRateLimit, TimetableCalendar, TimetableSubscription
from app.models.site import SiteSettings
from app.services.timetable import TimetableService
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion
from tests.test_timetable_workspace_postgres import Workspace, workspace  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


async def login(case: Harness, name: str) -> None:
    """Switch to a real account without bypassing session authentication."""
    case.client.cookies.clear()
    response = await case.client.post(
        "/api/v1/auth/login", json={"identifier": name, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


async def personal(case: Harness) -> dict:
    """Read only the current owner's credential via its authenticated endpoint."""
    response = await case.client.get("/api/v1/timetable/subscription")
    assert response.status_code == 200, response.text
    return response.json()


async def feed(case: Harness, token: str) -> list:
    """Parse the public ICS route, requiring successful private, nonindexed responses."""
    response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    assert "noindex" in response.headers["x-robots-tag"]
    return Calendar.from_ical(response.content).walk("VEVENT")


@pytest.mark.asyncio
async def test_active_feed_minute_budget(auth_case: Harness) -> None:
    """Limit active links even when empty, reset expired windows and ignore revoked tokens."""
    case = auth_case
    case.as_admin()
    token = (await personal(case))["token"]
    path = f"/api/v1/timetable/feed/{token}.ics"
    limit = case.app.state.auth_settings.calendar_feed_limit_per_minute
    for _ in range(limit):
        assert (await case.client.get(path)).status_code == 200
    response = await case.client.get(path)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    async with case.database.sessions.begin() as session:
        key = case.app.state.identity_cipher.lookup("rate:calendar-feed", token_digest(token).hex())
        row = await session.get(AuthRateLimit, key)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await case.client.get(path)).status_code == 200
    case.as_admin()
    assert (
        await case.client.post(
            f"/api/v1/timetable/subscriptions/users/{case.administrator}",
            json={"action": "regenerate"},
        )
    ).status_code == 200
    replacement = (await personal(case))["token"]
    assert (await case.client.get(f"/api/v1/timetable/feed/{replacement}.ics")).status_code == 200
    for _ in range(limit + 1):
        assert (await case.client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_all_roles_get_stable_encrypted_links_and_cannot_manage_targets(
    auth_case: Harness,
) -> None:
    """Provision every permanent role, prevent self rotation and never disclose target tokens."""
    case = auth_case
    case.as_admin()
    owner = await personal(case)
    for role in ("user", "teacher", "kholleur", "admin"):
        identifier, name = await case.create(role)
        await login(case, name)
        first = await personal(case)
        assert not first["revoked"]
        assert first == await personal(case)
        async with case.database.sessions() as session:
            row = await session.get(TimetableSubscription, identifier)
            token = case.app.state.identity_cipher.decrypt(
                identifier, "calendar_token", row.token_encrypted
            )
            assert len(token) == 86 and row.token_hash == token_digest(token)
            assert token.encode() not in row.token_encrypted
            assert first["token"] == (None if role == "user" else token)
        assert await feed(case, token) == []
        assert (await case.client.post("/api/v1/timetable/subscription")).status_code == 405
        if role != "admin":
            path = f"/api/v1/timetable/subscriptions/users/{case.administrator}"
            assert (await case.client.get(path)).status_code == 403
            assert (await case.client.post(path, json={"action": "regenerate"})).status_code == 403
            assert (
                await case.client.post(
                    "/api/v1/timetable/subscriptions/bulk",
                    json={"category": "user", "action": "revoke"},
                )
            ).status_code == 403
        case.as_admin()
        status = (
            await case.client.get(f"/api/v1/timetable/subscriptions/users/{identifier}")
        ).json()
        assert set(status) == {"eligible", "exists", "revoked"}
    case.as_admin()
    assert await personal(case) == owner


@pytest.mark.asyncio
async def test_revocation_persists_until_admin_replaces_token(workspace: Workspace) -> None:  # noqa: F811
    """Keep revocation across login, empty old URLs, replace secrets and exclude rejected polls."""
    w, case = workspace, workspace.case
    await w.add()
    await w.broadcast()
    await w.login(w.pupil_name)
    original = (await personal(case))["token"]
    assert await feed(case, original)
    case.as_admin()
    path = f"/api/v1/timetable/subscriptions/users/{w.pupil_id}"
    response = await case.client.post(path, json={"action": "revoke"})
    assert response.status_code == 200 and response.json()["revoked"]
    assert "token" not in response.text and original not in response.text
    await w.login(w.pupil_name)
    assert await personal(case) == {"token": original, "revoked": True}
    assert await feed(case, original) == []
    assert await feed(case, "x" * 86) == []
    assert await feed(case, "invalid") == []
    case.as_admin()
    response = await case.client.post(path, json={"action": "regenerate"})
    assert response.status_code == 200 and not response.json()["revoked"]
    assert set(response.json()) == {"eligible", "exists", "revoked"}
    await w.login(w.pupil_name)
    replacement = (await personal(case))["token"]
    assert len(replacement) == 86 and replacement != original
    assert await feed(case, original) == []
    async with case.database.sessions() as session:
        row = await session.get(TimetableSubscription, w.pupil_id)
        assert row.last_requested_at is not None
    assert await feed(case, replacement)
    case.as_admin()
    response = await case.client.get("/api/v1/admin/statistics?period=day")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["calendar_recent_users"] == 1
    counts = {item["label"]: item["value"] for item in body["calendar_subscriptions"]}
    assert counts["Consulté"] == 1
    await feed(case, replacement)
    assert (await case.client.get("/api/v1/admin/statistics?period=day")).json()[
        "calendar_recent_users"
    ] == 1
    journal = await case.client.get("/api/v1/admin/events", params={"user_id": w.pupil_id})
    assert journal.status_code == 200
    entries = journal.json()["items"]
    for code in ("user.calendar_revoke", "user.calendar_regenerate"):
        entry = next(item for item in entries if item["event_type"] == code)
        assert entry["subject_user_id"] == w.pupil_id and entry["data"] == {}
    assert original not in journal.text and replacement not in journal.text


@pytest.mark.asyncio
async def test_promotion_removal_hides_existing_secret_and_pupil_title(
    workspace: Workspace,  # noqa: F811
) -> None:
    """Recheck membership before disclosing an existing token or serving its named feed."""
    w, case = workspace, workspace.case
    response = await case.client.post("/api/v1/timetable/rooms", json={"name": "ICS-B208"})
    assert response.status_code == 201, response.text
    state = await w.add(room_id=response.json()["id"])
    await w.broadcast()
    await w.login(w.pupil_name)
    token = (await personal(case))["token"]
    response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    calendar = Calendar.from_ical(response.content)
    assert "LIVE-TIMETABLE" in str(calendar["x-wr-calname"])
    assert calendar.walk("VEVENT")
    event = calendar.walk("VEVENT")[0]
    assert str(event["summary"]) == "Cours - MATHS"
    assert str(event["location"]) == "ICS-B208"
    assert str(event["description"]) == (
        f"{calendar['x-wr-calname']} — Classe entière\n{state['events'][0]['teacher']}"
    )
    case.as_admin()
    response = await case.client.delete(
        f"/api/v1/admin/users/{w.pupil_id}/promotions/{w.promotion_id}"
    )
    assert response.status_code == 204, response.text
    await w.login(w.pupil_name)
    assert await personal(case) == {"token": None, "revoked": False}
    assert await feed(case, token) == []
    async with case.database.sessions() as session:
        row = await session.get(TimetableSubscription, w.pupil_id)
        assert row.token_hash == token_digest(token)
    case.as_admin()
    response = await case.client.put(
        f"/api/v1/admin/users/{w.pupil_id}/promotions/{w.promotion_id}"
    )
    assert response.status_code == 204, response.text
    await w.login(w.pupil_name)
    assert (await personal(case))["token"] == token


@pytest.mark.asyncio
async def test_staff_title_uses_current_site_name(auth_case: Harness) -> None:
    """Use the administrator's configured application name for every staff feed."""
    case = auth_case
    async with case.database.sessions.begin() as session:
        settings = await session.get(SiteSettings, 1)
        previous = settings.name
        settings.name = "Lycée des sciences"
    try:
        for role in ("teacher", "kholleur", "admin"):
            _, name = await case.create(role)
            await login(case, name)
            token = (await personal(case))["token"]
            response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
            assert str(Calendar.from_ical(response.content)["x-wr-calname"]) == "Lycée des sciences"
    finally:
        async with case.database.sessions.begin() as session:
            settings = await session.get(SiteSettings, 1)
            settings.name = previous


@pytest.mark.asyncio
async def test_category_changes_exclude_never_connected_and_other_roles(auth_case: Harness) -> None:
    """Bulk actions affect only active connected category members, with distinct random links."""
    case = auth_case
    pupil, pupil_name = await case.create()
    second, second_name = await case.create()
    never, _ = await case.create()
    pending, _ = await case.create(activate=False)
    teacher, teacher_name = await case.create("teacher")
    tokens = {}
    for identifier, name in ((pupil, pupil_name), (second, second_name), (teacher, teacher_name)):
        await login(case, name)
        async with case.database.sessions() as session:
            row = await session.get(TimetableSubscription, identifier)
            tokens[identifier] = case.app.state.identity_cipher.decrypt(
                identifier, "calendar_token", row.token_encrypted
            )
    case.as_admin()
    path = "/api/v1/timetable/subscriptions/bulk"
    response = await case.client.post(path, json={"category": "user", "action": "revoke"})
    assert response.status_code == 200 and response.json() == {"affected": 2}
    response = await case.client.post(path, json={"category": "user", "action": "regenerate"})
    assert response.status_code == 200 and response.json() == {"affected": 2}
    async with case.database.sessions() as session:
        rows = {row.user_id: row for row in await session.scalars(select(TimetableSubscription))}
        assert never not in rows and pending not in rows
        assert rows[teacher].token_hash == token_digest(tokens[teacher])
        assert rows[pupil].token_hash != rows[second].token_hash
        assert rows[pupil].token_hash != token_digest(tokens[pupil])
    response = await case.client.post(path, json={"category": "admin", "action": "revoke"})
    assert response.status_code == 422
    assert (
        await case.client.post(
            f"/api/v1/timetable/subscriptions/users/{never}", json={"action": "regenerate"}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_legacy_verifier_is_upgraded_once_and_disabled_accounts_stay_empty(
    auth_case: Harness,
) -> None:
    """Upgrade unrecoverable old links once and deny feed data after account archival."""
    case = auth_case
    identifier, name = await case.create("teacher")
    await login(case, name)
    old = new_token()
    async with case.database.sessions.begin() as session:
        row = await session.get(TimetableSubscription, identifier)
        row.token_hash, row.token_encrypted = token_digest(old), None
    replacement = await personal(case)
    assert len(replacement["token"]) == 86 and replacement == await personal(case)
    assert await feed(case, old) == []
    case.as_admin()
    response = await case.client.patch(
        f"/api/v1/admin/users/{identifier}/archive", json={"archived": True}
    )
    assert response.status_code == 204, response.text
    case.client.cookies.clear()
    assert await feed(case, replacement["token"]) == []
    assert (await case.client.get("/api/v1/timetable/subscription")).status_code == 401


@pytest.mark.asyncio
async def test_complete_year_includes_past_sessions_after_teaching_ends(
    workspace: Workspace,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep annual history even when today lies outside the calendar's teaching dates."""
    w, case = workspace, workspace.case
    state = await w.add()
    year = state["years"][0]
    settings = {**year["settings"], "end": f"{w.school_year + 1}-07-01"}
    response = await case.client.put(
        f"/api/v1/timetable/years/{year['id']}/settings",
        json={"expected_revision": year["revision"], "settings": settings},
    )
    assert response.status_code == 200, response.text
    await w.broadcast()
    monkeypatch.setattr(TimetableService, "today", lambda self: date(w.school_year + 1, 8, 31))
    await w.login(w.pupil_name)
    token = (await personal(case))["token"]
    first = await feed(case, token)
    assert len(first) > 30
    assert all(event.decoded("dtstart").date() <= date(w.school_year + 1, 7, 1) for event in first)
    assert [event["uid"] for event in await feed(case, token)] == [event["uid"] for event in first]


@pytest.mark.asyncio
async def test_teacher_feed_combines_promotions_and_filters_other_teachers(
    workspace: Workspace,  # noqa: F811
) -> None:
    """Union assigned sessions across two live promotions without leaking other staff sessions."""
    w, case = workspace, workspace.case
    await w.add(title="First promotion")
    await w.broadcast()
    promotion = await make_promotion(case, "ICS-SECOND")
    try:
        case.as_admin()
        response = await case.client.post(
            f"/api/v1/admin/promotions/{promotion}/users", json={"user_ids": [w.teacher_id]}
        )
        assert response.status_code == 204
        w.calendar_id = await w.create(promotion=promotion)
        await w.add(title="Second promotion")
        await w.add(title="Another teacher", teacher_id=None)
        await w.broadcast()
        await w.login(w.teacher_name)
        token = (await personal(case))["token"]
        titles = {str(event["summary"]) for event in await feed(case, token)}
        assert titles == {"Cours - FIRST PROMOTION", "Cours - SECOND PROMOTION"}
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.promotion_id == promotion)
            )
        await clear_promotions([promotion])
