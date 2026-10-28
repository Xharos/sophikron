"""Real shared settings, dated template versions, pause and group subscription boundaries."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from icalendar import Calendar
from sqlalchemy import delete, select
from sqlalchemy import event as sqlalchemy_event

from app.models import (
    Subject,
    TeacherAvailability,
    TeacherSubject,
    TimetableCalendar,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableSeries,
    TimetableTemplateVersion,
    TimetableYear,
)
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion
from tests.test_groups_postgres import preview_and_save

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@dataclass
class Workspace:
    """Own synthetic timetable references and real API convenience operations."""

    case: Harness
    promotion_id: int
    calendar_id: int
    year_id: int
    settings: dict
    subject_id: int
    room_id: int
    teachers: list[tuple[int, str]]
    pupils: list[tuple[int, str]]

    async def board(self) -> dict:
        """Read the administrator's current draft and revision."""
        self.case.as_admin()
        response = await self.case.client.get(
            "/api/v1/timetable/board",
            params={
                "calendar_ids": self.calendar_id,
                "school_year": date.fromisoformat(self.settings["start"]).year,
                "draft": "true",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def version(self, on: str, blocks: list[dict]) -> dict:
        """Append a weekly version using the actual observed draft revision."""
        state = await self.board()
        response = await self.case.client.put(
            f"/api/v1/timetable/years/{self.year_id}/template",
            json={
                "expected_revision": state["years"][0]["revision"],
                "effective_on": on,
                "acknowledge_history": True,
                "blocks": blocks,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def publish(self) -> None:
        """Publish the latest observed annual draft."""
        state = await self.board()
        response = await self.case.client.post(
            f"/api/v1/timetable/years/{self.year_id}/publish",
            json={"expected_revision": state["years"][0]["revision"]},
        )
        assert response.status_code == 200, response.text

    def block(self, **changes: object) -> dict:
        """Build a whole-class Monday template with a stable root identity."""
        return {
            "key": "a" * 32,
            "weekday": 0,
            "start_slot": 0,
            "duration_slots": 2,
            "subject_id": self.subject_id,
            "teacher_id": self.teachers[0][0],
            "room_id": self.room_id,
            "title": "Maths",
            "interval": 1,
            "phase": 1,
            **changes,
        }

    async def login(self, username: str) -> None:
        """Authenticate a synthetic member through the real login endpoint."""
        self.case.client.cookies.clear()
        response = await self.case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text


@pytest_asyncio.fixture
async def workspace(auth_case: Harness) -> AsyncIterator[Workspace]:
    """Create and clean only records owned by this isolated PostgreSQL fixture."""
    case = auth_case
    promotion_id = await make_promotion(case, "WORKSPACE")
    calendar_id = subject_id = room_id = None
    today = date.today()
    beginning = today - timedelta(days=42 + today.weekday())
    settings = {
        "start": beginning.isoformat(),
        "end": (today + timedelta(days=140)).isoformat(),
        "breaks": [{"start": 35400, "end": 36600}, {"start": 43200, "end": 46800}],
    }
    teachers = []
    try:
        teachers = [await case.create("teacher") for _ in range(2)]
        pupils = [await case.create() for _ in range(4)]
        case.as_admin()
        response = await case.client.post(
            f"/api/v1/admin/promotions/{promotion_id}/users",
            json={"user_ids": [identifier for identifier, _ in teachers + pupils]},
        )
        assert response.status_code == 204, response.text
        async with case.database.sessions.begin() as session:
            subject = Subject(
                name="Maths", name_key=case.prefix, icon="book", color="#244BC1", is_active=True
            )
            session.add(subject)
            await session.flush()
            subject_id = subject.id
        response = await case.client.post("/api/v1/timetable/rooms", json={"name": case.prefix})
        assert response.status_code == 201, response.text
        room_id = response.json()["id"]
        response = await case.client.post(
            "/api/v1/timetable/calendars", json={"name": "PTSI", "promotion_id": promotion_id}
        )
        assert response.status_code == 201, response.text
        calendar_id = response.json()["id"]
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{calendar_id}/years", json={"settings": settings}
        )
        assert response.status_code == 201, response.text
        yield Workspace(
            case,
            promotion_id,
            calendar_id,
            response.json()["id"],
            settings,
            subject_id,
            room_id,
            teachers,
            pupils,
        )
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherAvailability).where(
                    TeacherAvailability.user_id.in_([identifier for identifier, _ in teachers])
                )
            )
            if calendar_id:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id == calendar_id)
                )
            if room_id:
                await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room_id))
            if subject_id:
                await session.execute(
                    delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
                )
                await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.execute(
                delete(TimetableSchoolYear).where(
                    TimetableSchoolYear.school_year == beginning.year,
                    ~select(TimetableYear.id)
                    .where(TimetableYear.school_year == TimetableSchoolYear.school_year)
                    .exists(),
                )
            )
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_external_teacher_bookings_are_symmetric_private_and_publication_scoped(
    workspace: Workspace,
) -> None:
    """Expose anonymous external bookings in both boards without leaking private recipients."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    response = await case.client.post(
        "/api/v1/timetable/calendars",
        json={"name": "Deuxième année", "promotion_id": w.promotion_id},
    )
    assert response.status_code == 201, response.text
    extra_id = response.json()["id"]
    params = {
        "calendar_ids": extra_id,
        "school_year": date.fromisoformat(w.settings["start"]).year,
        "draft": "true",
    }
    try:
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{extra_id}/years", json={"settings": w.settings}
        )
        assert response.status_code == 201, response.text
        extra_year = response.json()
        response = await case.client.put(
            f"/api/v1/timetable/years/{extra_year['id']}/template",
            json={
                "expected_revision": extra_year["revision"],
                "effective_on": w.settings["start"],
                "acknowledge_history": True,
                "blocks": [w.block(key="b" * 32)],
            },
        )
        assert response.status_code == 200, response.text
        first_board = await w.board()
        commitments = first_board["teacher_commitments"]
        assert commitments and {item["calendar_id"] for item in commitments} == {extra_id}
        assert all(item["start"][:10] >= date.today().isoformat() for item in commitments)
        second_board = (await case.client.get("/api/v1/timetable/board", params=params)).json()
        assert {item["calendar_id"] for item in second_board["teacher_commitments"]} == {
            w.calendar_id
        }
        assert {item["source_date"] for item in commitments} == {
            item["source_date"] for item in second_board["teacher_commitments"]
        }
        private_title = "Private pupil meeting"
        future = commitments[0]["source_date"]
        response = await case.client.post(
            f"/api/v1/timetable/years/{extra_year['id']}/series",
            json={
                "expected_revision": second_board["years"][0]["revision"],
                "block": {
                    "starts_on": future,
                    "start_slot": 0,
                    "duration_slots": 1,
                    "subject_id": w.subject_id,
                    "teacher_id": w.teachers[1][0],
                    "room_id": w.room_id,
                    "title": private_title,
                    "interval": 0,
                    "kind": "kholle",
                    "target_kind": "student",
                    "target_user_id": w.pupils[0][0],
                },
            },
        )
        assert response.status_code == 201, response.text
        commitments = (await w.board())["teacher_commitments"]
        assert {item["teacher_id"] for item in commitments} == {item[0] for item in w.teachers}
        expected_fields = {
            "series_id",
            "conflict_key",
            "source_date",
            "teacher_id",
            "start",
            "end",
            "calendar_id",
            "year_id",
            "calendar_label",
        }
        assert all(set(item) == expected_fields for item in commitments)
        assert private_title not in str(commitments)
        await w.publish()
        await w.login(w.teachers[0][1])
        published_params = {**params, "calendar_ids": w.calendar_id, "draft": "false"}
        public_board = await case.client.get("/api/v1/timetable/board", params=published_params)
        assert public_board.status_code == 200, public_board.text
        assert public_board.json()["teacher_commitments"] == []
        assert (await case.client.get("/api/v1/timetable/board", params=params)).status_code == 403
        case.as_admin()
        second_board = (await case.client.get("/api/v1/timetable/board", params=params)).json()
        response = await case.client.post(
            f"/api/v1/timetable/years/{extra_year['id']}/publish",
            json={"expected_revision": second_board["years"][0]["revision"]},
        )
        assert response.status_code == 200, response.text
        await w.login(w.teachers[0][1])
        public_board = await case.client.get("/api/v1/timetable/board", params=published_params)
        assert public_board.status_code == 200, public_board.text
        assert {item["teacher_id"] for item in public_board.json()["teacher_commitments"]} == {
            w.teachers[0][0]
        }
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(TimetableCalendar).where(TimetableCalendar.id == extra_id))


@pytest.mark.asyncio
async def test_staff_occupancy_uses_all_pupils_and_calendars_without_exposing_rosters(
    workspace: Workspace,
) -> None:
    """Aggregate groups and empty/paused agendas independently of selected staff."""
    w, case = workspace, workspace.case
    params = {
        "school_year": date.fromisoformat(w.settings["start"]).year,
        "teacher_ids": str(w.teachers[0][0]),
        "include_occupancy": "true",
    }

    async def read_occupancy() -> dict:
        """Read the current authorized anonymous occupancy response."""
        response = await case.client.get("/api/v1/timetable/staff/board", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    case.as_admin()
    assert (await read_occupancy())["occupied_ranges"] == []
    await preview_and_save(
        case,
        f"/api/v1/promotion-groups/{w.promotion_id}",
        [identifier for identifier, _ in w.pupils],
        "halves",
    )
    first = w.block(target_kind="halves", target_number=1)
    second = w.block(
        key="b" * 32, target_kind="halves", target_number=2, teacher_id=w.teachers[1][0]
    )
    await w.version(w.settings["start"], [first])
    assert (await read_occupancy())["occupied_ranges"] == []
    await w.version(w.settings["start"], [first, second])
    expected = [{"weekday": 0, "start": 28800, "end": 32100}]
    result = await read_occupancy()
    assert result["occupied_ranges"] == expected
    assert all(set(item) == {"weekday", "start", "end"} for item in result["occupied_ranges"])
    assert all("target_user_id" not in event for event in result["events"])
    assert {event["teacher_id"] for event in result["events"]} == {w.teachers[0][0]}
    without = await case.client.get(
        "/api/v1/timetable/staff/board", params={**params, "include_occupancy": "false"}
    )
    assert without.json()["occupied_ranges"] == []
    await w.login(w.teachers[0][1])
    assert (await read_occupancy())["occupied_ranges"] == []  # Staff cannot inspect drafts.
    await w.publish()
    await w.login(w.teachers[1][1])
    assert (await read_occupancy())["occupied_ranges"] == expected
    case.as_admin()
    response = await case.client.post(
        "/api/v1/timetable/calendars", json={"name": "Autre classe", "promotion_id": w.promotion_id}
    )
    assert response.status_code == 201, response.text
    extra_id = response.json()["id"]
    try:
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{extra_id}/years", json={"settings": w.settings}
        )
        assert response.status_code == 201, response.text
        extra_year = response.json()
        assert (await read_occupancy())["occupied_ranges"] == []
        response = await case.client.put(
            f"/api/v1/timetable/years/{extra_year['id']}/template",
            json={
                "expected_revision": extra_year["revision"],
                "effective_on": w.settings["start"],
                "acknowledge_history": True,
                "blocks": [w.block(key="c" * 32, start_slot=1, duration_slots=1)],
            },
        )
        assert response.status_code == 200, response.text
        assert (await read_occupancy())["occupied_ranges"] == [
            {"weekday": 0, "start": 30450, "end": 32100}
        ]
        async with case.database.sessions.begin() as session:
            row = await session.get(TimetableCalendar, extra_id)
            row.is_paused = True
        assert (await read_occupancy())["occupied_ranges"] == expected
        async with case.database.sessions.begin() as session:
            row = await session.get(TimetableCalendar, extra_id)
            row.is_paused, row.is_deleted = False, True
        assert (await read_occupancy())["occupied_ranges"] == expected
        await w.login(w.pupils[0][1])
        assert (
            await case.client.get("/api/v1/timetable/staff/board", params=params)
        ).status_code == 403
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(TimetableCalendar).where(TimetableCalendar.id == extra_id))


@pytest.mark.asyncio
async def test_staff_availability_permissions_revisions_and_nonblocking_warnings(
    workspace: Workspace,
) -> None:
    """Exercise real annual persistence, staff read-only access, drafts and safe publication."""
    w, case = workspace, workspace.case
    year = date.fromisoformat(w.settings["start"]).year
    teacher_id = w.teachers[0][0]
    path = f"/api/v1/timetable/staff/{year}/{teacher_id}/availability"
    params = {"school_year": year, "teacher_ids": str(teacher_id)}
    response = await case.client.get("/api/v1/timetable/staff/catalog")
    assert response.status_code == 200, response.text
    assert teacher_id in {row["id"] for row in response.json()["teachers"]}
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    assert next(item for item in catalog["teachers"] if item["id"] == teacher_id)["roles"] == [
        "teacher"
    ]
    response = await case.client.get("/api/v1/timetable/staff/board", params=params)
    assert response.status_code == 200, response.text
    initial = response.json()["availability"][0]
    assert initial["default"] and initial["revision"] is None and initial["ranges"]
    response = await case.client.put(path, json={"ranges": []})
    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
    assert (await case.client.put(path, json={"ranges": []})).status_code == 409
    invalid = await case.client.put(
        path,
        json={
            "expected_revision": revision,
            "ranges": [{"weekday": 5, "start": 28800, "end": 32100}],
        },
    )
    assert invalid.status_code == 422, invalid.text
    await w.version(w.settings["start"], [w.block()])
    state = await w.board()
    warnings = [text for text in state["warnings"] if text.startswith("Disponibilité de ")]
    assert all(event["teacher_roles"] == ["teacher"] for event in state["events"])
    assert all(
        event["template_key"] == "a" * 32 and not event["is_exception"] for event in state["events"]
    )
    assert len(warnings) == 1
    assert date.fromisoformat(warnings[0].split("le ")[-1][:10]) >= date.today()
    await w.publish()
    response = await case.client.get("/api/v1/timetable/staff/board", params=params)
    assert response.json()["events"]
    assert all("target_user_id" not in event for event in response.json()["events"])
    assert all(event["audience_label"] == "Classe entière" for event in response.json()["events"])
    assert all(event["calendar_label"] for event in response.json()["events"])
    await w.login(w.teachers[0][1])
    assert (await case.client.get("/api/v1/timetable/staff/catalog")).status_code == 200
    assert (
        await case.client.get("/api/v1/timetable/staff/board", params=params)
    ).status_code == 200
    assert (
        await case.client.put(path, json={"expected_revision": revision, "ranges": None})
    ).status_code == 403
    kholleur_id, kholleur_name = await case.create("kholleur")
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    assert next(item for item in catalog["teachers"] if item["id"] == kholleur_id)["roles"] == [
        "kholleur"
    ]
    await w.login(kholleur_name)
    assert (await case.client.get("/api/v1/timetable/staff/catalog")).status_code == 200
    assert (
        await case.client.put(path, json={"expected_revision": revision, "ranges": None})
    ).status_code == 403
    await w.login(w.pupils[0][1])
    assert (await case.client.get("/api/v1/timetable/staff/catalog")).status_code == 403
    assert (
        await case.client.get("/api/v1/timetable/staff/board", params=params)
    ).status_code == 403
    case.as_admin()
    assert (
        await case.client.put(path, json={"expected_revision": revision, "ranges": None})
    ).status_code == 200
    response = await case.client.get("/api/v1/timetable/staff/board", params=params)
    assert response.json()["availability"][0]["default"]


@pytest.mark.asyncio
async def test_staff_workspace_consolidates_selected_agendas_and_isolates_annual_patterns(
    workspace: Workspace,
) -> None:
    """Combine only selected teachers' assignments and preserve publication/year boundaries."""
    w, case = workspace, workspace.case
    year = date.fromisoformat(w.settings["start"]).year
    teacher, other_teacher = (row[0] for row in w.teachers)
    second_calendar = None
    future_year = year + 6
    try:
        await w.version(w.settings["start"], [w.block()])
        await w.publish()
        response = await case.client.post(
            "/api/v1/timetable/calendars", json={"name": "Teaching consolidation"}
        )
        assert response.status_code == 201, response.text
        second_calendar = response.json()["id"]
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{second_calendar}/years", json={"settings": w.settings}
        )
        assert response.status_code == 201, response.text
        second_year = response.json()["id"]
        response = await case.client.get(
            "/api/v1/timetable/board",
            params={"calendar_ids": second_calendar, "school_year": year, "draft": "true"},
        )
        response = await case.client.put(
            f"/api/v1/timetable/years/{second_year}/template",
            json={
                "expected_revision": response.json()["years"][0]["revision"],
                "effective_on": w.settings["start"],
                "acknowledge_history": True,
                "blocks": [w.block(key="b" * 32, teacher_id=other_teacher, title="Draft only")],
            },
        )
        assert response.status_code == 200, response.text
        params = {"school_year": year, "teacher_ids": f"{teacher},{other_teacher}"}
        response = await case.client.get("/api/v1/timetable/staff/board", params=params)
        assert response.status_code == 200, response.text
        events = response.json()["events"]
        assert {event["teacher_id"] for event in events} == {teacher, other_teacher}
        assert {event["calendar_id"] for event in events} == {w.calendar_id, second_calendar}
        assert {event["session_minutes"] for event in events} == {55}
        response = await case.client.get(
            "/api/v1/timetable/staff/board", params={**params, "teacher_ids": str(teacher)}
        )
        assert {event["teacher_id"] for event in response.json()["events"]} == {teacher}
        await w.login(w.teachers[0][1])
        response = await case.client.get("/api/v1/timetable/staff/board", params=params)
        assert {event["calendar_id"] for event in response.json()["events"]} == {w.calendar_id}
        assert "Draft only" not in response.text
        case.as_admin()
        future_settings = {
            **w.settings,
            "start": f"{future_year}-09-01",
            "end": f"{future_year + 1}-06-30",
        }
        response = await case.client.put(
            "/api/v1/timetable/configuration", json={"settings": future_settings}
        )
        assert response.status_code == 200, response.text
        response = await case.client.put(
            f"/api/v1/timetable/staff/{future_year}/{teacher}/availability", json={"ranges": []}
        )
        assert response.status_code == 200, response.text
        response = await case.client.get(
            "/api/v1/timetable/staff/board",
            params={"school_year": future_year, "teacher_ids": str(teacher)},
        )
        assert response.json()["availability"][0]["ranges"] == []
        response = await case.client.get(
            "/api/v1/timetable/staff/board",
            params={"school_year": year, "teacher_ids": str(teacher)},
        )
        assert response.json()["availability"][0]["default"] is True
        assert response.json()["availability"][0]["ranges"]
    finally:
        async with case.database.sessions.begin() as session:
            if second_calendar is not None:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id == second_calendar)
                )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == future_year)
            )


