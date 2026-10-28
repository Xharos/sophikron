"""Real publication isolation, recurrence edits and member subscription boundaries."""

import os
from datetime import date, timedelta

import pytest
from icalendar import Calendar
from sqlalchemy import delete, select

from app.models import (
    Subject,
    TimetableCalendar,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableSubscription,
    TimetableYear,
)
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_timetable_publication_subscriptions_and_scope(auth_case: Harness) -> None:
    """Keep drafts private, rotate links and deny student web access and unrelated staff reads."""
    case = auth_case
    promotion_id = await make_promotion(case, "TIMETABLE")
    calendar_id = room_id = subject_id = None
    school_year = date.today().year
    try:
        teacher_id, teacher_name = await case.create("teacher")
        pupil_id, pupil_name = await case.create()
        kholleur_id, kholleur_name = await case.create("kholleur")
        outsider_id, outsider_name = await case.create("teacher")
        case.as_admin()
        response = await case.client.post(
            f"/api/v1/admin/promotions/{promotion_id}/users",
            json={"user_ids": [teacher_id, pupil_id, kholleur_id]},
        )
        assert response.status_code == 204, response.text
        async with case.database.sessions.begin() as session:
            subject = Subject(
                name="Timetable maths",
                name_key=case.prefix,
                icon="book",
                color="#244BC1",
                is_active=True,
            )
            session.add(subject)
            await session.flush()
            subject_id = subject.id
        response = await case.client.post("/api/v1/timetable/rooms", json={"name": case.prefix})
        assert response.status_code == 201, response.text
        room_id = response.json()["id"]
        response = await case.client.post(
            "/api/v1/timetable/calendars",
            json={"name": "Première année", "promotion_id": promotion_id},
        )
        assert response.status_code == 201, response.text
        calendar_id = response.json()["id"]
        today = date.today()
        school_year = today.year - (today.month < 9)
        first = date(school_year, 9, 1)
        first += timedelta(days=(-first.weekday()) % 7)
        settings = {
            "start": f"{school_year}-09-01",
            "end": f"{school_year + 1}-06-30",
            "breaks": [{"start": 35400, "end": 36600}, {"start": 43200, "end": 46800}],
        }
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{calendar_id}/years", json={"settings": settings}
        )
        assert response.status_code == 201, response.text
        year_id, revision = response.json()["id"], response.json()["revision"]
        block = {
            "starts_on": first.isoformat(),
            "start_slot": 0,
            "duration_slots": 8,
            "subject_id": subject_id,
            "teacher_id": teacher_id,
            "room_id": room_id,
            "title": "Published lesson",
            "interval": 1,
            "until": settings["end"],
        }
        response = await case.client.post(
            f"/api/v1/timetable/years/{year_id}/series",
            json={"expected_revision": revision, "block": block},
        )
        assert response.status_code == 201, response.text
        revision = response.json()["revision"]
        response = await case.client.post(
            f"/api/v1/timetable/years/{year_id}/publish", json={"expected_revision": revision}
        )
        assert response.status_code == 200, response.text
        assert (
            await case.client.post(
                f"/api/v1/timetable/years/{year_id}/publish", json={"expected_revision": "0" * 32}
            )
        ).status_code == 409
        draft_query = {"calendar_ids": calendar_id, "school_year": school_year, "draft": "true"}
        response = await case.client.get("/api/v1/timetable/board", params=draft_query)
        assert response.status_code == 200, response.text
        initial = response.json()
        series_id = initial["years"][0]["series"][0]["id"]
        assert len(initial["events"]) > 10
        assert [item["start"][11:19] for item in initial["events"][:2]] == ["08:00:00", "10:10:00"]
        response = await case.client.put(
            f"/api/v1/timetable/years/{year_id}/series/{series_id}",
            json={
                "expected_revision": revision,
                "occurrence": first.isoformat(),
                "scope": "one",
                "block": {**block, "title": "PRIVATE DRAFT"},
            },
        )
        assert response.status_code == 200, response.text
        revision = response.json()["revision"]
        response = await case.client.get(
            "/api/v1/timetable/board",
            params={"calendar_ids": calendar_id, "school_year": school_year},
        )
        assert "PRIVATE DRAFT" not in response.text

        async def login(username: str) -> None:
            """Switch the actual HTTP session to the requested synthetic member."""
            case.client.cookies.clear()
            response = await case.client.post(
                "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
            )
            assert response.status_code == 200, response.text

        await login(pupil_name)
        for endpoint in ("catalog", f"board?calendar_ids={calendar_id}"):
            assert (await case.client.get(f"/api/v1/timetable/{endpoint}")).status_code == 403
        assert (
            await case.client.post("/api/v1/timetable/rooms", json={"name": "Forbidden"})
        ).status_code == 403
        assert (
            await case.client.post(
                "/api/v1/timetable/subscription", headers={"Origin": "https://evil.example"}
            )
        ).status_code == 403
        token = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
        assert (await case.client.get("/api/v1/timetable/subscription")).json() == {"exists": True}
        response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
        assert response.status_code == 200
        assert "PRIVATE DRAFT" not in response.text
        in_term = (
            date.fromisoformat(settings["start"]) <= today <= date.fromisoformat(settings["end"])
        )
        feed = Calendar.from_ical(response.content)
        assert bool(feed.walk("VEVENT")) == in_term
        async with case.database.sessions() as session:
            stored = await session.get(TimetableSubscription, pupil_id)
            assert token.encode() != stored.token_hash and len(stored.token_hash) == 32
        replacement = (await case.client.post("/api/v1/timetable/subscription")).json()["token"]
        assert replacement != token
        assert (await case.client.get(f"/api/v1/timetable/feed/{token}.ics")).status_code == 404
        assert (
            await case.client.get(f"/api/v1/timetable/feed/{replacement}.ics")
        ).status_code == 200

        await login(teacher_name)
        response = await case.client.get(
            "/api/v1/timetable/board", params={"calendar_ids": calendar_id}
        )
        assert response.status_code == 200, response.text
        assert "PRIVATE DRAFT" not in response.text
        assert (
            await case.client.get("/api/v1/timetable/board", params=draft_query)
        ).status_code == 403
        assert (
            await case.client.post(
                f"/api/v1/timetable/years/{year_id}/publish", json={"expected_revision": revision}
            )
        ).status_code == 403
        await login(kholleur_name)
        assert (await case.client.get("/api/v1/timetable/catalog")).status_code == 200
        assert (await case.client.post("/api/v1/timetable/subscription")).status_code == 200
        await login(outsider_name)
        assert (
            await case.client.get("/api/v1/timetable/board", params={"calendar_ids": calendar_id})
        ).status_code == 404

        case.as_admin()
        second = first + timedelta(weeks=1)
        response = await case.client.put(
            f"/api/v1/timetable/years/{year_id}/series/{series_id}",
            json={
                "expected_revision": revision,
                "occurrence": second.isoformat(),
                "scope": "future",
                "block": {**block, "starts_on": second.isoformat(), "title": "Future only"},
            },
        )
        assert response.status_code == 200, response.text
        revision = response.json()["revision"]
        response = await case.client.get("/api/v1/timetable/board", params=draft_query)
        state = response.json()
        assert state["events"][0]["title"] == "PRIVATE DRAFT"
        assert state["events"][2]["title"] == "Future only"
        future_id = state["events"][2]["series_id"]
        response = await case.client.put(
            f"/api/v1/timetable/years/{year_id}/series/{future_id}",
            json={
                "expected_revision": revision,
                "occurrence": second.isoformat(),
                "scope": "one",
                "block": None,
            },
        )
        assert response.status_code == 200, response.text
        revision = response.json()["revision"]
        assert (
            await case.client.post(
                f"/api/v1/timetable/years/{year_id}/publish", json={"expected_revision": revision}
            )
        ).status_code == 200
        response = await case.client.get(f"/api/v1/timetable/feed/{replacement}.ics")
        if in_term:
            assert "PRIVATE DRAFT" in response.text
            assert not any(
                str(item.get("UID", "")).endswith(f"-{second.isoformat()}-0@sophikron")
                for item in Calendar.from_ical(response.content).walk("VEVENT")
            )
        assert (
            await case.client.delete(f"/api/v1/admin/users/{pupil_id}/promotions/{promotion_id}")
        ).status_code == 204
        response = await case.client.get(f"/api/v1/timetable/feed/{replacement}.ics")
        assert not Calendar.from_ical(response.content).walk("VEVENT")
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{pupil_id}/archive", json={"archived": True}
            )
        ).status_code == 204
        assert (
            await case.client.get(f"/api/v1/timetable/feed/{replacement}.ics")
        ).status_code == 404
        assert outsider_id not in {member["id"] for member in initial["members"]}
        # Preparing the next year keeps weekdays and series boundaries but drops exceptions.
        next_settings = {
            **settings,
            "start": f"{school_year + 1}-09-01",
            "end": f"{school_year + 2}-06-30",
        }
        response = await case.client.post(
            f"/api/v1/timetable/calendars/{calendar_id}/years", json={"settings": next_settings}
        )
        assert response.status_code == 201, response.text
        assert (
            await case.client.post(
                f"/api/v1/timetable/calendars/{calendar_id}/years", json={"settings": next_settings}
            )
        ).status_code == 409
        response = await case.client.get(
            "/api/v1/timetable/board",
            params={"calendar_ids": calendar_id, "school_year": school_year + 1, "draft": "true"},
        )
        copied = response.json()
        assert len(copied["years"][0]["series"]) == 2
        assert all(not item["exceptions"] for item in copied["years"][0]["series"])
        assert (
            next(item for item in copied["years"][0]["series"] if item["title"] == "Future only")[
                "until"
            ]
            == next_settings["end"]
        )
        assert all(
            date.fromisoformat(item["starts_on"]).weekday() == first.weekday()
            for item in copied["years"][0]["series"]
        )
        assert not copied["warnings"]
        next_year = copied["years"][0]
        response = await case.client.put(
            f"/api/v1/timetable/years/{next_year['id']}/settings",
            json={
                "expected_revision": next_year["revision"],
                "settings": {**next_settings, "start": settings["end"]},
            },
        )
        assert response.status_code == 200, response.text
        response = await case.client.post(
            f"/api/v1/timetable/years/{next_year['id']}/publish",
            json={"expected_revision": response.json()["revision"]},
        )
        assert response.status_code == 422, response.text
    finally:
        async with case.database.sessions.begin() as session:
            if calendar_id:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id == calendar_id)
                )
            if room_id:
                await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room_id))
            if subject_id:
                await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.execute(
                delete(TimetableSchoolYear).where(
                    TimetableSchoolYear.school_year.in_([school_year, school_year + 1]),
                    ~select(TimetableYear.id)
                    .where(TimetableYear.school_year == TimetableSchoolYear.school_year)
                    .exists(),
                )
            )
        await clear_promotions([promotion_id])
