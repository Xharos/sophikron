"""Actual PostgreSQL checks for subject revocation, read-only collaborators and public calendars."""

import asyncio
import json
import os
from datetime import date, timedelta

import httpx2 as httpx
import pytest
from sqlalchemy import delete

from app.models.lessons import LessonCollaborator
from app.models.site import SiteSettings, Subject, TeacherSubject, Timeline, TimelineEvent
from tests.test_auth_postgres import HEADERS, Harness
from tests.test_lessons_postgres import CourseHarness
from tests.test_lessons_postgres import course as course_fixture

course = course_fixture

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_subject_revocation_serializes_against_inflight_course_edit(
    course: CourseHarness,
) -> None:
    """Allow an already serialized edit or deny it, then forbid every subsequent teacher write."""
    case = course.case
    await course.login(course.owner)
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    current = await profile(case, course.owner_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app),
        base_url="https://testserver",
        headers=HEADERS,
        cookies={case.app.state.auth_settings.cookie_name: token},
    ) as writer:
        edited, revoked = await asyncio.gather(
            writer.post(
                course.path + "/elements",
                json={
                    "expected_version": course.state["version"],
                    "kind": "section",
                    "title": "Concurrent",
                },
            ),
            case.client.patch(
                f"/api/v1/admin/users/{course.owner_id}/profile",
                json={
                    "expected_version": current["profile_version"],
                    "subject_ids": [],
                    "acknowledge_course_impact": True,
                },
            ),
        )
        assert edited.status_code in {201, 403}, edited.text
        assert revoked.status_code == 200, revoked.text
        denied = await writer.post(
            course.path + "/elements",
            json={
                "expected_version": course.state["version"],
                "kind": "section",
                "title": "Denied",
            },
        )
        assert denied.status_code == 403, denied.text


@pytest.mark.asyncio
async def test_subject_archive_serializes_against_course_creation(course: CourseHarness) -> None:
    """Never leave a course referencing a subject archived by a concurrent administrator request."""
    case = course.case
    current = await profile(case, course.owner_id)
    response = await case.client.post(
        "/api/v1/admin/subjects", json={"name": f"Race {case.prefix}"}
    )
    assert response.status_code == 201, response.text
    subject_id = response.json()["id"]
    created_id = None
    try:
        response = await case.client.patch(
            f"/api/v1/admin/users/{course.owner_id}/profile",
            json={
                "expected_version": current["profile_version"],
                "subject_ids": [course.state["subject_id"], subject_id],
            },
        )
        assert response.status_code == 200, response.text
        await course.login(course.owner)
        token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
        case.as_admin()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=case.app),
            base_url="https://testserver",
            headers=HEADERS,
            cookies={case.app.state.auth_settings.cookie_name: token},
        ) as writer:
            created, archived = await asyncio.gather(
                writer.post(
                    "/api/v1/lessons",
                    json={
                        "title": f"Concurrent {case.prefix}",
                        "description": "Race",
                        "subject_id": subject_id,
                    },
                ),
                case.client.request(
                    "DELETE", f"/api/v1/admin/subjects/{subject_id}", json={"expected_version": 0}
                ),
            )
        if created.status_code == 201:
            created_id = created.json()["id"]
            assert archived.status_code == 409, archived.text
        else:
            assert created.status_code == 403, created.text
            assert archived.status_code == 204, archived.text
    finally:
        from app.models.lessons import Lesson

        async with case.database.sessions.begin() as session:
            if created_id:
                await session.execute(delete(Lesson).where(Lesson.id == created_id))
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))


