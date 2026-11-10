"""Shared synthetic fixtures and helpers; never collected as tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date

import pytest_asyncio
from sqlalchemy import delete

from app.models.lessons import Lesson
from app.models.site import Subject, TeacherSubject
from tests.support.administration import clear_promotions
from tests.support.authentication import PASSWORD, Harness


@dataclass
class CourseHarness:
    """Own only synthetic course records and principals for one isolated integration test."""

    case: Harness
    owner_id: int
    owner: str
    collaborator_id: int
    collaborator: str
    student_id: int
    student: str
    state: dict
    course_ids: list[int] = field(default_factory=list)
    promotion_ids: list[int] = field(default_factory=list)

    @property
    def path(self) -> str:
        """Return this fixture's course URL."""
        return f"/api/v1/lessons/{self.state['id']}"

    async def login(self, username: str) -> None:
        """Switch principals through the real session API."""
        response = await self.case.client.post(
            "/api/v1/auth/login",
            json={"identifier": username, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text

    async def mutation(self, suffix: str, data: dict, method: str = "post") -> dict:
        """Save one revision and keep the returned state for the next authorized mutation."""
        response = await self.case.client.request(
            method,
            self.path + suffix,
            json={"expected_version": self.state["version"], **data},
        )
        assert response.status_code in {200, 201}, response.text
        self.state = response.json()
        return self.state

    async def promotion(self, *, assign: bool = True) -> int:
        """Create an active current-year promotion and optionally assign the fixture student."""
        self.case.as_admin()
        today = date.fromisoformat(self.state["today"])
        year = today.year if today.month >= 9 else today.year - 1
        response = await self.case.client.post(
            "/api/v1/admin/promotions",
            json={
                "year": year,
                "identifier": f"COURSE-{self.case.prefix}-{len(self.promotion_ids)}",
                "color": "#123ABC",
            },
        )
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        self.promotion_ids.append(identifier)
        if assign:
            assert (
                await self.case.client.put(
                    f"/api/v1/admin/users/{self.student_id}/promotions/{identifier}",
                )
            ).status_code == 204
        await self.login(self.owner)
        await self.mutation(f"/promotions/{identifier}", {}, "put")
        return identifier


@pytest_asyncio.fixture
async def course(auth_case: Harness) -> AsyncIterator[CourseHarness]:
    """Create a course with independent owner, collaborator and student accounts."""
    owner_id, owner = await auth_case.create("teacher")
    collaborator_id, collaborator = await auth_case.create("teacher")
    student_id, student = await auth_case.create("user")
    async with auth_case.database.sessions.begin() as session:
        subject = Subject(
            name=f"Maths {auth_case.prefix}",
            name_key=auth_case.prefix,
            icon="book",
            color="#41754E",
        )
        session.add(subject)
        await session.flush()
        subject_id = subject.id
        session.add_all(
            [
                TeacherSubject(user_id=identifier, subject_id=subject_id)
                for identifier in (owner_id, collaborator_id)
            ]
        )
    await auth_case.client.post(
        "/api/v1/auth/login",
        json={"identifier": owner, "password": PASSWORD},
    )
    response = await auth_case.client.post(
        "/api/v1/lessons",
        json={
            "title": f"Cours {auth_case.prefix}",
            "description": "Programme annuel",
            "subject_id": subject_id,
        },
    )
    assert response.status_code == 201, response.text
    fixture = CourseHarness(
        auth_case,
        owner_id,
        owner,
        collaborator_id,
        collaborator,
        student_id,
        student,
        response.json(),
    )
    fixture.course_ids.append(fixture.state["id"])
    try:
        yield fixture
    finally:
        async with auth_case.database.sessions.begin() as session:
            await session.execute(delete(Lesson).where(Lesson.id.in_(fixture.course_ids)))
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))
        if fixture.promotion_ids:
            await clear_promotions(fixture.promotion_ids)