@pytest.mark.asyncio
async def test_unassigned_events_save_publish_and_export_without_false_warnings(
    workspace: Workspace,
) -> None:
    """Round-trip optional assignments through templates, edits and authorized subscriptions."""
    w, case = workspace, workspace.case
    fields = {"subject_id": None, "teacher_id": None, "room_id": None, "title": "Réunion"}
    await w.version(w.settings["start"], [w.block(**fields)])
    state = await w.board()
    assert not state["warnings"]
    assert not state["issues"]
    event = state["events"][0]
    assert all(event[field] is None for field in ("subject_id", "teacher_id", "room_id"))
    assert event["title"] == "Réunion"
    assert event["room"] == event["teacher"] == ""
    assert event["teacher_available"] is True
    assert event["color"] == "#64748B"
    revision = state["years"][0]["revision"]
    dated = {**fields, "starts_on": w.settings["start"], "start_slot": 4, "interval": 0}
    for title in ["", "   "]:
        response = await case.client.post(
            f"/api/v1/timetable/years/{w.year_id}/series",
            json={"expected_revision": revision, "block": {**dated, "title": title}},
        )
        assert response.status_code == 422, response.text
    for field in ("subject_id", "teacher_id", "room_id"):
        response = await case.client.post(
            f"/api/v1/timetable/years/{w.year_id}/series",
            json={"expected_revision": revision, "block": {**dated, field: 999999999}},
        )
        assert response.status_code == 422, response.text
    response = await case.client.post(
        f"/api/v1/timetable/years/{w.year_id}/series",
        json={"expected_revision": revision, "block": dated},
    )
    assert response.status_code == 201, response.text
    state = await w.board()
    assert not state["warnings"]
    assert len(state["years"][0]["series"]) == 2
    async with case.database.sessions() as session:
        rows = list(
            await session.scalars(
                select(TimetableSeries).where(TimetableSeries.year_id == w.year_id)
            )
        )
        assert all(
            row.subject_id is None and row.teacher_id is None and row.room_id is None
            for row in rows
        )
    source = next(item for item in state["years"][0]["series"] if item["interval"] == 0)
    response = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/series/{source['id']}",
        json={
            "expected_revision": state["years"][0]["revision"],
            "occurrence": source["starts_on"],
            "scope": "one",
            "block": {**dated, "title": "Réunion ponctuelle"},
        },
    )
    assert response.status_code == 200, response.text
    await w.publish()
    await w.login(w.pupils[0][1])
    token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    events = Calendar.from_ical(response.content).walk("VEVENT")
    assert {str(item["SUMMARY"]) for item in events} == {"Réunion", "Réunion ponctuelle"}
    assert all("LOCATION" not in item and "None" not in str(item["DESCRIPTION"]) for item in events)
    denied = await case.client.post(
        f"/api/v1/timetable/years/{w.year_id}/series",
        json={"expected_revision": state["years"][0]["revision"], "block": dated},
    )
    assert denied.status_code == 403
    await w.login(w.teachers[0][1])
    token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    assert not Calendar.from_ical(response.content).walk("VEVENT")


