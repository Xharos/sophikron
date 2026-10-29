"""Live annual calendars, authorization, archival and bounded-query personal feeds."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest
import pytest_asyncio
from icalendar import Calendar
from sqlalchemy import delete, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError

from app.models import (
    Subject,
    TeacherAvailability,
    TimetableCalendar,
    TimetablePreferences,
    TimetableSchoolYear,
    TimetableSeries,
    TimetableYear,
)
from app.services.timetable_engine import PARIS
from app.services.timetable_lifecycle import rollover
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@dataclass
class Workspace:
    """Own only this scenario's accounts, promotions and annual calendars."""

    case: Harness
    promotion_id: int
    teacher_id: int
    teacher_name: str
    pupil_id: int
    pupil_name: str
    school_year: int
    settings: dict
    calendar_id: int = 0
    calendar_ids: list[int] = field(default_factory=list)

    async def create(self, *, promotion: int | None = None, school_year: int | None = None) -> int:
        """Create an independent annual calendar through the actual administrator API."""
        self.case.as_admin()
        response = await self.case.client.post(
            "/api/v1/timetable/calendars",
            json={
                "name": f"{self.case.prefix}-{len(self.calendar_ids)}",
                "promotion_id": promotion,
                "school_year": school_year or self.school_year,
                "settings": self.settings,
                "is_paused": True,
            },
        )
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        self.calendar_ids.append(identifier)
        return identifier

    async def board(self, identifier: int | None = None) -> dict:
        """Read the real live board with an administrator session."""
        self.case.as_admin()
        response = await self.case.client.get(
            "/api/v1/timetable/board", params={"calendar_ids": identifier or self.calendar_id}
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def add(self, **changes: object) -> dict:
        """Save a recurring session and return its refreshed actual annual board."""
        state = await self.board()
        year = state["years"][0]
        beginning = date.fromisoformat(self.settings["start"])
        beginning += timedelta(days=(-beginning.weekday()) % 7)
        response = await self.case.client.post(
            f"/api/v1/timetable/years/{year['id']}/series",
            json={
                "expected_revision": year["revision"],
                "confirmed_live": True,
                "block": {
                    "starts_on": beginning.isoformat(),
                    "start_slot": 0,
                    "duration_slots": 2,
                    "teacher_id": self.teacher_id,
                    "title": "Maths",
                    "interval": 1,
                    **changes,
                },
            },
        )
        assert response.status_code == 201, response.text
        return await self.board()

    async def broadcast(self) -> dict:
        """Enable diffusion using the observed calendar revision."""
        state = await self.board()
        agenda = state["calendars"][0]
        response = await self.case.client.put(
            f"/api/v1/timetable/calendars/{self.calendar_id}",
            json={
                "name": agenda["name"],
                "promotion_id": agenda["promotion_id"],
                "is_paused": False,
                "expected_revision": agenda["revision"],
                "confirmed_live": True,
            },
        )
        assert response.status_code == 200, response.text
        return await self.board()

    async def login(self, username: str) -> None:
        """Switch to a real account session without bypassing permission dependencies."""
        self.case.client.cookies.clear()
        response = await self.case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text


@pytest_asyncio.fixture
async def workspace(auth_case: Harness) -> AsyncIterator[Workspace]:
    """Build an isolated roster and clean only explicitly created timetable records."""
    case = auth_case
    promotion = await make_promotion(case, "LIVE-TIMETABLE")
    teacher, teacher_name = await case.create("teacher")
    pupil, pupil_name = await case.create()
    school_year = date.today().year - (date.today().month < 9)
    case.as_admin()
    response = await case.client.post(
        f"/api/v1/admin/promotions/{promotion}/users", json={"user_ids": [teacher, pupil]}
    )
    assert response.status_code == 204, response.text
    response = await case.client.post(
        "/api/v1/timetable/school-years", json={"school_year": school_year}
    )
    assert response.status_code == 201, response.text
    w = Workspace(
        case,
        promotion,
        teacher,
        teacher_name,
        pupil,
        pupil_name,
        school_year,
        {
            "start": f"{school_year}-09-01",
            "end": f"{school_year + 1}-08-31",
            "session_minutes": 60,
            "day_start": 28800,
            "day_end": 68400,
            "lunch_start": 43200,
            "lunch_end": 50400,
            "breaks": [],
        },
    )
    try:
        w.calendar_id = await w.create(promotion=promotion)
        yield w
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.id.in_(w.calendar_ids))
            )
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.user_id == teacher)
            )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == school_year)
            )
        await clear_promotions([promotion])