async def profile(case: Harness, identifier: int) -> dict:
    """Read the current profile revision through the administrator API."""
    case.as_admin()
    response = await case.client.get(f"/api/v1/admin/users/{identifier}/profile")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_kholleur_reads_hidden_content_only_when_assigned_and_cannot_write(
    course: CourseHarness,
) -> None:
    """Exercise course mutations and private staff boundaries with a reader session."""
    case = course.case
    reader_id, reader = await case.create("kholleur")
    current = await profile(case, reader_id)
    assigned = await case.client.patch(
        f"/api/v1/admin/users/{reader_id}/profile",
        json={
            "expected_version": current["profile_version"],
            "subject_ids": [course.state["subject_id"]],
        },
    )
    assert assigned.status_code == 200, assigned.text
    await course.login(course.owner)
    await course.mutation("/elements", {"kind": "section", "title": "Programme"})
    section = course.state["elements"][0]["id"]
    tomorrow = (date.fromisoformat(course.state["today"]) + timedelta(days=1)).isoformat()
    await course.mutation(
        "/elements",
        {
            "kind": "text",
            "parent_id": section,
            "body": "HIDDEN",
            "schedule_mode": "from",
            "starts_on": tomorrow,
        },
    )
    text = course.state["elements"][-1]["id"]
    await course.login(reader)
    assert (await case.client.get(course.path)).status_code == 403
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{reader_id}", {}, "put")
    await course.login(reader)
    state = (await case.client.get(course.path)).json()
    assert state["staff_view"] and not state["can_edit"] and not state["can_manage_collaborators"]
    assert any(item["body"] == "HIDDEN" for item in state["elements"])
    assert state["promotions"] == []
    payload = {"expected_version": state["version"]}
    for method, suffix, values in (
        ("put", "", {"title": "Forged", "description": "No", "subject_id": state["subject_id"]}),
        ("post", "/elements", {"kind": "section", "title": "No"}),
        ("put", f"/elements/{text}", {"body": "No"}),
        ("delete", f"/elements/{text}", {}),
        ("post", f"/elements/{text}/move", {"direction": "up"}),
        ("put", f"/collaborators/{course.collaborator_id}", {}),
        ("delete", f"/collaborators/{reader_id}", {}),
        ("put", "/promotions/1", {}),
        ("delete", "/promotions/1", {}),
        (
            "put",
            "/responsibility",
            {"responsible_id": course.collaborator_id, "subject_id": state["subject_id"]},
        ),
    ):
        response = await case.client.request(
            method, course.path + suffix, json={**payload, **values}
        )
        assert response.status_code == 403, (suffix, response.text)
    for path in (
        "/api/v1/admin/subjects",
        "/api/v1/admin/summary",
        "/api/v1/admin/events",
        "/api/v1/teaching/users",
        f"/api/v1/teaching/users/{course.student_id}/profile",
        "/api/v1/lessons/subject-options",
    ):
        assert (await case.client.get(path)).status_code == 403, path
    assert (await case.client.get("/api/v1/auth/me/profile")).status_code == 200
    # Roster assignments never grant management or replace explicit collaboration.
    assert (
        await case.client.post(
            "/api/v1/lessons",
            json={
                "title": "Forbidden",
                "description": "Denied",
                "subject_id": course.state["subject_id"],
            },
        )
    ).status_code == 403
    current = await profile(case, reader_id)
    removed = await case.client.patch(
        f"/api/v1/admin/users/{reader_id}/profile",
        json={"expected_version": current["profile_version"], "subject_ids": []},
    )
    assert removed.status_code == 200, removed.text
    await course.login(reader)
    assert (await case.client.get(course.path)).status_code == 200
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{reader_id}", {}, "delete")
    await course.login(reader)
    assert (await case.client.get(course.path)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("activate", [False, True], ids=["pending", "active"])
async def test_subject_and_team_include_pending_assignments_without_archived_accounts(
    auth_case: Harness, activate: bool
) -> None:
    """Keep seeded staff visible before activation without exposing archived assignments."""
    case = auth_case
    response = await case.client.post(
        "/api/v1/admin/subjects", json={"name": f"Seeded staff {case.prefix}"}
    )
    assert response.status_code == 201, response.text
    subject_id = response.json()["id"]
    extra_subject_id = None
    try:
        response = await case.client.post(
            "/api/v1/admin/subjects", json={"name": f"English staff {case.prefix}"}
        )
        assert response.status_code == 201, response.text
        extra_subject_id = response.json()["id"]
        identifiers = []
        for index, roles in enumerate(
            (["teacher"], ["kholleur"], ["teacher", "kholleur"], ["teacher"])
        ):
            identifier, _ = await case.create(roles[0], activate=activate)
            identifiers.append(identifier)
            current = await profile(case, identifier)
            response = await case.client.patch(
                f"/api/v1/admin/users/{identifier}/profile",
                json={
                    "expected_version": current["profile_version"],
                    "roles": roles,
                    "subject_ids": [subject_id] + ([extra_subject_id] if index != 2 else []),
                },
            )
            assert response.status_code == 200, response.text
        response = await case.client.patch(
            f"/api/v1/admin/users/{identifiers[-1]}/archive", json={"archived": True}
        )
        assert response.status_code == 204, response.text
        response = await case.client.get("/api/v1/admin/team")
        assert response.status_code == 200, response.text
        team = response.json()
        group = next(item for item in team["subjects"] if item["id"] == subject_id)
        assert {member["id"] for member in group["members"]} == set(identifiers[:3])
        assert team["member_count"] == 3
        assert team["teacher_count"] == team["kholleur_count"] == 2
        response = await case.client.get("/api/v1/admin/subjects")
        assert response.status_code == 200, response.text
        subject = next(item for item in response.json()["items"] if item["id"] == subject_id)
        assert subject["teacher_count"] == 3
        english = next(item for item in response.json()["items"] if item["id"] == extra_subject_id)
        assert english["teacher_count"] == 2
        english_team = next(item for item in team["subjects"] if item["id"] == extra_subject_id)
        assert {member["id"] for member in english_team["members"]} == set(identifiers[:2])
        for identifier in identifiers[:3]:
            account = await case.client.get(f"/api/v1/admin/users/{identifier}")
            assert account.status_code == 200, account.text
            assert account.json()["status"] == ("active" if activate else "pending_activation")
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(
                    TeacherSubject.subject_id.in_([subject_id, extra_subject_id])
                )
            )
            await session.execute(
                delete(Subject).where(Subject.id.in_([subject_id, extra_subject_id]))
            )


