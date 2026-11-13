"""Shared synthetic fixtures and helpers; never collected as tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest_asyncio
from sqlalchemy import delete

from app.models import (
    TeacherAvailability,
    TimetableCalendar,
    TimetableSchoolYear,
)
from tests.support.administration import clear_promotions, make_promotion
from tests.support.authentication import PASSWORD, Harness


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