@pytest.mark.asyncio
async def test_unchanged_templates_keep_versions_revisions_and_occurrences(
    workspace: Workspace,
) -> None:
    """Skip empty and reordered saves without changing publication or stable occurrence IDs."""
    w, case = workspace, workspace.case
    initial = await w.board()
    empty = await w.version(w.settings["start"], [])
    assert empty == {
        "revision": initial["years"][0]["revision"],
        "number": None,
        "changed": False,
    }
    blocks = [w.block(), w.block(key="b" * 32, weekday=1)]
    saved = await w.version(w.settings["start"], blocks)
    assert saved["changed"] is True and saved["number"] == 1
    await w.publish()
    before = await w.board()
    unchanged = await w.version(date.today().isoformat(), list(reversed(blocks)))
    assert unchanged == {"revision": saved["revision"], "number": 1, "changed": False}
    assert await w.board() == before
    async with case.database.sessions() as session:
        versions = list(
            await session.scalars(
                select(TimetableTemplateVersion).where(
                    TimetableTemplateVersion.year_id == w.year_id
                )
            )
        )
        assert len(versions) == 1
    updated = await w.version(date.today().isoformat(), [w.block(teacher_id=w.teachers[1][0])])
    assert updated["changed"] is True and updated["number"] == 2
    assert updated["revision"] != saved["revision"]