@pytest.mark.asyncio
async def test_annual_kholle_bounds_permissions_and_availability_preservation(
    workspace: Workspace,
) -> None:
    """Keep annual bounds independent from ranges and enforce admin writes and stale revisions."""
    w = workspace
    endpoint = f"/api/v1/timetable/staff/{w.school_year}/{w.teacher_id}/availability"
    board_endpoint = "/api/v1/timetable/staff/board"
    params = {"school_year": w.school_year, "teacher_ids": w.teacher_id}
    initial = (await w.case.client.get(board_endpoint, params=params)).json()["availability"][0]
    assert initial["kholle_min_hours"] == initial["kholle_max_hours"] == 0
    response = await w.case.client.put(
        endpoint, json={"kholle_min_hours": 1, "kholle_max_hours": 4}
    )
    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
    pattern = (await w.case.client.get(board_endpoint, params=params)).json()["availability"][0]
    assert pattern["default"] and pattern["ranges"] == initial["ranges"]
    assert (pattern["kholle_min_hours"], pattern["kholle_max_hours"]) == (1, 4)
    assert (
        await w.case.client.put(endpoint, json={"kholle_min_hours": 2, "kholle_max_hours": 5})
    ).status_code == 409
    for ranges in ([], None):
        response = await w.case.client.put(
            endpoint, json={"expected_revision": revision, "ranges": ranges}
        )
        assert response.status_code == 200, response.text
        revision = response.json()["revision"]
        pattern = (await w.case.client.get(board_endpoint, params=params)).json()["availability"][0]
        assert (pattern["kholle_min_hours"], pattern["kholle_max_hours"]) == (1, 4)
        assert pattern["default"] == (ranges is None)
    for role in ("teacher", "kholleur"):
        _, username = await w.case.create(role)
        await w.login(username)
        assert (
            await w.case.client.put(
                endpoint,
                json={
                    "expected_revision": revision,
                    "kholle_min_hours": 2,
                    "kholle_max_hours": 5,
                },
            )
        ).status_code == 403
        assert (await w.case.client.get(board_endpoint, params=params)).status_code == 200
    w.case.as_admin()
    future_year = w.school_year + 1
    response = await w.case.client.post(
        "/api/v1/timetable/school-years", json={"school_year": future_year}
    )
    assert response.status_code == 201, response.text
    try:
        future = (
            await w.case.client.get(board_endpoint, params={**params, "school_year": future_year})
        ).json()["availability"][0]
        assert future["kholle_min_hours"] == future["kholle_max_hours"] == 0
        response = await w.case.client.put(
            endpoint,
            json={"expected_revision": revision, "kholle_min_hours": 0, "kholle_max_hours": 0},
        )
        assert response.status_code == 200 and response.json()["revision"] is None
        async with w.case.database.sessions.begin() as session:
            for minimum, maximum in ((-1, 0), (2, 1)):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            TeacherAvailability(
                                user_id=w.teacher_id,
                                school_year=future_year,
                                ranges=None,
                                revision="a" * 32,
                                kholle_min_hours=minimum,
                                kholle_max_hours=maximum,
                            )
                        )
                        await session.flush()
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == future_year)
            )


@pytest.mark.asyncio
async def test_live_confirmation_stale_write_and_removed_endpoints(workspace: Workspace) -> None:
    """Confirm every live mutation and refuse stale edits, publication and template endpoints."""
    w = workspace
    state = await w.add()
    state = await w.broadcast()
    year = state["years"][0]
    block = {
        key: value
        for key, value in year["series"][0].items()
        if key in {"starts_on", "start_slot", "duration_slots", "teacher_id", "title", "interval"}
    }
    endpoint = f"/api/v1/timetable/years/{year['id']}/series"
    response = await w.case.client.post(
        endpoint, json={"expected_revision": year["revision"], "block": block}
    )
    assert response.status_code == 409
    response = await w.case.client.post(
        endpoint, json={"expected_revision": "0" * 32, "confirmed_live": True, "block": block}
    )
    assert response.status_code == 409
    assert (
        await w.case.client.post(f"/api/v1/timetable/years/{year['id']}/publish", json={})
    ).status_code == 404
    assert (
        await w.case.client.get(f"/api/v1/timetable/years/{year['id']}/template")
    ).status_code == 404
    assert (await w.board())["events"] == state["events"]