@pytest.mark.asyncio
async def test_teaching_team_groups_sorts_and_counts_distinct_staff(course: CourseHarness) -> None:
    """Count unique people per role across subjects, omitting archived staff."""
    case = course.case
    reader_id, _ = await case.create("kholleur")
    disabled_id, _ = await case.create("teacher")
    extra = []
    try:
        for label in ("SECOND", "EMPTY"):
            result = await case.client.post(
                "/api/v1/admin/subjects",
                json={
                    "name": f"{label} {case.prefix}",
                    "icon": "science",
                    "color": "#ABCDEF",
                },
            )
            assert result.status_code == 201, result.text
            extra.append(result.json()["id"])
        for user_id, last, roles, subjects in (
            (course.owner_id, "Zulu", ["admin", "teacher"], [course.state["subject_id"], extra[0]]),
            (
                course.collaborator_id,
                "Éclair",
                ["teacher", "kholleur"],
                [course.state["subject_id"]],
            ),
            (reader_id, "Alpha", ["kholleur"], [course.state["subject_id"], extra[0]]),
            (disabled_id, "Absent", ["teacher"], [extra[0]]),
        ):
            current = await profile(case, user_id)
            changed = await case.client.patch(
                f"/api/v1/admin/users/{user_id}/profile",
                json={
                    "expected_version": current["profile_version"],
                    "last_name": last,
                    "roles": roles,
                    "subject_ids": subjects,
                },
            )
            assert changed.status_code == 200, changed.text
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{disabled_id}/archive", json={"archived": True}
            )
        ).status_code == 204
        result = await case.client.get("/api/v1/admin/team")
        assert result.status_code == 200, result.text
        team = result.json()
        assert team["member_count"] == 3
        assert team["teacher_count"] == 2 and team["kholleur_count"] == 2
        groups = {subject["id"]: subject for subject in team["subjects"]}
        assert [member["id"] for member in groups[course.state["subject_id"]]["members"]] == [
            course.collaborator_id,
            course.owner_id,
            reader_id,
        ]
        assert set(groups[course.state["subject_id"]]["members"][0]["roles"]) == {
            "teacher",
            "kholleur",
        }
        assert groups[extra[1]]["members"] == []
        assert len(groups[extra[0]]["members"]) == 2
        assert all(
            set(member) == {"id", "first_name", "last_name", "roles"}
            for group in groups.values()
            for member in group["members"]
        )
        # Archiving a free subject also removes kholleur assignments and its team block.
        response = await case.client.request(
            "DELETE", f"/api/v1/admin/subjects/{extra[0]}", json={"expected_version": 0}
        )
        assert response.status_code == 204, response.text
        assert (await profile(case, reader_id))["subject_ids"] == [course.state["subject_id"]]
        remaining = (await case.client.get("/api/v1/admin/team")).json()
        assert extra[0] not in {item["id"] for item in remaining["subjects"]}
        assert remaining["member_count"] == 3
        assert remaining["teacher_count"] == 2 and remaining["kholleur_count"] == 2
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id.in_(extra))
            )
            await session.execute(delete(Subject).where(Subject.id.in_(extra)))


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["subject", "role", "archive"])
async def test_revocation_requires_warning_and_immediately_denies_old_session(
    course: CourseHarness, action: str
) -> None:
    """Retain responsibility while revoking eligibility and affected collaborator grants."""
    case = course.case
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.owner)
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    current = await profile(case, course.owner_id)
    impact = (await case.client.get(f"/api/v1/admin/users/{course.owner_id}/course-impact")).json()
    assert any(item["id"] == course.state["id"] and item["responsible"] for item in impact)
    path = f"/api/v1/admin/users/{course.owner_id}/" + (
        "archive" if action == "archive" else "profile"
    )
    data = (
        {"archived": True}
        if action == "archive"
        else {
            "expected_version": current["profile_version"],
            **({"subject_ids": []} if action == "subject" else {"roles": ["user"]}),
        }
    )
    assert (await case.client.patch(path, json=data)).status_code == 409
    response = await case.client.patch(path, json={**data, "acknowledge_course_impact": True})
    assert response.status_code == (204 if action == "archive" else 200), response.text
    updated = await profile(case, course.owner_id)
    assert updated["subject_ids"] == []
    case.client.cookies.clear()
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, token, domain="testserver.local", path="/"
    )
    denied = await case.client.post(
        course.path + "/elements",
        json={"expected_version": course.state["version"], "kind": "section", "title": "Denied"},
    )
    assert denied.status_code == (401 if action == "archive" else 403), denied.text
    case.as_admin()
    state = (await case.client.get(course.path)).json()
    assert state["responsible"]["id"] == course.owner_id and not state["responsible"]["can_edit"]
    transfer = await case.client.put(
        course.path + "/responsibility",
        json={
            "expected_version": state["version"],
            "responsible_id": course.collaborator_id,
            "subject_id": state["subject_id"],
        },
    )
    assert transfer.status_code == 200, transfer.text
    assert transfer.json()["creator"]["id"] == course.owner_id
    assert transfer.json()["responsible"]["id"] == course.collaborator_id
    await course.login(course.collaborator)
    assert (await case.client.get(course.path)).json()["can_manage_collaborators"]