@pytest.mark.asyncio
async def test_unchanged_legacy_template_does_not_create_a_version(workspace: Workspace) -> None:
    """Recognize a legacy recurring pattern before creating its first versioned snapshot."""
    w, case = workspace, workspace.case
    initial = await w.board()
    block = w.block()
    for field in ("key", "weekday", "phase"):
        block.pop(field)
    response = await case.client.post(
        f"/api/v1/timetable/years/{w.year_id}/series",
        json={
            "expected_revision": initial["years"][0]["revision"],
            "block": {**block, "starts_on": w.settings["start"]},
        },
    )
    assert response.status_code == 201, response.text
    before = await w.board()
    template = await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")
    assert template.status_code == 200, template.text
    unchanged = await w.version(w.settings["start"], template.json()["blocks"])
    assert unchanged == {
        "revision": before["years"][0]["revision"],
        "number": None,
        "changed": False,
    }
    assert await w.board() == before
    template = await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")
    assert template.json()["versions"] == []


@pytest.mark.asyncio
async def test_workspace_effective_versions_pause_and_preserved_exceptions(
    workspace: Workspace,
) -> None:
    """Freeze subscriptions in pause and preserve V1 history, a replacement and a cancellation."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    await w.login(w.pupils[0][1])
    token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    original_feed = (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
    state = await w.board()
    initial = state["events"]
    effective = date.today()
    future = effective + timedelta(days=(7 - effective.weekday()) % 7 + 14)
    source_id = initial[0]["series_id"]
    replacement = {
        "starts_on": future.isoformat(),
        "start_slot": 0,
        "duration_slots": 2,
        "subject_id": w.subject_id,
        "teacher_id": w.teachers[0][0],
        "room_id": w.room_id,
        "title": "Exception retained",
        "interval": 1,
    }
    for day, value in ((future, replacement), (future + timedelta(weeks=1), None)):
        state = await w.board()
        response = await case.client.put(
            f"/api/v1/timetable/years/{w.year_id}/series/{source_id}",
            json={
                "expected_revision": state["years"][0]["revision"],
                "occurrence": day.isoformat(),
                "scope": "one",
                "block": value,
            },
        )
        assert response.status_code == 200, response.text
    assert (await w.version(effective.isoformat(), [w.block(teacher_id=w.teachers[1][0])]))[
        "number"
    ] == 2
    state = await w.board()
    assert {
        event["teacher_id"]
        for event in state["events"]
        if event["start"][:10] < effective.isoformat()
    } == {w.teachers[0][0]}
    assert any(event["title"] == "Exception retained" for event in state["events"])
    assert not any(
        event["source_date"] == (future + timedelta(weeks=1)).isoformat()
        for event in state["events"]
    )
    assert all(
        event["id"] in {item["id"] for item in state["events"]}
        for event in initial
        if event["start"][:10] < effective.isoformat()
    )
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    agenda = next(item for item in catalog["calendars"] if item["id"] == w.calendar_id)
    response = await case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "is_paused": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        await case.client.post(
            f"/api/v1/timetable/years/{w.year_id}/publish",
            json={"expected_revision": state["years"][0]["revision"]},
        )
    ).status_code == 409
    assert (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content == original_feed
    response = await case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": response.json()["revision"],
            "is_paused": False,
        },
    )
    assert response.status_code == 200, response.text
    await w.publish()
    await w.version(
        (effective + timedelta(weeks=1)).isoformat(), [w.block(teacher_id=w.teachers[0][0])]
    )
    history = (await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")).json()
    assert [item["number"] for item in history["versions"]] == [1, 2, 3]
    async with case.database.sessions() as session:
        versions = list(
            await session.scalars(
                select(TimetableTemplateVersion)
                .where(TimetableTemplateVersion.year_id == w.year_id)
                .order_by(TimetableTemplateVersion.number)
            )
        )
        assert versions[0].blocks[0]["teacher_id"] == w.teachers[0][0]
        assert versions[1].blocks[0]["teacher_id"] == w.teachers[1][0]
    state = await w.board()
    invalid = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/template",
        json={
            "expected_revision": state["years"][0]["revision"],
            "effective_on": effective.isoformat(),
            "blocks": [],
        },
    )
    assert invalid.status_code == 422
    payload = {
        "expected_revision": state["years"][0]["revision"],
        "effective_on": (effective + timedelta(weeks=2)).isoformat(),
        "blocks": [],
        "padding": "x" * 20000,
    }
    assert (
        await case.client.put(f"/api/v1/timetable/years/{w.year_id}/template", json=payload)
    ).status_code == 422
    payload["padding"] = "x" * 270000
    assert (
        await case.client.put(f"/api/v1/timetable/years/{w.year_id}/template", json=payload)
    ).status_code == 413


@pytest.mark.asyncio
async def test_workspace_future_edit_cannot_change_weekly_template(
    workspace: Workspace,
) -> None:
    """Reject edits to future template occurrences without changing any generated session."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block(interval=2, phase=2)])
    state = await w.board()
    chosen = next(
        event for event in state["events"] if event["source_date"] >= date.today().isoformat()
    )
    block = {
        key: value
        for key, value in w.block(interval=1).items()
        if key not in {"key", "weekday", "phase"}
    }
    block["starts_on"] = chosen["source_date"]
    response = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/series/{chosen['series_id']}",
        json={
            "expected_revision": state["years"][0]["revision"],
            "occurrence": chosen["source_date"],
            "scope": "future",
            "block": block,
        },
    )
    assert response.status_code == 422, response.text
    assert (await w.board()) == state


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["resize", "edit", "delete"])
async def test_workspace_template_occurrence_changes_remain_isolated(
    workspace: Workspace, action: str
) -> None:
    """Keep weekly blocks, other occurrences and the published snapshot after dated changes."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    before = await w.board()
    chosen = next(
        event for event in before["events"] if event["source_date"] >= date.today().isoformat()
    )
    replacement = {
        key: value for key, value in w.block().items() if key not in {"key", "weekday", "phase"}
    }
    replacement["starts_on"] = chosen["source_date"]
    if action == "resize":
        replacement["duration_slots"] = 3
    elif action == "edit":
        replacement["title"] = "Occurrence modifiée"
    payload = {
        "expected_revision": before["years"][0]["revision"],
        "occurrence": chosen["source_date"],
        "scope": "one",
        "block": None if action == "delete" else replacement,
    }
    # Even deletion must not bypass the scope restriction on the API.
    denied = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/series/{chosen['series_id']}",
        json={**payload, "scope": "future"},
    )
    assert denied.status_code == 422, denied.text
    response = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/series/{chosen['series_id']}", json=payload
    )
    assert response.status_code == 200, response.text
    after = await w.board()
    assert after["years"][0]["template_blocks"] == before["years"][0]["template_blocks"]
    assert after["years"][0]["published_revision"] == before["years"][0]["published_revision"]
    assert [e for e in after["events"] if e["source_date"] != chosen["source_date"]] == [
        e for e in before["events"] if e["source_date"] != chosen["source_date"]
    ]
    affected = [e for e in after["events"] if e["source_date"] == chosen["source_date"]]
    if action == "delete":
        assert affected == []
    else:
        assert affected and all(e["is_exception"] for e in affected)
        assert all(
            e["duration_slots"] == replacement["duration_slots"]
            and e["title"] == replacement["title"]
            for e in affected
        )


@pytest.mark.asyncio
async def test_workspace_group_filters_and_personal_subscriptions(workspace: Workspace) -> None:
    """Use live partitions for group feeds and refuse foreign pupil or unknown group targets."""
    w, case = workspace, workspace.case
    pupils = [item[0] for item in w.pupils]
    partitions = {
        kind: await preview_and_save(
            case, f"/api/v1/promotion-groups/{w.promotion_id}", pupils, kind
        )
        for kind in ("halves", "thirds", "kholles")
    }
    first_group = partitions["halves"]["groups"][0]
    member_id = first_group["student_ids"][0]
    other_id = next(
        identifier for identifier in pupils if identifier not in first_group["student_ids"]
    )
    blocks = [
        w.block(title="Shared"),
        w.block(key="b" * 32, title="Half A", target_kind="halves", target_number=1),
        w.block(key="c" * 32, title="Half B", target_kind="halves", target_number=2),
    ]
    await w.version(w.settings["start"], blocks)
    state = await w.board()
    response = await case.client.post(
        f"/api/v1/timetable/years/{w.year_id}/series",
        json={
            "expected_revision": state["years"][0]["revision"],
            "block": {
                **{
                    key: value
                    for key, value in w.block().items()
                    if key not in {"key", "weekday", "phase"}
                },
                "starts_on": w.settings["start"],
                "title": "Individual",
                "target_kind": "student",
                "target_user_id": member_id,
            },
        },
    )
    assert response.status_code == 201, response.text
    await w.publish()
    state = await w.board()
    assert len(state["groups"]) == sum(len(item["groups"]) for item in partitions.values())
    assert all(item["roles"] == ["user"] for item in state["members"])
    for identifier, expected in (
        (member_id, {"Shared", "Half A", "Individual"}),
        (other_id, {"Shared", "Half B"}),
    ):
        await w.login(next(name for uid, name in w.pupils if uid == identifier))
        token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
        feed = Calendar.from_ical(
            (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
        )
        assert {str(event["SUMMARY"]) for event in feed.walk("VEVENT")} == expected
        assert (
            await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")
        ).status_code == 403
        assert (await case.client.get("/api/v1/timetable/configuration")).status_code == 403
    state = await w.board()
    for target in (
        {"target_kind": "student", "target_user_id": w.teachers[0][0]},
        {"target_kind": "kholles", "target_number": 999},
    ):
        response = await case.client.put(
            f"/api/v1/timetable/years/{w.year_id}/template",
            json={
                "expected_revision": state["years"][0]["revision"],
                "effective_on": date.today().isoformat(),
                "blocks": [w.block(**target)],
            },
        )
        assert response.status_code == 422, response.text
    await w.login(w.teachers[0][1])
    assert (
        await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")
    ).status_code == 403
    assert (
        await case.client.request(
            "DELETE", f"/api/v1/timetable/rooms/{w.room_id}", json={"expected_revision": "a" * 32}
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_retroactive_versions_require_confirmation_and_retain_publication(
    workspace: Workspace,
) -> None:
    """Allow confirmed historical replacement while preserving publication and staff boundaries."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    initial = await w.board()
    await w.version(
        (date.today() + timedelta(days=14)).isoformat(), [w.block(teacher_id=w.teachers[1][0])]
    )
    before = await w.board()
    cutoff = date.fromisoformat(w.settings["start"]) + timedelta(days=7)
    payload = {
        "expected_revision": before["years"][0]["revision"],
        "effective_on": cutoff.isoformat(),
        "blocks": [w.block(teacher_id=w.teachers[1][0], title="Retroactive")],
    }
    path = f"/api/v1/timetable/years/{w.year_id}/template"
    response = await case.client.put(path, json=payload)
    assert response.status_code == 422 and "Confirmez" in response.text
    assert await w.board() == before
    await w.login(w.pupils[0][1])
    assert (
        await case.client.put(path, json={**payload, "acknowledge_history": True})
    ).status_code == 403
    case.as_admin()
    response = await case.client.put(path, json={**payload, "acknowledge_history": True})
    assert response.status_code == 200, response.text
    assert response.json()["number"] == 3
    after = await w.board()
    historical = {
        event["id"] for event in initial["events"] if event["source_date"] < cutoff.isoformat()
    }
    assert historical == {
        event["id"] for event in after["events"] if event["source_date"] < cutoff.isoformat()
    }
    assert all(
        event["teacher_id"] == w.teachers[1][0] and event["title"] == "Retroactive"
        for event in after["events"]
        if event["source_date"] >= cutoff.isoformat()
    )
    async with case.database.sessions() as session:
        year = await session.get(TimetableYear, w.year_id)
        assert year.published_revision == initial["years"][0]["published_revision"]
        assert all(series["teacher_id"] == w.teachers[0][0] for series in year.published["series"])
        versions = list(
            await session.scalars(
                select(TimetableTemplateVersion)
                .where(TimetableTemplateVersion.year_id == w.year_id)
                .order_by(TimetableTemplateVersion.number)
            )
        )
        assert [version.number for version in versions] == [1, 2, 3]
        assert versions[1].effective_on > versions[2].effective_on
    await w.publish()
    async with case.database.sessions() as session:
        year = await session.get(TimetableYear, w.year_id)
        assert year.published_revision == year.revision
        assert any(series["title"] == "Retroactive" for series in year.published["series"])