@pytest.mark.asyncio
async def test_unique_name_assignment_archival_and_restore(workspace: Workspace) -> None:
    """Enforce uniqueness in services and the database, with archives read-only and reversible."""
    w = workspace
    state = await w.add()
    other = await w.create()
    agenda = (await w.board(other))["calendars"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{other}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "confirmed_assignment": True,
            "is_paused": True,
        },
    )
    assert response.status_code == 409
    current = state["calendars"][0]
    response = await w.case.client.post(
        f"/api/v1/timetable/calendars/{w.calendar_id}/archive",
        json={"expected_revision": current["revision"]},
    )
    assert response.status_code == 200, response.text
    archive_revision = response.json()["revision"]
    year = state["years"][0]
    assert (
        await w.case.client.put(
            f"/api/v1/timetable/years/{year['id']}/settings",
            json={"expected_revision": year["revision"], "settings": year["settings"]},
        )
    ).status_code == 409
    response = await w.case.client.get(
        "/api/v1/timetable/staff/board",
        params={"school_year": w.school_year, "teacher_ids": w.teacher_id},
    )
    assert response.status_code == 200 and response.json()["events"] == []
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{other}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "confirmed_assignment": True,
            "is_paused": True,
        },
    )
    assert response.status_code == 200, response.text
    endpoint = f"/api/v1/timetable/calendars/{w.calendar_id}/restore"
    response = await w.case.client.post(endpoint, json={"expected_revision": archive_revision})
    assert response.status_code == 409
    response = await w.case.client.post(
        endpoint, json={"expected_revision": archive_revision, "detach_promotion": True}
    )
    assert response.status_code == 200, response.text
    restored = (await w.board())["calendars"][0]
    assert (
        restored["promotion_id"] is None and restored["is_paused"] and not restored["is_archived"]
    )


