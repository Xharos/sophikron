"""Actual PostgreSQL course permissions, scheduling, invariants and atomic audit events."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models import ActivityEvent
from app.models.lessons import Lesson, LessonElement
from app.models.site import Subject, TeacherSubject
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1",
        reason="Dedicated PostgreSQL required",
    ),
]


@pytest.mark.asyncio
async def test_existing_lesson_policies_upgrade_preserves_private_content(
    course: "CourseHarness",
) -> None:
    """Amend an installed schema idempotently while retaining file-only dates and course IDs."""
    await course.mutation("/elements", {"kind": "section", "title": "Legacy section"})
    section = course.state["elements"][0]["id"]
    await course.mutation("/elements", {"kind": "text", "parent_id": section, "body": "PRIVATE"})
    child = course.state["elements"][1]["id"]
    database = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    try:
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "ALTER TABLE sophikron.lesson_elements "
                    "DROP CONSTRAINT ck_lesson_elements_section_audience"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE sophikron.lesson_elements "
                    "DROP CONSTRAINT ck_lesson_elements_resource_dates"
                )
            )
            await connection.execute(
                text(
                    "UPDATE sophikron.lesson_elements SET schedule_mode='from', "
                    "starts_on='2099-01-01' WHERE id=:id"
                ),
                {"id": section},
            )
            await connection.execute(
                text("UPDATE sophikron.lesson_elements SET audience='staff' WHERE id=:id"),
                {"id": child},
            )

            def upgrade(sync_connection: Connection) -> None:
                """Apply the amended baseline helper with the migration role."""
                script = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
                with Operations.context(MigrationContext.configure(sync_connection)):
                    script.get_revision("0005_lessons").module.upgrade_lesson_policies()

            await connection.run_sync(upgrade)
            version = await connection.scalar(
                text("SELECT version FROM sophikron.lessons WHERE id=:id"),
                {"id": course.state["id"]},
            )
            await connection.run_sync(upgrade)
            assert (
                await connection.scalar(
                    text("SELECT version FROM sophikron.lessons WHERE id=:id"),
                    {"id": course.state["id"]},
                )
                == version
            )
        response = await course.case.client.get(course.path)
        assert response.status_code == 200
        section_data, child_data = response.json()["elements"]
        assert section_data["audience"] == "staff" and child_data["audience"] == "students"
        assert section_data["schedule_mode"] == "inherit"
        assert child_data["effective_audience"] == "staff"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_admin_teacher_has_teaching_badge_in_course_metadata(course: "CourseHarness") -> None:
    """Prefer the pedagogical teacher role without changing administrator permissions."""
    course.case.as_admin()
    profile = (
        await course.case.client.get(f"/api/v1/admin/users/{course.owner_id}/profile")
    ).json()
    changed = await course.case.client.patch(
        f"/api/v1/admin/users/{course.owner_id}/profile",
        json={"expected_version": profile["profile_version"], "roles": ["admin", "teacher"]},
    )
    assert changed.status_code == 200, changed.text
    state = (await course.case.client.get(course.path)).json()
    assert state["responsible"]["role"] == "teacher"


@pytest.mark.asyncio
async def test_collaborator_options_browse_live_search_and_exclusions(
    course: "CourseHarness",
) -> None:
    """List five eligible staff before typing, excluding every existing course association."""
    case = course.case
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    ineligible_id, _ = await case.create("teacher")
    teacher_id, _ = await case.create("teacher")
    async with case.database.sessions.begin() as session:
        session.add(TeacherSubject(user_id=teacher_id, subject_id=course.state["subject_id"]))
    pending_id, _ = await case.create("kholleur", activate=False)
    readers = [await case.create("kholleur") for _ in range(6)]
    eligible = [teacher_id, *(identifier for identifier, _ in readers)]
    await course.login(course.owner)
    path = course.path + "/teacher-options"
    for params in [{}, {"q": ""}, {"q": "V"}, {"q": "  valentin  "}]:
        response = await case.client.get(path, params=params)
        assert response.status_code == 200, response.text
        assert [person["id"] for person in response.json()] == eligible[:5]
        assert response.json()[0]["role"] == "teacher"
        assert all(person["role"] == "kholleur" for person in response.json()[1:])
        assert {course.owner_id, course.collaborator_id, ineligible_id, pending_id}.isdisjoint(
            person["id"] for person in response.json()
        )
    assert (await case.client.get(path, params={"q": "NoSuchPerson"})).json() == []
    assert (await case.client.get(path, params={"q": "x" * 101})).status_code == 422
    await course.mutation(f"/collaborators/{teacher_id}", {}, "put")
    assert [person["id"] for person in (await case.client.get(path)).json()] == eligible[1:6]
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "delete")
    assert (await case.client.get(path)).json()[0]["id"] == course.collaborator_id
    case.as_admin()
    transferred = await case.client.put(
        course.path + "/responsibility",
        json={
            "expected_version": course.state["version"],
            "responsible_id": course.collaborator_id,
            "subject_id": course.state["subject_id"],
        },
    )
    assert transferred.status_code == 200, transferred.text
    response = await case.client.get(path)
    assert {course.owner_id, course.collaborator_id, teacher_id}.isdisjoint(
        person["id"] for person in response.json()
    )
    for username in [course.owner, course.student, readers[0][1]]:
        await course.login(username)
        assert (await case.client.get(path)).status_code == 403
    case.client.cookies.clear()
    assert (await case.client.get(path)).status_code == 401


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


@pytest.mark.asyncio
async def test_catalogue_page_gates_and_default_school_year(course: CourseHarness) -> None:
    """Keep cards public to members while denying page bodies without active promotion grants."""
    case = course.case
    await course.mutation("/elements", {"kind": "section", "title": "Programme"})
    section = course.state["elements"][0]["id"]
    await course.mutation(
        "/elements", {"kind": "text", "parent_id": section, "body": "PRIVATE-BODY"}
    )
    await course.login(course.student)
    cards = (await case.client.get("/api/v1/lessons")).json()
    card = next(item for item in cards["items"] if item["id"] == course.state["id"])
    assert card["creator"]["role"] == "teacher"
    assert not card["can_open"] and not card["can_edit"]
    assert "PRIVATE-BODY" not in str(cards)
    assert (await case.client.get(course.path)).status_code == 403
    assert (
        await case.client.post(
            "/api/v1/lessons",
            json={
                "title": "Forbidden",
                "description": "No",
                "subject_id": course.state["subject_id"],
            },
        )
    ).status_code == 403
    promotion_id = await course.promotion()
    grant = course.state["promotions"][0]
    assert grant["ends_on"] == f"{grant['year'] + 1}-08-31"
    await course.login(course.student)
    visible = await case.client.get(course.path)
    assert visible.status_code == 200 and "PRIVATE-BODY" in visible.text
    assert visible.json()["promotions"] == [] and visible.json()["warnings"] == []
    assert not visible.json()["can_manage_collaborators"]
    await course.login(course.owner)
    await course.mutation(f"/promotions/{promotion_id}", {}, "delete")
    await course.login(course.student)
    assert (await case.client.get(course.path)).status_code == 403
    case.client.cookies.clear()
    assert (await case.client.get("/api/v1/lessons")).status_code == 401
    assert (await case.client.get(course.path)).status_code == 401


@pytest.mark.asyncio
async def test_structural_dates_ignored_and_media_placeholders(course: CourseHarness) -> None:
    """Retain headings but exclude protected bodies, including overrides of closed ancestors."""
    await course.promotion()
    today = date.fromisoformat(course.state["today"])
    future, past = (today + timedelta(days=5)).isoformat(), (today - timedelta(days=5)).isoformat()
    await course.mutation(
        "/elements",
        {
            "kind": "section",
            "title": "Future section",
            "schedule_mode": "from",
            "starts_on": future,
        },
    )
    section = course.state["elements"][0]["id"]
    await course.mutation(
        "/elements", {"kind": "text", "parent_id": section, "body": "INHERITED-SECRET"}
    )
    await course.mutation(
        "/elements",
        {
            "kind": "subsection",
            "parent_id": section,
            "title": "Open override",
            "schedule_mode": "from",
            "starts_on": past,
        },
    )
    subsection = next(
        item["id"] for item in course.state["elements"] if item["kind"] == "subsection"
    )
    await course.mutation(
        "/elements", {"kind": "text", "parent_id": subsection, "body": "OVERRIDDEN-OPEN"}
    )
    await course.mutation(
        "/elements",
        {
            "kind": "youtube",
            "parent_id": subsection,
            "body": "https://youtu.be/abcdefghijk",
            "schedule_mode": "range",
            "starts_on": past,
            "ends_on": past,
        },
    )
    staff = course.state
    assert len(staff["elements"]) == 5
    assert sum(not item["available"] for item in staff["elements"]) == 1
    await course.login(course.student)
    response = await course.case.client.get(course.path)
    assert response.status_code == 200
    assert "Future section" in response.text and "Open override" in response.text
    assert "OVERRIDDEN-OPEN" in response.text
    assert "INHERITED-SECRET" in response.text and "abcdefghijk" not in response.text
    assert len(response.json()["elements"]) == 5


@pytest.mark.asyncio
async def test_creator_collaborator_and_admin_permissions_follow_current_roles(
    course: CourseHarness,
) -> None:
    """Revoke editing on role loss using existing sessions, including historical creators."""
    case = course.case
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.collaborator)
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    await course.mutation("/elements", {"kind": "section", "title": "Collaborator section"})
    assert not course.state["can_manage_collaborators"]
    assert (
        await case.client.put(
            f"{course.path}/collaborators/{course.owner_id}",
            json={
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 403
    assert (await case.client.get(f"{course.path}/teacher-options?q=Valentin")).status_code == 403
    case.as_admin()
    changed = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile",
        json={
            "expected_version": 0,
            "roles": ["user"],
            "acknowledge_course_impact": True,
        },
    )
    assert changed.status_code == 200, changed.text
    case.client.cookies.clear()
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, token, domain="testserver.local", path="/"
    )
    assert (
        await case.client.post(
            course.path + "/elements",
            json={
                "expected_version": course.state["version"],
                "kind": "section",
                "title": "Forbidden",
            },
        )
    ).status_code == 403
    assert (await case.client.get(course.path)).status_code == 403
    await course.login(course.owner)
    owner_token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    case.as_admin()
    assert (
        await case.client.patch(
            f"/api/v1/admin/users/{course.owner_id}/profile",
            json={
                "expected_version": 0,
                "roles": ["user"],
                "acknowledge_course_impact": True,
            },
        )
    ).status_code == 200
    case.client.cookies.clear()
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, owner_token, domain="testserver.local", path="/"
    )
    assert (
        await case.client.put(
            course.path,
            json={
                "title": "No longer mine",
                "description": "No",
                "subject_id": course.state["subject_id"],
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 403
    case.as_admin()
    admin = (await case.client.get(course.path)).json()
    assert admin["can_edit"] and admin["can_manage_collaborators"]
    assert not admin["creator"]["can_edit"] and not admin["collaborators"]
    assert admin["creator"]["role"] == "user"
    course.state = admin
    await course.mutation("/elements", {"kind": "section", "title": "Admin recovery"})
    assert (
        await case.client.post(
            "/api/v1/lessons",
            json={
                "title": "Admin alone",
                "description": "No teacher role",
                "subject_id": course.state["subject_id"],
            },
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_collaboration_removal_archive_and_unrelated_teachers(course: CourseHarness) -> None:
    """Deny unrelated teachers, revoked collaborators and deactivated sessions immediately."""
    case = course.case
    await course.login(course.collaborator)
    assert (await case.client.get(course.path)).status_code == 200
    assert (
        await case.client.post(
            course.path + "/elements",
            json={
                "kind": "section",
                "title": "No grant",
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 403
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.collaborator)
    assert (await case.client.get(course.path)).json()["can_edit"]
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "delete")
    await course.login(course.collaborator)
    assert not (await case.client.get(course.path)).json()["can_edit"]
    assert (
        await case.client.post(
            course.path + "/elements",
            json={
                "kind": "section",
                "title": "Revoked",
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 403
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    case.as_admin()
    assert (
        await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/archive",
            json={"archived": True},
        )
    ).status_code == 204
    case.client.cookies.clear()
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, token, domain="testserver.local", path="/"
    )
    assert (await case.client.get(course.path)).status_code == 401


@pytest.mark.asyncio
async def test_promotion_archive_membership_and_calendar_boundaries(course: CourseHarness) -> None:
    """Require active membership and inclusive access dates on every request."""
    case = course.case
    promotion_id = await course.promotion()
    today = course.state["today"]
    await course.mutation(
        f"/promotions/{promotion_id}", {"starts_on": today, "ends_on": today}, "put"
    )
    await course.login(course.student)
    assert (await case.client.get(course.path)).status_code == 200
    case.as_admin()
    assert (
        await case.client.patch(
            f"/api/v1/admin/promotions/{promotion_id}",
            json={
                "is_active": False,
            },
        )
    ).status_code == 200
    await course.login(course.student)
    assert (await case.client.get(course.path)).status_code == 403
    await course.login(course.owner)
    assert (
        await case.client.put(
            f"{course.path}/promotions/{promotion_id}",
            json={
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 409
    case.as_admin()
    await case.client.patch(f"/api/v1/admin/promotions/{promotion_id}", json={"is_active": True})
    await case.client.delete(f"/api/v1/admin/users/{course.student_id}/promotions/{promotion_id}")
    await course.login(course.student)
    assert (await case.client.get(course.path)).status_code == 403
    case.as_admin()
    await case.client.put(f"/api/v1/admin/users/{course.student_id}/promotions/{promotion_id}")
    await course.login(course.owner)
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    await course.mutation(
        f"/promotions/{promotion_id}", {"starts_on": yesterday, "ends_on": yesterday}, "put"
    )
    await course.login(course.student)
    assert (await case.client.get(course.path)).status_code == 403


@pytest.mark.asyncio
async def test_atomic_events_validation_stale_versions_and_subtree_deletion(
    course: CourseHarness,
) -> None:
    """Reject forged hierarchy/ownership and stale revisions without successful audit facts."""
    case = course.case
    await course.mutation("/elements", {"kind": "section", "title": "First"})
    section = course.state["elements"][0]["id"]
    old_version = course.state["version"]
    await course.mutation(
        "/elements", {"kind": "text", "parent_id": section, "body": "AUDIT-SECRET"}
    )
    text_id = next(item["id"] for item in course.state["elements"] if item["kind"] == "text")
    assert (
        await case.client.post(
            course.path + "/elements",
            json={
                "expected_version": old_version,
                "kind": "section",
                "title": "Stale",
            },
        )
    ).status_code == 409
    for values in (
        {"kind": "text", "body": "Root"},
        {"kind": "subsection", "parent_id": text_id, "title": "Invalid"},
        {"kind": "youtube", "parent_id": section, "body": "javascript:alert(1)"},
    ):
        assert (
            await case.client.post(
                course.path + "/elements",
                json={
                    "expected_version": course.state["version"],
                    **values,
                },
            )
        ).status_code == 422
    assert (
        await case.client.put(
            course.path,
            json={
                "expected_version": course.state["version"],
                "title": "Forged",
                "description": "No",
                "subject_id": course.state["subject_id"],
                "creator_id": course.student_id,
            },
        )
    ).status_code == 422
    duplicate = await case.client.post(
        "/api/v1/lessons",
        json={
            "title": f"  {course.state['title'].upper()}  ",
            "description": "Duplicate",
            "subject_id": course.state["subject_id"],
        },
    )
    assert duplicate.status_code == 409
    await course.mutation(
        f"/elements/{text_id}",
        {"body": "CHANGED-SECRET", "schedule_mode": "from", "starts_on": course.state["today"]},
        "put",
    )
    await course.mutation("/elements", {"kind": "section", "title": "Second"})
    second = next(item["id"] for item in course.state["elements"] if item["title"] == "Second")
    await course.mutation(f"/elements/{second}/move", {"direction": "up"})
    assert course.state["elements"][0]["id"] == second
    await course.mutation(f"/elements/{section}", {}, "delete")
    assert [item["id"] for item in course.state["elements"]] == [second]
    case.as_admin()
    events = (
        await case.client.get(
            "/api/v1/admin/events",
            params={
                "resource_type": "lesson",
                "resource_id": course.state["id"],
                "limit": 50,
            },
        )
    ).json()["items"]
    assert len(events) == 7
    assert all(item["resource_label"] == course.state["title"] for item in events)
    assert all(
        item["actor_profile_available"] and item["actor_role"] == "teacher" for item in events
    )
    assert "AUDIT-SECRET" not in str(events) and "CHANGED-SECRET" not in str(events)
    removed = next(item for item in events if item["event_type"] == "lesson.element_deleted")
    assert removed["data"]["removed_count"] == 2
    updated = next(item for item in events if item["event_type"] == "lesson.element_updated")
    assert "body" in updated["data"]["changed_fields"]
    async with case.database.sessions.begin() as session:
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    LessonElement(
                        lesson_id=course.state["id"],
                        kind="subsection",
                        parent_id=second + 999999,
                        title="Invalid",
                        body="",
                        position=0,
                        schedule_mode="inherit",
                    )
                )
                await session.flush()
        assert await session.scalar(
            select(ActivityEvent.id).where(
                ActivityEvent.resource_type == "lesson",
                ActivityEvent.resource_id == course.state["id"],
            )
        )


@pytest.mark.asyncio
async def test_cross_course_references_are_rejected(course: CourseHarness) -> None:
    """Never accept another course's element ID even when the actor can edit both pages."""
    case = course.case
    await course.mutation("/elements", {"kind": "section", "title": "Owned by first course"})
    element_id = course.state["elements"][0]["id"]
    response = await case.client.post(
        "/api/v1/lessons",
        json={
            "title": f"Other {case.prefix}",
            "description": "Separate tree",
            "subject_id": course.state["subject_id"],
        },
    )
    assert response.status_code == 201
    other = response.json()
    course.course_ids.append(other["id"])
    path = f"/api/v1/lessons/{other['id']}"
    for method, suffix, values in (
        ("put", f"/elements/{element_id}", {"title": "Forged"}),
        ("delete", f"/elements/{element_id}", {}),
        ("post", f"/elements/{element_id}/move", {"direction": "up"}),
    ):
        assert (
            await case.client.request(
                method,
                path + suffix,
                json={
                    "expected_version": 0,
                    **values,
                },
            )
        ).status_code == 404
    assert (
        await case.client.post(
            path + "/elements",
            json={
                "expected_version": 0,
                "kind": "text",
                "parent_id": element_id,
                "body": "Forged",
            },
        )
    ).status_code == 422
    assert (await case.client.get(path)).json()["version"] == 0
    assert (await case.client.get(course.path)).json()["elements"][0][
        "title"
    ] == "Owned by first course"