@pytest.mark.asyncio
async def test_shared_subject_identity_used_archive_guard_and_unused_assignment_cleanup(
    course: CourseHarness,
) -> None:
    """Propagate identity live and refuse archival while a course references the subject."""
    case = course.case
    case.as_admin()
    subject_id = course.state["subject_id"]
    current = (await case.client.get("/api/v1/admin/subjects", params={"q": case.prefix})).json()[
        "items"
    ][0]
    response = await case.client.put(
        f"/api/v1/admin/subjects/{subject_id}",
        json={
            "name": current["name"],
            "icon": "science",
            "color": "#AaBbCc",
            "expected_version": current["version"],
        },
    )
    assert response.status_code == 200, response.text
    state = (await case.client.get(course.path)).json()
    assert state["icon"] == "science" and state["color"] == "#AABBCC"
    response = await case.client.request(
        "DELETE",
        f"/api/v1/admin/subjects/{subject_id}",
        json={"expected_version": response.json()["version"]},
    )
    assert response.status_code == 409
    response = await case.client.post(
        "/api/v1/admin/subjects",
        json={"name": f"Unused {case.prefix}", "icon": "code", "color": "#123456"},
    )
    assert response.status_code == 201, response.text
    unused = response.json()
    try:
        current_profile = await profile(case, course.collaborator_id)
        changed = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={
                "expected_version": current_profile["profile_version"],
                "subject_ids": [subject_id, unused["id"]],
            },
        )
        assert changed.status_code == 200, changed.text
        response = await case.client.request(
            "DELETE",
            f"/api/v1/admin/subjects/{unused['id']}",
            json={"expected_version": unused["version"]},
        )
        assert response.status_code == 204, response.text
        refreshed = await profile(case, course.collaborator_id)
        assert refreshed["subject_ids"] == [subject_id]
        assert refreshed["profile_version"] > changed.json()["profile_version"]
        stale = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={
                "expected_version": changed.json()["profile_version"],
                "subject_ids": [subject_id, unused["id"]],
            },
        )
        assert stale.status_code == 409
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Subject).where(Subject.id == unused["id"]))