@pytest.mark.asyncio
async def test_teacher_catalog_reports_current_subject_assignments(workspace: Workspace) -> None:
    """Expose active subject IDs with the administrator's already-authorized staff labels."""
    w, case = workspace, workspace.case
    path = f"/api/v1/admin/users/{w.teachers[0][0]}/profile"
    profile = (await case.client.get(path)).json()
    response = await case.client.patch(
        path, json={"expected_version": profile["profile_version"], "subject_ids": [w.subject_id]}
    )
    assert response.status_code == 200, response.text
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    teachers = {teacher["id"]: teacher for teacher in catalog["teachers"]}
    assert teachers[w.teachers[0][0]]["subject_ids"] == [w.subject_id]
    assert teachers[w.teachers[1][0]]["subject_ids"] == []
    await w.login(w.teachers[0][1])
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    assert catalog["teachers"] == []


@pytest.mark.asyncio
async def test_generic_groups_can_be_prepared_before_promotion_assignment(
    workspace: Workspace,
) -> None:
    """Save generic halves before assignment, then resolve recipients through the live promotion."""
    w, case = workspace, workspace.case
    catalog = (await case.client.get("/api/v1/timetable/catalog")).json()
    calendar = next(item for item in catalog["calendars"] if item["id"] == w.calendar_id)
    response = await case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "expected_revision": calendar["revision"],
            "name": calendar["name"],
            "promotion_id": None,
        },
    )
    assert response.status_code == 200, response.text
    saved = await w.version(w.settings["start"], [w.block(target_kind="halves", target_number=1)])
    state = await w.board()
    assert state["issues"][0]["severity"] == "critical"
    assert state["calendars"][0]["promotion_id"] is None
    assert state["years"][0]["template_blocks"][0]["target_kind"] == "halves"
    assert (
        await case.client.post(
            f"/api/v1/timetable/years/{w.year_id}/publish",
            json={"expected_revision": saved["revision"]},
        )
    ).status_code == 422
    response = await case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "expected_revision": response.json()["revision"],
            "name": calendar["name"],
            "promotion_id": w.promotion_id,
        },
    )
    assert response.status_code == 200, response.text
    partition = await preview_and_save(
        case, f"/api/v1/promotion-groups/{w.promotion_id}", [uid for uid, _ in w.pupils], "halves"
    )
    await w.publish()
    first = partition["groups"][0]
    for identifier, username in w.pupils:
        await w.login(username)
        token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
        feed = Calendar.from_ical(
            (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
        )
        assert bool(feed.walk("VEVENT")) == (identifier in first["student_ids"])


@pytest.mark.asyncio
async def test_archived_teacher_keeps_history_and_warns_until_replaced(
    workspace: Workspace,
) -> None:
    """Keep archived names in published events and permit replacing only future assignments."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    await w.login(w.teachers[0][1])
    teacher_token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    await w.login(w.pupils[0][1])
    token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    original_feed = (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
    state = await w.board()
    teacher_name = state["events"][0]["teacher"]
    response = await case.client.patch(
        f"/api/v1/admin/users/{w.teachers[0][0]}/archive", json={"archived": True}
    )
    assert response.status_code == 204, response.text
    state = await w.board()
    assert all(event["teacher"] == teacher_name for event in state["events"])
    assert any(issue["code"] == f"teacher-{w.teachers[0][0]}" for issue in state["issues"])
    assert (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content == original_feed
    assert (await case.client.get(f"/api/v1/timetable/feed/{teacher_token}.ics")).status_code == 404
    await w.publish()
    response = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/template",
        json={
            "expected_revision": state["years"][0]["revision"],
            "blocks": [w.block(key="b" * 32)],
        },
    )
    assert response.status_code == 422, response.text
    started = datetime.now(UTC)
    response = await case.client.put(
        f"/api/v1/timetable/years/{w.year_id}/template",
        json={
            "expected_revision": state["years"][0]["revision"],
            "blocks": [w.block(teacher_id=w.teachers[1][0])],
        },
    )
    assert response.status_code == 200, response.text
    activated = datetime.fromisoformat(response.json()["effective_at"])
    assert started <= activated <= datetime.now(UTC)
    state = await w.board()
    assert not any(issue["code"] == f"teacher-{w.teachers[0][0]}" for issue in state["issues"])
    assert all(
        event["teacher"] == teacher_name
        for event in state["events"]
        if datetime.fromisoformat(event["end"]) <= activated
    )
    async with case.database.sessions() as session:
        version = await session.scalar(
            select(TimetableTemplateVersion).where(
                TimetableTemplateVersion.year_id == w.year_id, TimetableTemplateVersion.number == 2
            )
        )
        assert version.effective_at == activated


@pytest.mark.asyncio
async def test_feed_batches_publications_and_groups_for_multiple_agendas(
    workspace: Workspace,
) -> None:
    """Keep SQL reads constant when one subscription combines many authorized calendars."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    await w.login(w.pupils[0][1])
    token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
    statements: list[str] = []

    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Count actual SQL SELECTs without recording credentials or statement parameters."""
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = case.app.state.database.engine.sync_engine
    extra_calendars = []
    try:
        sqlalchemy_event.listen(engine, "before_cursor_execute", capture)
        response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        baseline = len(statements)
        initial = len(Calendar.from_ical(response.content).walk("VEVENT"))
        case.as_admin()
        for index in range(6):
            response = await case.client.post(
                "/api/v1/timetable/calendars",
                json={"name": f"Extra {index}", "promotion_id": w.promotion_id},
            )
            assert response.status_code == 201, response.text
            identifier = response.json()["id"]
            extra_calendars.append(identifier)
            response = await case.client.post(
                f"/api/v1/timetable/calendars/{identifier}/years", json={"settings": w.settings}
            )
            assert response.status_code == 201, response.text
            year = response.json()
            fields = {
                key: value
                for key, value in w.block().items()
                if key not in {"key", "weekday", "phase"}
            }
            response = await case.client.post(
                f"/api/v1/timetable/years/{year['id']}/series",
                json={
                    "expected_revision": year["revision"],
                    "block": {**fields, "starts_on": w.settings["start"]},
                },
            )
            assert response.status_code == 201, response.text
            response = await case.client.post(
                f"/api/v1/timetable/years/{year['id']}/publish",
                json={"expected_revision": response.json()["revision"]},
            )
            assert response.status_code == 200, response.text
        statements.clear()
        sqlalchemy_event.listen(engine, "before_cursor_execute", capture)
        response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        assert len(Calendar.from_ical(response.content).walk("VEVENT")) == initial * 7
        assert len(statements) == baseline <= 10
        assert (
            len(
                [
                    statement
                    for statement in statements
                    if "FROM sophikron.timetable_years" in statement
                ]
            )
            == 1
        )
    finally:
        if sqlalchemy_event.contains(engine, "before_cursor_execute", capture):
            sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.id.in_(extra_calendars))
            )


@pytest.mark.asyncio
async def test_workspace_common_settings_room_catalogue_and_calendar_removal(
    workspace: Workspace,
) -> None:
    """Share draft settings, protect publication snapshots and retain retired room references."""
    w, case = workspace, workspace.case
    await w.version(w.settings["start"], [w.block()])
    await w.publish()
    second = (
        await case.client.post(
            "/api/v1/timetable/calendars",
            json={"name": "Deuxième agenda", "promotion_id": w.promotion_id},
        )
    ).json()
    try:
        assert (
            await case.client.post(
                f"/api/v1/timetable/calendars/{second['id']}/years", json={"settings": w.settings}
            )
        ).status_code == 201
        configuration = (await case.client.get("/api/v1/timetable/configuration")).json()
        shared = next(
            item
            for item in configuration["years"]
            if item["school_year"] == date.fromisoformat(w.settings["start"]).year
        )
        response = await case.client.put(
            "/api/v1/timetable/configuration",
            json={
                "expected_revision": shared["revision"],
                "settings": {**w.settings, "day_end": 64800},
            },
        )
        assert response.status_code == 200, response.text
        async with case.database.sessions() as session:
            years = list(
                await session.scalars(
                    select(TimetableYear).where(
                        TimetableYear.calendar_id.in_([w.calendar_id, second["id"]])
                    )
                )
            )
            assert {item.settings["day_end"] for item in years} == {64800}
            assert (
                next(item for item in years if item.calendar_id == w.calendar_id).published[
                    "settings"
                ]["day_end"]
                == 61200
            )
        room = next(item for item in configuration["rooms"] if item["id"] == w.room_id)
        renamed = await case.client.put(
            f"/api/v1/timetable/rooms/{w.room_id}",
            json={"name": "B402 " + case.prefix, "expected_revision": room["revision"]},
        )
        assert renamed.status_code == 200, renamed.text
        removed = await case.client.request(
            "DELETE",
            f"/api/v1/timetable/rooms/{w.room_id}",
            json={"expected_revision": renamed.json()["revision"]},
        )
        assert removed.status_code == 200, removed.text
        assert not any(
            item["id"] == w.room_id
            for item in (await case.client.get("/api/v1/timetable/catalog")).json()["rooms"]
        )
        assert any(item["room"].startswith("B402") for item in (await w.board())["events"])
        agenda = next(
            item
            for item in (await case.client.get("/api/v1/timetable/catalog")).json()["calendars"]
            if item["id"] == w.calendar_id
        )
        response = await case.client.request(
            "DELETE",
            f"/api/v1/timetable/calendars/{w.calendar_id}",
            json={"expected_revision": agenda["revision"]},
        )
        assert response.status_code == 200, response.text
        assert (
            await case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
        ).status_code == 404
        assert (
            await case.client.get(f"/api/v1/timetable/years/{w.year_id}/template")
        ).status_code == 404
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.id == second["id"])
            )