@pytest.mark.asyncio
async def test_dates_hide_and_restore_events_without_destroying_exceptions(
    workspace: Workspace,
) -> None:
    """Retain data under vacation edits and reject changes to immutable grid/self settings."""
    w = workspace
    state = await w.add()
    year = state["years"][0]
    event = state["events"][0]
    changed = {
        **year["settings"],
        "holidays": [{"start": event["source_date"], "end": event["source_date"]}],
    }
    endpoint = f"/api/v1/timetable/years/{year['id']}/settings"
    response = await w.case.client.post(
        endpoint + "/preview", json={"expected_revision": year["revision"], "settings": changed}
    )
    assert response.status_code == 200 and response.json()["hidden"] == 1
    response = await w.case.client.put(
        endpoint, json={"expected_revision": year["revision"], "settings": changed}
    )
    assert response.status_code == 200, response.text
    after = await w.board()
    assert len(after["events"]) == len(state["events"]) - 1
    assert after["years"][0]["series"] == year["series"]
    response = await w.case.client.put(
        endpoint,
        json={"expected_revision": after["years"][0]["revision"], "settings": year["settings"]},
    )
    assert response.status_code == 200 and len((await w.board())["events"]) == len(state["events"])
    fresh = (await w.board())["years"][0]
    for key, value in {
        "day_start": 30000,
        "day_end": 65000,
        "session_minutes": 55,
        "lunch_end": 54000,
    }.items():
        response = await w.case.client.put(
            endpoint,
            json={
                "expected_revision": fresh["revision"],
                "settings": {**fresh["settings"], key: value},
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_availability_and_calendar_conflicts_use_the_same_year(workspace: Workspace) -> None:
    """Warn on explicit unavailability and external bookings without refusing a saved course."""
    w = workspace
    response = await w.case.client.put(
        f"/api/v1/timetable/staff/{w.school_year}/{w.teacher_id}/availability", json={"ranges": []}
    )
    assert response.status_code == 200, response.text
    state = await w.add()
    assert any("Disponibilité" in warning for warning in state["warnings"])
    other = await w.create()
    w.calendar_id, original = other, w.calendar_id
    second = await w.add()
    assert second["teacher_commitments"] and all(
        item["calendar_id"] == original for item in second["teacher_commitments"]
    )
    w.calendar_id = original
    assert any(item["calendar_id"] == other for item in (await w.board())["teacher_commitments"])
    response = await w.case.client.get("/api/v1/timetable/staff/catalog")
    settings = response.json()["years"][0]["settings"]
    assert settings["saturday"] and not settings["breaks"] and settings["day_end"] == 68400


@pytest.mark.asyncio
async def test_live_feed_private_scope_pause_archive_and_query_budget(workspace: Workspace) -> None:
    """Generate real ICS with bounded SQL and immediately honor diffusion and membership rights."""
    w = workspace
    state = await w.add()
    state = await w.broadcast()
    await w.login(w.pupil_name)
    assert (await w.case.client.get("/api/v1/timetable/catalog")).status_code == 403
    assert (await w.case.client.get("/api/v1/timetable/staff/catalog")).status_code == 403
    response = await w.case.client.get("/api/v1/timetable/subscription")
    token = response.json()["token"]
    statements = []

    def count_statement(*arguments: object) -> None:
        """Count real driver executions, including authorization and decoration queries."""
        statements.append(arguments[2])

    sqlalchemy_event.listen(
        w.case.database.engine.sync_engine, "before_cursor_execute", count_statement
    )
    try:
        response = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    finally:
        sqlalchemy_event.remove(
            w.case.database.engine.sync_engine, "before_cursor_execute", count_statement
        )
    assert response.status_code == 200, response.text
    exported = Calendar.from_ical(response.content).walk("VEVENT")
    assert len(exported) > 40 and len(statements) <= 15
    await w.login(w.teacher_name)
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 200
    assert (
        await w.case.client.post("/api/v1/timetable/school-years", json={"school_year": 2100})
    ).status_code == 403
    w.case.as_admin()
    year = state["years"][0]
    first = state["events"][0]
    block = {
        key: value
        for key, value in year["series"][0].items()
        if key in {"starts_on", "start_slot", "duration_slots", "teacher_id", "title", "interval"}
    }
    response = await w.case.client.put(
        f"/api/v1/timetable/years/{year['id']}/series/{first['series_id']}",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "occurrence": first["source_date"],
            "scope": "one",
            "block": {**block, "title": "Replacement"},
        },
    )
    assert response.status_code == 200, response.text
    assert (
        "Cours - REPLACEMENT"
        in (await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")).text
    )
    agenda = (await w.board())["calendars"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "is_paused": True,
            "confirmed_live": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        Calendar.from_ical(
            (await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
        ).walk("VEVENT")
        == []
    )
    await w.login(w.teacher_name)
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 404


@pytest.mark.asyncio
async def test_school_year_is_required_and_ever_used_availability_prevents_deletion(
    workspace: Workspace,
) -> None:
    """Require explicit tags and retain their usage marker even after availability reset."""
    w = workspace
    endpoint = "/api/v1/timetable/school-years"
    response = await w.case.client.post(
        "/api/v1/timetable/calendars",
        json={"name": w.case.prefix + "untagged", "settings": w.settings},
    )
    assert response.status_code == 422
    response = await w.case.client.post(endpoint, json={"school_year": 2080})
    revision = response.json()["revision"]
    assert response.status_code == 201
    assert (
        await w.case.client.request(
            "DELETE", endpoint + "/2080", json={"expected_revision": revision}
        )
    ).status_code == 200
    response = await w.case.client.post(endpoint, json={"school_year": 2080})
    revision = response.json()["revision"]
    try:
        availability = f"/api/v1/timetable/staff/2080/{w.teacher_id}/availability"
        response = await w.case.client.put(availability, json={"ranges": []})
        assert response.status_code == 200, response.text
        response = await w.case.client.put(
            availability, json={"ranges": None, "expected_revision": response.json()["revision"]}
        )
        assert response.status_code == 200
        assert (
            await w.case.client.request(
                "DELETE", endpoint + "/2080", json={"expected_revision": revision}
            )
        ).status_code == 409
        for invalid in [
            {"weekday": 5, "start": 40000, "end": 44000},
            {"weekday": 0, "start": 28000, "end": 30000},
        ]:
            assert (
                await w.case.client.put(availability, json={"ranges": [invalid]})
            ).status_code == 422
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.school_year == 2080)
            )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == 2080)
            )