@pytest.mark.asyncio
async def test_collaborator_subject_loss_and_transfer_to_another_subject(
    course: CourseHarness,
) -> None:
    """Remove collaboration permanently and validate replacement teacher eligibility."""
    case = course.case
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    current = await profile(case, course.collaborator_id)
    response = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile",
        json={
            "expected_version": current["profile_version"],
            "subject_ids": [],
            "acknowledge_course_impact": True,
        },
    )
    assert response.status_code == 200, response.text
    async with case.database.sessions() as session:
        assert (
            await session.get(LessonCollaborator, (course.state["id"], course.collaborator_id))
            is None
        )
    await course.login(course.collaborator)
    assert not (await case.client.get(course.path)).json()["can_edit"]
    current = await profile(case, course.collaborator_id)
    response = await case.client.post(
        "/api/v1/admin/subjects", json={"name": f"Other {case.prefix}"}
    )
    assert response.status_code == 201, response.text
    other = response.json()
    try:
        state = (await case.client.get(course.path)).json()
        values = {
            "expected_version": state["version"],
            "responsible_id": course.collaborator_id,
            "subject_id": other["id"],
        }
        assert (
            await case.client.put(course.path + "/responsibility", json=values)
        ).status_code == 422
        response = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={"expected_version": current["profile_version"], "subject_ids": [other["id"]]},
        )
        assert response.status_code == 200, response.text
        response = await case.client.put(course.path + "/responsibility", json=values)
        assert response.status_code == 200, response.text
        assert response.json()["subject_id"] == other["id"]
        assert (
            await case.client.put(course.path + "/responsibility", json=values)
        ).status_code == 409
        assert (await case.client.get(course.path)).json()["creator"]["id"] == course.owner_id
        # Return the course to its fixture subject so cleanup retains valid references.
        back = await case.client.put(
            course.path + "/responsibility",
            json={
                "expected_version": response.json()["version"],
                "responsible_id": course.owner_id,
                "subject_id": course.state["subject_id"],
            },
        )
        assert back.status_code == 200, back.text
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == other["id"])
            )
            await session.execute(delete(Subject).where(Subject.id == other["id"]))