@pytest.mark.asyncio
async def test_collaborator_grants_and_detailed_audit_are_atomic(course: CourseHarness) -> None:
    """Allow collaborator promotion management, retain audit references and skip no-op events."""
    case = course.case
    promotion_id = await course.promotion()
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    version = course.state["version"]
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    assert course.state["version"] == version
    await course.login(course.collaborator)
    await course.mutation(
        f"/promotions/{promotion_id}",
        {
            "starts_on": course.state["today"],
            "ends_on": course.state["today"],
        },
        "put",
    )
    await course.mutation(f"/promotions/{promotion_id}", {}, "delete")
    case.as_admin()
    events = (
        await case.client.get(
            "/api/v1/admin/events",
            params={
                "resource_type": "lesson",
                "resource_id": course.state["id"],
                "limit": 50,
            },
        )
    ).json()["items"]
    assert sum(item["event_type"] == "lesson.collaborator_added" for item in events) == 1
    invited = next(item for item in events if item["event_type"] == "lesson.collaborator_added")
    assert invited["subject_user_id"] == course.collaborator_id
    assert invited["subject_role"] == "teacher" and invited["subject_profile_available"]
    updated = next(item for item in events if item["event_type"] == "lesson.promotion_updated")
    assert updated["actor_user_id"] == course.collaborator_id
    assert updated["data"]["promotion_id"] == promotion_id
    assert updated["data"]["previous_period"]["ends_on"].endswith("08-31")
    assert updated["data"]["period"]["ends_on"] == course.state["today"]