@pytest.mark.asyncio
async def test_active_promotion_uniqueness_is_also_enforced_by_postgresql(
    workspace: Workspace,
) -> None:
    """Protect the assignment invariant even if a writer bypasses the normal service validation."""
    w = workspace
    other = await w.create()
    with pytest.raises(IntegrityError):
        async with w.case.database.sessions.begin() as session:
            calendar = await session.get(TimetableCalendar, other)
            calendar.promotion_id = w.promotion_id
            await session.flush()
    state = await w.board()
    response = await w.case.client.post(
        "/api/v1/timetable/calendars",
        json={
            "name": state["calendars"][0]["name"].upper(),
            "is_paused": True,
            "settings": w.settings,
            "school_year": w.school_year,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_event_preview_is_read_only_and_uses_actual_lunch_checks(
    workspace: Workspace,
) -> None:
    """Show critical meal diagnostics before saving, without introducing any compact series row."""
    w = workspace
    state = await w.board()
    year = state["years"][0]
    beginning = date.fromisoformat(w.settings["start"])
    beginning += timedelta(days=(-beginning.weekday()) % 7)
    while beginning < date.today():
        beginning += timedelta(days=7)
    response = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/preview",
        json={
            "expected_revision": year["revision"],
            "block": {
                "starts_on": beginning.isoformat(),
                "start_slot": 9,
                "duration_slots": 2,
                "title": "Midday",
                "teacher_id": w.teacher_id,
                "interval": 0,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert any(
        issue["code"].startswith("lunch-") and issue["severity"] == "critical"
        for issue in response.json()["issues"]
    )
    assert (await w.board())["years"][0]["series"] == []
    await w.login(w.teacher_name)
    assert (
        await w.case.client.post(
            f"/api/v1/timetable/years/{year['id']}/preview",
            json={"expected_revision": year["revision"], "block": None},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_future_year_bookings_and_availability_do_not_affect_current_year(
    workspace: Workspace,
) -> None:
    """Keep actual persisted bookings and availability isolated by their academic-year tag."""
    w = workspace
    future_year = w.school_year + 1
    response = await w.case.client.post(
        "/api/v1/timetable/school-years", json={"school_year": future_year}
    )
    assert response.status_code == 201, response.text
    future_calendar = None
    try:
        response = await w.case.client.put(
            f"/api/v1/timetable/staff/{future_year}/{w.teacher_id}/availability",
            json={"ranges": []},
        )
        assert response.status_code == 200, response.text
        response = await w.case.client.post(
            "/api/v1/timetable/calendars",
            json={
                "name": w.case.prefix + "future",
                "school_year": future_year,
                "settings": {
                    **w.settings,
                    "start": f"{future_year}-09-01",
                    "end": f"{future_year + 1}-08-31",
                },
                "is_paused": True,
            },
        )
        assert response.status_code == 201, response.text
        future_calendar = response.json()["id"]
        future = (await w.board(future_calendar))["years"][0]
        beginning = date(future_year, 9, 1)
        beginning += timedelta(days=(-beginning.weekday()) % 7)
        response = await w.case.client.post(
            f"/api/v1/timetable/years/{future['id']}/series",
            json={
                "expected_revision": future["revision"],
                "block": {
                    "starts_on": beginning.isoformat(),
                    "start_slot": 0,
                    "duration_slots": 2,
                    "teacher_id": w.teacher_id,
                    "title": "Future only",
                    "interval": 1,
                },
            },
        )
        assert response.status_code == 201, response.text
        assert any(
            "Disponibilité" in warning for warning in (await w.board(future_calendar))["warnings"]
        )
        current = await w.add()
        assert current["teacher_commitments"] == []
        assert not any("Disponibilité" in warning for warning in current["warnings"])
    finally:
        async with w.case.database.sessions.begin() as session:
            if future_calendar is not None:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id == future_calendar)
                )
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.school_year == future_year)
            )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == future_year)
            )