@pytest.mark.asyncio
async def test_public_configuration_calendar_shared_events_conflicts_and_deletion(
    auth_case: Harness,
) -> None:
    """Publish only intended content and preserve shared events when one bar is deleted."""
    case = auth_case
    case.as_admin()
    original = (await case.client.get("/api/v1/site")).json()["settings"]
    ids = []
    event_ids = []
    try:
        settings = {
            "name": "Lycée <test>",
            "home_text": "# Bienvenue\n**Bonjour**",
            "text_color": "#123ABC",
            "holiday_color": "#ab12cd",
            "expected_version": original["version"],
        }
        saved = await case.client.put("/api/v1/admin/site", json=settings)
        assert saved.status_code == 200, saved.text
        assert (await case.client.put("/api/v1/admin/site", json=settings)).status_code == 409
        for name in ("Première année", "Deuxième année"):
            result = await case.client.post(
                "/api/v1/admin/timelines",
                json={"name": name, "starts_on": "2026-09-01", "ends_on": "2027-08-31"},
            )
            assert result.status_code == 201, result.text
            ids.append(result.json()["id"])
        event = {
            "name": "Vacances",
            "kind": "holiday",
            "starts_on": "2026-12-20",
            "ends_on": "2027-01-03",
            "timeline_ids": ids,
        }
        saved_event = await case.client.post("/api/v1/admin/timeline-events", json=event)
        assert saved_event.status_code == 201, saved_event.text
        event_id = saved_event.json()["id"]
        event_ids.append(event_id)
        assert saved_event.json()["color"] == "#AB12CD"
        for name, kind, color in (
            ("Printemps", "holiday", "#FFFFFF"),
            ("Oraux", "oral", "#998877"),
        ):
            extra = await case.client.post(
                "/api/v1/admin/timeline-events",
                json={
                    **event,
                    "name": name,
                    "kind": kind,
                    "color": color,
                    "starts_on": "2027-04-01",
                    "ends_on": "2027-04-02",
                },
            )
            assert extra.status_code == 201, extra.text
            event_ids.append(extra.json()["id"])
            assert extra.json()["color"] == ("#AB12CD" if kind == "holiday" else color)
        changed_settings = await case.client.put(
            "/api/v1/admin/site",
            json={
                **settings,
                "holiday_color": "#AABBCC",
                "expected_version": saved.json()["version"],
            },
        )
        assert changed_settings.status_code == 200, changed_settings.text
        invalid_color = await case.client.put(
            "/api/v1/admin/site",
            json={
                **settings,
                "holiday_color": "red",
                "expected_version": changed_settings.json()["version"],
            },
        )
        assert invalid_color.status_code == 422
        unchanged = await case.client.put(
            "/api/v1/admin/site",
            json={
                key: value
                for key, value in changed_settings.json().items()
                if key not in {"version", "holiday_color"}
            }
            | {"expected_version": changed_settings.json()["version"]},
        )
        assert unchanged.status_code == 200 and unchanged.json()["holiday_color"] == "#AABBCC"
        assert unchanged.json()["version"] == changed_settings.json()["version"]
        old_event = await case.client.put(
            f"/api/v1/admin/timeline-events/{event_id}", json={**event, "expected_version": 0}
        )
        assert old_event.status_code == 409
        settings_log = (
            await case.client.get("/api/v1/admin/events", params={"event_type": "site.updated"})
        ).json()["items"][0]
        assert settings_log["data"]["changed_fields"] == ["holiday_color"]
        assert "home_text" not in settings_log["data"]
        calendar_log = (
            await case.client.get("/api/v1/admin/events", params={"event_type": "calendar.saved"})
        ).json()["items"][0]
        assert (
            calendar_log["data"]["name"] == "Oraux"
            and calendar_log["data"]["entry_type"] == "event"
        )
        invalid = await case.client.post(
            "/api/v1/admin/timeline-events", json={**event, "ends_on": "2028-01-03"}
        )
        assert invalid.status_code == 422
        changed = await case.client.put(
            f"/api/v1/admin/timelines/{ids[0]}",
            json={
                "name": "Bad period",
                "starts_on": "2027-02-01",
                "ends_on": "2027-08-31",
                "expected_version": 0,
            },
        )
        assert changed.status_code == 409
        case.client.cookies.clear()
        public = (await case.client.get("/api/v1/site")).json()
        assert (
            public["settings"]["name"] == "Lycée <test>"
            and public["events"][0]["timeline_ids"] == ids
        )
        assert {item["color"] for item in public["events"] if item["kind"] == "holiday"} == {
            "#AABBCC"
        }
        assert (
            next(item for item in public["events"] if item["kind"] == "oral")["color"] == "#998877"
        )
        assert "email" not in str(public) and "permissions" not in str(public)
        assert (await case.client.put("/api/v1/admin/site", json=settings)).status_code == 401
        case.as_admin()
        assert (
            await case.client.request(
                "DELETE", f"/api/v1/admin/timelines/{ids[0]}", json={"expected_version": 0}
            )
        ).status_code == 204
        deletion = (
            await case.client.get("/api/v1/admin/events", params={"event_type": "calendar.deleted"})
        ).json()["items"][0]
        assert deletion["data"]["name"] == "Première année"
        assert deletion["data"]["retained_events"] == 3 and deletion["data"]["deleted_events"] == 0
        public = (await case.client.get("/api/v1/site")).json()
        event_state = next(item for item in public["events"] if item["id"] == event_id)
        assert event_state["timeline_ids"] == ids[1:] and event_state["version"] == 2
        assert (
            await case.client.put(
                f"/api/v1/admin/timeline-events/{event_id}", json={**event, "expected_version": 0}
            )
        ).status_code == 409
        assert (
            await case.client.request(
                "DELETE", f"/api/v1/admin/timelines/{ids[1]}", json={"expected_version": 0}
            )
        ).status_code == 204
        assert not (await case.client.get("/api/v1/site")).json()["events"]
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Timeline).where(Timeline.id.in_(ids)))
            await session.execute(delete(TimelineEvent).where(TimelineEvent.id.in_(event_ids)))
            row = await session.get(SiteSettings, 1)
            for key, value in original.items():
                setattr(row, key, value)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["remove_kholleur", "remove_teacher", "remove_subject"])
async def test_combined_roles_preserve_remaining_course_permissions(
    course: CourseHarness, change: str
) -> None:
    """Preserve grants from retained roles and require acknowledgement only for real losses."""
    case = course.case
    current = await profile(case, course.collaborator_id)
    response = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile",
        json={
            "expected_version": current["profile_version"],
            "roles": ["teacher", "kholleur", "admin"],
        },
    )
    assert response.status_code == 200, response.text
    await course.login(course.collaborator)
    me = (await case.client.get("/api/v1/auth/me")).json()
    assert {"teacher.access", "kholleur.access", "users.manage"} <= set(me["permissions"])
    # Removing admin retains the independent teaching and reader grants.
    current = await profile(case, course.collaborator_id)
    response = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile",
        json={"expected_version": current["profile_version"], "roles": ["teacher", "kholleur"]},
    )
    assert response.status_code == 200, response.text
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    candidates = await case.client.get(course.path + "/teacher-options", params={"q": "Valentin"})
    assert candidates.status_code == 200, candidates.text
    assert all(item["id"] != course.collaborator_id for item in candidates.json())
    current = await profile(case, course.collaborator_id)
    patch = {"expected_version": current["profile_version"]}
    if change == "remove_subject":
        patch["subject_ids"] = []
    else:
        patch["roles"] = ["teacher"] if change == "remove_kholleur" else ["kholleur"]
    response = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile", json=patch
    )
    if change != "remove_kholleur":
        assert response.status_code == 409, response.text
        unchanged = await profile(case, course.collaborator_id)
        assert unchanged["subject_ids"] == current["subject_ids"]
        patch["acknowledge_course_impact"] = True
        response = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile", json=patch
        )
    assert response.status_code == 200, response.text
    assert response.json()["subject_ids"] == (
        current["subject_ids"] if change != "remove_subject" else []
    )
    async with case.database.sessions() as session:
        assert await session.get(LessonCollaborator, (course.state["id"], course.collaborator_id))
    await course.login(course.collaborator)
    state = (await case.client.get(course.path)).json()
    assert state["can_edit"] == (change == "remove_kholleur")
    denied = await case.client.post(
        course.path + "/elements",
        json={"expected_version": state["version"], "kind": "section", "title": "Role check"},
    )
    assert denied.status_code == (201 if change == "remove_kholleur" else 403), denied.text
    if change == "remove_subject":
        current = await profile(case, course.collaborator_id)
        response = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={
                "expected_version": current["profile_version"],
                "subject_ids": [course.state["subject_id"]],
            },
        )
        assert response.status_code == 200, response.text
        await course.login(course.collaborator)
        assert (await case.client.get(course.path)).json()["can_edit"]
    elif change == "remove_teacher":
        current = await profile(case, course.collaborator_id)
        response = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={
                "expected_version": current["profile_version"],
                "roles": ["admin"],
                "acknowledge_course_impact": True,
            },
        )
        assert response.status_code == 200, response.text
        async with case.database.sessions() as session:
            assert (
                await session.get(LessonCollaborator, (course.state["id"], course.collaborator_id))
                is None
            )


@pytest.mark.asyncio
async def test_archiving_combined_staff_revokes_every_assignment_and_session(
    course: CourseHarness,
) -> None:
    """Archive combined roles atomically and never restore removed associations implicitly."""
    case = course.case
    current = await profile(case, course.collaborator_id)
    changed = await case.client.patch(
        f"/api/v1/admin/users/{course.collaborator_id}/profile",
        json={
            "expected_version": current["profile_version"],
            "roles": ["teacher", "kholleur", "admin"],
        },
    )
    assert changed.status_code == 200, changed.text
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.collaborator)
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    case.as_admin()
    path = f"/api/v1/admin/users/{course.collaborator_id}/archive"
    assert (await case.client.patch(path, json={"archived": True})).status_code == 409
    archived = await case.client.patch(
        path, json={"archived": True, "acknowledge_course_impact": True}
    )
    assert archived.status_code == 204, archived.text
    case.client.cookies.clear()
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, token, domain="testserver.local", path="/"
    )
    assert (await case.client.get(course.path)).status_code == 401
    case.as_admin()
    assert (await case.client.patch(path, json={"archived": False})).status_code == 204
    current = await profile(case, course.collaborator_id)
    assert set(current["roles"]) == {"teacher", "kholleur", "admin"}
    assert current["subject_ids"] == []
    async with case.database.sessions() as session:
        assert (
            await session.get(LessonCollaborator, (course.state["id"], course.collaborator_id))
            is None
        )
        assert (
            await session.get(TeacherSubject, (course.collaborator_id, course.state["subject_id"]))
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["role_removed", "account_archived", "subject_archived"])
async def test_automatic_assignment_removals_are_explicit_in_journal(
    course: CourseHarness, reason: str
) -> None:
    """Keep exact subject identity and trusted cause when another action removes an assignment."""
    case = course.case
    current = await profile(case, course.collaborator_id)
    created = await case.client.post(
        "/api/v1/admin/subjects",
        json={"name": f"Audit {case.prefix}", "icon": "science", "color": "#123ABC"},
    )
    assert created.status_code == 201, created.text
    matter = created.json()
    try:
        assigned = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={"expected_version": current["profile_version"], "subject_ids": [matter["id"]]},
        )
        assert assigned.status_code == 200, assigned.text
        if reason == "role_removed":
            result = await case.client.patch(
                f"/api/v1/admin/users/{course.collaborator_id}/profile",
                json={"expected_version": assigned.json()["profile_version"], "roles": ["user"]},
            )
        elif reason == "account_archived":
            result = await case.client.patch(
                f"/api/v1/admin/users/{course.collaborator_id}/archive", json={"archived": True}
            )
        else:
            result = await case.client.request(
                "DELETE",
                f"/api/v1/admin/subjects/{matter['id']}",
                json={"expected_version": matter["version"]},
            )
        assert result.status_code in {200, 204}, result.text
        events = (
            await case.client.get(
                "/api/v1/admin/events",
                params={
                    "event_type": "user.subjects_updated",
                    "subject_user_id": course.collaborator_id,
                },
            )
        ).json()["items"]
        latest = events[0]
        assert latest["schema_version"] == 2
        assert latest["data"] == {
            "added": [],
            "removed": [{key: matter[key] for key in ("id", "name", "icon", "color")}],
            "reason": reason,
        }
        assert (await profile(case, course.collaborator_id))["subject_ids"] == []
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == matter["id"])
            )
            await session.execute(delete(Subject).where(Subject.id == matter["id"]))