@pytest.mark.asyncio
async def test_free_schedule_round_trips_through_recurrence_edits_and_personal_ics(
    workspace: Workspace,
) -> None:
    """Keep exact custom times through the actual SQL, dated exception and ICS pipeline."""
    w = workspace
    state = await w.add(start_time=50820, end_time=53070, title="Exact custom course")
    assert all(
        event["start"][11:19] == "14:07:00" and event["end"][11:19] == "14:44:30"
        for event in state["events"]
    )
    state = await w.broadcast()
    year = state["years"][0]
    original = state["events"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/years/{year['id']}/series/{original['series_id']}",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "occurrence": original["source_date"],
            "scope": "one",
            "block": {
                "starts_on": original["source_date"],
                "start_time": 51060,
                "end_time": 52140,
                "teacher_id": w.teacher_id,
                "title": "Changed exact occurrence",
                "interval": 1,
            },
        },
    )
    assert response.status_code == 200, response.text
    await w.login(w.pupil_name)
    response = await w.case.client.get("/api/v1/timetable/subscription")
    token = response.json()["token"]
    response = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    events = Calendar.from_ical(response.content).walk("VEVENT")
    changed = next(
        event for event in events if str(event["summary"]) == "Cours - CHANGED EXACT OCCURRENCE"
    )
    assert changed.decoded("dtstart").astimezone(PARIS).strftime("%H:%M:%S") == "14:11:00"
    assert changed.decoded("dtend").astimezone(PARIS).strftime("%H:%M:%S") == "14:29:00"


@pytest.mark.asyncio
async def test_saved_unique_event_becomes_recurring_and_detached_nodes_stay_independent(
    workspace: Workspace,
) -> None:
    """Round-trip the linked chain behavior through real API previews and persisted SQL rows."""
    w = workspace
    state = await w.add(interval=0)
    first = state["events"][0]
    year = state["years"][0]
    endpoint = f"/api/v1/timetable/years/{year['id']}/series/{first['series_id']}"
    block = {"starts_on": first["source_date"], "title": "Weekly", "interval": 1}
    response = await w.case.client.put(
        endpoint,
        json={
            "expected_revision": year["revision"],
            "occurrence": first["source_date"],
            "scope": "one",
            "block": block,
        },
    )
    assert response.status_code == 200, response.text
    state = await w.board()
    assert len(state["events"]) > 40
    tenth = state["events"][9]
    ninth = state["events"][8]
    response = await w.case.client.put(
        endpoint,
        json={
            "expected_revision": state["years"][0]["revision"],
            "occurrence": tenth["source_date"],
            "scope": "one",
            "block": {**block, "starts_on": tenth["source_date"], "title": "Detached"},
        },
    )
    assert response.status_code == 200, response.text
    state = await w.board()
    detached = next(event for event in state["events"] if event["title"] == "Detached")
    assert detached["id"] == tenth["id"] and detached["series_id"] != tenth["series_id"]
    proposal = {
        "expected_revision": state["years"][0]["revision"],
        "occurrence": ninth["source_date"],
        "scope": "future",
        "block": {**block, "starts_on": ninth["source_date"], "title": "Future", "start_slot": 4},
    }
    preview = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/preview",
        json={**proposal, "series_id": first["series_id"]},
    )
    assert preview.status_code == 200, preview.text
    assert (
        next(event for event in preview.json()["events"] if event["title"] == "Detached")
        == detached
    )
    assert (await w.case.client.put(endpoint, json=proposal)).status_code == 200
    final = await w.board()
    assert [event for event in final["events"] if event["source_date"] == tenth["source_date"]] == [
        detached
    ]


@pytest.mark.asyncio
async def test_archived_custom_members_remain_editable_without_calendar_access(
    workspace: Workspace,
) -> None:
    """Keep archived memberships movable while denying login, subscription and feed contents."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Preserved", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    group = response.json()
    await w.add(title="Preserved option", target_kind="custom", target_number=group["id"])
    await w.broadcast()
    await w.login(w.pupil_name)
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    student_cookie = dict(w.case.client.cookies)
    feed_path = f"/api/v1/timetable/feed/{token}.ics"
    assert Calendar.from_ical((await w.case.client.get(feed_path)).content).walk("VEVENT")
    w.case.as_admin()
    response = await w.case.client.patch(
        f"/api/v1/admin/users/{w.pupil_id}/archive", json={"archived": True}
    )
    assert response.status_code == 204, response.text
    groups = (await w.case.client.get(path + "/groups")).json()["groups"]
    assert groups[0]["student_ids"] == [w.pupil_id]
    response = await w.case.client.put(
        path + f"/{group['id']}",
        json={
            "name": "Preserved renamed",
            "student_ids": [w.pupil_id],
            "expected_revision": group["revision"],
            "confirmed_live": True,
        },
    )
    assert response.status_code == 200, response.text
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Moved archived", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    for invalid in ([w.teacher_id], [w.pupil_id, w.pupil_id]):
        response = await w.case.client.put(
            path + "/0",
            json={"name": "Invalid", "student_ids": invalid, "expected_revision": None},
        )
        assert response.status_code == 422, response.text
    w.case.client.cookies.clear()
    w.case.client.cookies.update(student_cookie)
    assert (await w.case.client.get("/api/v1/timetable/subscription")).status_code == 401
    assert not Calendar.from_ical((await w.case.client.get(feed_path)).content).walk("VEVENT")
    response = await w.case.client.post(
        "/api/v1/auth/login", json={"identifier": w.pupil_name, "password": PASSWORD}
    )
    assert response.status_code == 401, response.text
    w.case.as_admin()
    response = await w.case.client.delete(
        f"/api/v1/admin/users/{w.pupil_id}/promotions/{w.promotion_id}"
    )
    assert response.status_code == 204, response.text
    assert all(
        w.pupil_id not in item["student_ids"]
        for item in (await w.case.client.get(path + "/groups")).json()["groups"]
    )
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Former pupil", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_named_groups_overlap_validate_roster_and_drive_personal_feeds(
    workspace: Workspace,
) -> None:
    """Authorize named audiences, confirm live changes and export only current recipients."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    for ids in ([], [w.teacher_id], [w.pupil_id, w.pupil_id]):
        response = await w.case.client.put(
            path + "/0", json={"name": "German", "student_ids": ids, "expected_revision": None}
        )
        assert response.status_code == 422, response.text
    group_ids = []
    for name in ("German", "European section"):
        response = await w.case.client.put(
            path + "/0", json={"name": name, "student_ids": [w.pupil_id], "expected_revision": None}
        )
        assert response.status_code == 200, response.text
        group_ids.append(response.json()["id"])
    response = await w.case.client.get(path + "/groups")
    assert len(response.json()["groups"]) == 2
    state = await w.add(title="German option", target_kind="custom", target_number=group_ids[0])
    assert all(event["audience_label"] == "German" for event in state["events"])
    assert any(
        group["kind"] == "custom" and group["student_ids"] == [w.pupil_id]
        for group in state["groups"]
    )
    assert not any(issue["code"].startswith("balance-") for issue in state["issues"])
    await w.broadcast()
    group = response.json()["groups"][0]
    body = {
        "name": group["name"] + " updated",
        "student_ids": [w.pupil_id],
        "expected_revision": group["revision"],
    }
    assert (await w.case.client.put(path + f"/{group['id']}", json=body)).status_code == 409
    assert (
        await w.case.client.put(path + f"/{group['id']}", json={**body, "confirmed_live": True})
    ).status_code == 200
    await w.login(w.pupil_name)
    assert (await w.case.client.get(path + "/groups")).status_code == 403
    assert (
        await w.case.client.put(path + "/0", json={**body, "expected_revision": None})
    ).status_code == 403
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert len(Calendar.from_ical(feed.content).walk("VEVENT")) > 40
    await w.login(w.teacher_name)
    assert (
        await w.case.client.put(path + "/0", json={**body, "expected_revision": None})
    ).status_code == 403
    w.case.as_admin()
    assert (
        await w.case.client.put(path + f"/{group['id']}", json={**body, "confirmed_live": True})
    ).status_code == 409


@pytest.mark.asyncio
async def test_option_hours_exclude_pupils_outside_its_custom_group(workspace: Workspace) -> None:
    """Return annual and weekly option hours for participants through the actual board API."""
    w = workspace
    other_pupil, _ = await w.case.create()
    w.case.as_admin()
    response = await w.case.client.post(
        f"/api/v1/admin/promotions/{w.promotion_id}/users", json={"user_ids": [other_pupil]}
    )
    assert response.status_code == 204, response.text
    response = await w.case.client.post(
        "/api/v1/admin/subjects", json={"name": f"German option {w.case.prefix}"}
    )
    assert response.status_code == 201, response.text
    subject_id = response.json()["id"]
    try:
        response = await w.case.client.put(
            f"/api/v1/promotion-groups/{w.promotion_id}/custom/0",
            json={"name": "German", "student_ids": [w.pupil_id], "expected_revision": None},
        )
        assert response.status_code == 200, response.text
        state = await w.add(
            title="German option",
            subject_id=subject_id,
            target_kind="custom",
            target_number=response.json()["id"],
        )
        annual = state["years"][0]
        hours = next(row for row in annual["hours"] if row["subject_id"] == subject_id)
        session_count = sum(event["subject_id"] == subject_id for event in state["events"])
        assert session_count > 0
        assert hours["course"] == hours["total"] == session_count
        assert hours["weekly"]["total"] == pytest.approx(session_count / len(annual["weeks"]))
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableSeries).where(TimetableSeries.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))