@pytest.mark.asyncio
async def test_assignment_journal_chunks_large_unicode_changes_and_keeps_snapshots(
    course: CourseHarness,
) -> None:
    """Respect the actual JSONB size limit and preserve old names across later catalogue edits."""
    case = course.case
    current = await profile(case, course.collaborator_id)
    matters = []
    try:
        for index in range(14):
            created = await case.client.post(
                "/api/v1/admin/subjects",
                json={
                    "name": "語" * 83 + case.prefix + str(index),
                    "icon": "science",
                    "color": "#123ABC",
                },
            )
            assert created.status_code == 201, created.text
            matters.append(created.json())
        identifiers = {matter["id"] for matter in matters}
        changed = await case.client.patch(
            f"/api/v1/admin/users/{course.collaborator_id}/profile",
            json={
                "expected_version": current["profile_version"],
                "subject_ids": sorted(identifiers),
            },
        )
        assert changed.status_code == 200, changed.text
        entries = (
            await case.client.get(
                "/api/v1/admin/events",
                params={
                    "event_type": "user.subjects_updated",
                    "subject_user_id": course.collaborator_id,
                },
            )
        ).json()["items"]
        assert len(entries) > 1
        assert {item["id"] for entry in entries for item in entry["data"]["added"]} == identifiers
        assert {item["id"] for entry in entries for item in entry["data"]["removed"]} == set(
            current["subject_ids"]
        )
        assert all(
            len(json.dumps(entry["data"], ensure_ascii=False).encode()) <= 4096 for entry in entries
        )
        matter = matters[0]
        renamed = await case.client.put(
            f"/api/v1/admin/subjects/{matter['id']}",
            json={
                "name": "Renamed " + case.prefix,
                "icon": "book",
                "color": "#112233",
                "expected_version": matter["version"],
            },
        )
        assert renamed.status_code == 200, renamed.text
        same = (
            await case.client.get(
                "/api/v1/admin/events",
                params={
                    "event_type": "user.subjects_updated",
                    "subject_user_id": course.collaborator_id,
                },
            )
        ).json()["items"]
        assert [item["data"] for item in same] == [item["data"] for item in entries]
        catalogue = (
            await case.client.get(
                "/api/v1/admin/events",
                params={
                    "event_type": "subject.saved",
                    "resource_type": "subject",
                    "resource_id": matter["id"],
                },
            )
        ).json()["items"][0]
        assert catalogue["data"]["action"] == "updated"
        assert catalogue["data"]["previous"]["name"] == matter["name"]
        assert set(catalogue["data"]["changed_fields"]) == {"name", "icon", "color"}
    finally:
        identifiers = [matter["id"] for matter in matters]
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id.in_(identifiers))
            )
            await session.execute(delete(Subject).where(Subject.id.in_(identifiers)))