@pytest.mark.asyncio
async def test_custom_group_layout_and_retirement_preserve_existing_sessions(
    workspace: Workspace,
) -> None:
    """Persist bubble positions and retire choices without losing assigned recipients."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    payload = {
        "name": "German",
        "student_ids": [w.pupil_id],
        "expected_revision": None,
        "x": 620,
        "y": 370,
    }
    assert (await w.case.client.put(path + "/0", json={**payload, "x": -1})).status_code == 422
    created = await w.case.client.put(path + "/0", json=payload)
    assert created.status_code == 200, created.text
    group = (await w.case.client.get(path + "/groups")).json()["groups"][0]
    assert group["x"] == 620 and group["y"] == 370
    await w.add(title="German option", target_kind="custom", target_number=group["id"])
    await w.broadcast()
    endpoint = path + f"/{group['id']}"
    version = {"expected_revision": group["revision"]}
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 409
    await w.login(w.pupil_name)
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    count = len(Calendar.from_ical(feed.content).walk("VEVENT"))
    assert count > 40
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 403
    await w.login(w.teacher_name)
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 403
    w.case.as_admin()
    assert (
        await w.case.client.request(
            "DELETE", endpoint, json={"expected_revision": "0" * 32, "confirmed_live": True}
        )
    ).status_code == 409
    response = await w.case.client.request(
        "DELETE", endpoint, json={**version, "confirmed_live": True}
    )
    assert response.status_code == 200, response.text
    assert (await w.case.client.get(path + "/groups")).json()["groups"] == []
    state = await w.board()
    assert state["events"] and all(event["audience_label"] == "German" for event in state["events"])
    year = state["years"][0]
    response = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/series",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "block": {
                "starts_on": state["events"][0]["source_date"],
                "title": "Retired audience",
                "target_kind": "custom",
                "target_number": group["id"],
            },
        },
    )
    assert response.status_code == 422
    replacement = await w.case.client.put(path + "/0", json=payload)
    assert replacement.status_code == 200 and replacement.json()["id"] != group["id"]
    await w.login(w.pupil_name)
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert len(Calendar.from_ical(feed.content).walk("VEVENT")) == count


@pytest.mark.asyncio
async def test_past_year_rejection_and_automatic_rollover_policy(workspace: Workspace) -> None:
    """Apply September archival once, honor disabling and preserve manual restoration."""
    w = workspace
    assert (
        await w.case.client.post(
            "/api/v1/timetable/school-years", json={"school_year": w.school_year - 1}
        )
    ).status_code == 422
    await w.add()
    await w.broadcast()
    config = (await w.case.client.get("/api/v1/timetable/configuration")).json()
    assert config["preferences"]["auto_archive"]
    async with w.case.database.sessions.begin() as session:
        row = await session.get(TimetablePreferences, 1)
        saved_year = row.last_rollover_year
    try:
        result = await w.case.client.put(
            "/api/v1/timetable/preferences",
            json={"expected_revision": config["preferences"]["revision"], "auto_archive": False},
        )
        assert result.status_code == 200, result.text
        disabled = result.json()
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 1))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived
        result = await w.case.client.put(
            "/api/v1/timetable/preferences",
            json={"expected_revision": disabled["revision"], "auto_archive": True},
        )
        assert result.status_code == 200, result.text
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 8, 31))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived
        before_revision = (await w.board())["years"][0]["revision"]
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 1))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert calendar.is_archived and calendar.is_paused
            annual = await session.scalar(
                select(TimetableYear).where(TimetableYear.calendar_id == calendar.id)
            )
            assert annual.revision != before_revision
            calendar.is_archived = False
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 2))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived and calendar.is_paused
    finally:
        async with w.case.database.sessions.begin() as session:
            row = await session.get(TimetablePreferences, 1)
            row.auto_archive, row.last_rollover_year = True, saved_year
