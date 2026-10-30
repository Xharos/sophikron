"""Actual PostgreSQL document lifecycle, table metadata, audiences and cascade cleanup."""

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import date, timedelta

import anyio
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models import User
from app.models.lessons import LessonFile, LessonFileDeletion, LessonUpload
from app.models.site import TeacherSubject
from app.services.document_storage import DocumentStorage, cleanup_documents
from tests.test_lessons_postgres import CourseHarness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]
PAYLOAD = b'print("pedagogical fixture, never executed")\n'


@pytest_asyncio.fixture
async def documents(course: CourseHarness) -> AsyncIterator[CourseHarness]:
    """Exercise real parsing, disk IO and database operations throughout the document lifecycle."""
    try:
        yield course
    finally:
        async with course.case.database.sessions.begin() as session:
            await session.execute(
                delete(LessonFile).where(LessonFile.lesson_id.in_(course.course_ids))
            )
            await session.execute(
                delete(LessonUpload).where(LessonUpload.lesson_id.in_(course.course_ids))
            )
        await cleanup_documents(
            course.case.database, DocumentStorage(course.case.app.state.document_settings)
        )


async def reserve(course: CourseHarness, parent: int, **changes: object) -> str:
    """Reserve a named Python document using the real authenticated API."""
    response = await course.case.client.post(
        course.path + "/uploads",
        json={
            "expected_version": course.state["version"],
            "parent_id": parent,
            "title": "Mon nom pédagogique",
            "filename": "original.py",
            "size_bytes": len(PAYLOAD),
            **changes,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["upload_id"]


async def upload(course: CourseHarness, parent: int, **changes: object) -> dict:
    """Run a real binary upload and retain the new course version."""
    key = await reserve(course, parent, **changes)
    response = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=PAYLOAD,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    course.state = response.json()
    return next(
        item
        for item in course.state["elements"]
        if item["kind"] == "file" and item["title"] == changes.get("title", "Mon nom pédagogique")
    )


@pytest.mark.asyncio
async def test_staff_sections_hide_entire_subtrees_but_teachers_and_collaborating_kholleurs_read(
    documents: CourseHarness,
) -> None:
    """Never expose staff titles/content to students, even through an explicit child override."""
    course = documents
    await course.promotion()
    await course.mutation(
        "/elements", {"kind": "section", "title": "PRIVATE-STAFF-TITLE", "audience": "staff"}
    )
    section = course.state["elements"][0]["id"]
    await course.mutation(
        "/elements", {"kind": "subsection", "title": "PRIVATE-SUBSECTION", "parent_id": section}
    )
    subsection = course.state["elements"][1]["id"]
    await course.mutation(
        "/elements",
        {
            "kind": "text",
            "body": "PRIVATE-PEDAGOGICAL-CONTENT",
            "parent_id": subsection,
            "audience": "students",
        },
    )
    await course.login(course.student)
    response = await course.case.client.get(course.path)
    assert response.status_code == 200 and response.json()["elements"] == []
    assert "PRIVATE" not in response.text
    await course.login(course.collaborator)
    assert "PRIVATE-PEDAGOGICAL-CONTENT" in (await course.case.client.get(course.path)).text
    course.case.as_admin()
    kholleur_id, kholleur = await course.case.create("kholleur")
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{kholleur_id}", {}, "put")
    await course.login(kholleur)
    state = (await course.case.client.get(course.path)).json()
    assert state["staff_view"] and not state["can_edit"]
    assert "PRIVATE-PEDAGOGICAL-CONTENT" in str(state)
    assert (
        await course.case.client.post(
            course.path + "/elements",
            json={
                "kind": "section",
                "title": "Denied",
                "expected_version": course.state["version"],
            },
        )
    ).status_code == 403
    await course.login(course.owner)
    await course.mutation(f"/collaborators/{kholleur_id}", {}, "delete")
    await course.login(kholleur)
    assert (await course.case.client.get(course.path)).status_code == 403


@pytest.mark.asyncio
async def test_named_upload_download_dates_and_integrity(documents: CourseHarness) -> None:
    """Preserve separate display/original names and enforce live access, dates and SHA-256."""
    course = documents
    await course.promotion()
    await course.mutation("/elements", {"kind": "section", "title": "Supports"})
    section = course.state["elements"][0]["id"]
    future = (date.fromisoformat(course.state["today"]) + timedelta(days=3)).isoformat()
    resource = await upload(course, section, schedule_mode="from", starts_on=future)
    assert resource["title"] == "Mon nom pédagogique"
    assert resource["file"]["original_name"] == "original.py"
    assert resource["file"]["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    path = course.path + f"/files/{resource['file']['id']}"
    await course.login(course.student)
    assert "Mon nom pédagogique" in (await course.case.client.get(course.path)).text
    preview = (await course.case.client.get(course.path)).json()
    assert (
        next(item for item in preview["elements"] if item["id"] == resource["id"])["available"]
        is False
    )
    assert (await course.case.client.get(path)).status_code == 404
    await course.login(course.collaborator)
    response = await course.case.client.get(path)
    assert response.status_code == 200 and response.content == PAYLOAD
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    await course.login(course.owner)
    await course.mutation(
        f"/elements/{resource['id']}", {"title": "Nom modifié sans nouveau fichier"}, "put"
    )
    await course.login(course.student)
    assert (await course.case.client.get(path)).content == PAYLOAD
    course.case.client.cookies.clear()
    assert (await course.case.client.get(path)).status_code == 401
    await course.login(course.owner)
    async with course.case.database.sessions() as session:
        file = await session.get(LessonFile, resource["file"]["id"])
        storage = DocumentStorage(course.case.app.state.document_settings)
        storage.path(file.storage_key).write_bytes(b"x" * len(PAYLOAD))
    assert (await course.case.client.get(path)).status_code == 503
    course.case.as_admin()
    history = await course.case.client.get(
        "/api/v1/admin/events",
        params={"event_type": "lesson.file_downloaded", "resource_id": course.state["id"]},
    )
    assert history.status_code == 200, history.text
    entries = history.json()["items"]
    assert len(entries) == 2
    assert [item["data"]["document_title"] for item in entries] == [
        "Nom modifié sans nouveau fichier",
        "Mon nom pédagogique",
    ]
    assert all("original.py" not in str(item["data"]) for item in entries)


@pytest.mark.asyncio
async def test_section_visibility_controls_all_descendants_and_clears_dates(
    documents: CourseHarness,
) -> None:
    """Keep private subtrees absent and refuse direct downloads through visibility changes."""
    course = documents
    await course.promotion()
    await course.mutation("/elements", {"kind": "section", "title": "Section"})
    section = course.state["elements"][0]["id"]
    await course.mutation(
        "/elements", {"kind": "subsection", "title": "Nested", "parent_id": section}
    )
    subsection = course.state["elements"][1]["id"]
    future = (date.fromisoformat(course.state["today"]) + timedelta(days=3)).isoformat()
    resource = await upload(course, subsection, schedule_mode="from", starts_on=future)
    path = course.path + f"/files/{resource['file']['id']}"
    await course.mutation(
        f"/elements/{section}", {"title": "Private section", "audience": "staff"}, "put"
    )
    assert all(item["effective_audience"] == "staff" for item in course.state["elements"])
    assert all(item["schedule_mode"] == "inherit" for item in course.state["elements"])
    await course.mutation(
        "/elements",
        {
            "kind": "youtube",
            "title": "Private video",
            "parent_id": subsection,
            "body": "https://youtu.be/abcdefghijk",
            "schedule_mode": "from",
            "starts_on": future,
        },
    )
    assert course.state["elements"][-1]["effective_starts_on"] is None
    invalid = await course.case.client.post(
        course.path + "/elements",
        json={
            "expected_version": course.state["version"],
            "kind": "text",
            "parent_id": subsection,
            "body": "Private",
            "audience": "staff",
        },
    )
    assert invalid.status_code == 422
    await course.login(course.student)
    response = await course.case.client.get(course.path)
    assert response.json()["elements"] == [] and "Private" not in response.text
    assert (await course.case.client.get(path)).status_code == 404
    await course.login(course.owner)
    await course.mutation(f"/elements/{section}", {"title": "Public section"}, "put")
    await course.login(course.student)
    response = await course.case.client.get(course.path)
    assert len(response.json()["elements"]) == 4
    assert (await course.case.client.get(path)).content == PAYLOAD


@pytest.mark.asyncio
async def test_dynamic_table_headers_empty_cells_dates_and_column_deletion(
    documents: CourseHarness,
) -> None:
    """Use free labels and independent cells, shifting surviving coordinates without losing data."""
    course = documents
    await course.promotion()
    await course.mutation("/elements", {"kind": "section", "title": "Travaux"})
    section = course.state["elements"][0]["id"]
    await course.mutation(
        "/elements",
        {
            "kind": "table",
            "parent_id": section,
            "title": "Ressources au choix",
            "table_rows": 2,
            "table_columns": ["Méthode", "Exemple libre", "Annexes"],
        },
    )
    table = next(item for item in course.state["elements"] if item["kind"] == "table")
    resource = await upload(course, table["id"], row_index=0, column_index=1)
    future = (date.fromisoformat(course.state["today"]) + timedelta(days=3)).isoformat()
    await course.mutation(
        "/elements",
        {
            "kind": "text",
            "body": "VISIBLE-TABLE-CELL",
            "parent_id": table["id"],
            "row_index": 1,
            "column_index": 2,
        },
    )
    await course.mutation(
        "/elements",
        {
            "kind": "text",
            "body": "FUTURE-TABLE-CELL",
            "parent_id": table["id"],
            "row_index": 0,
            "column_index": 0,
            "schedule_mode": "from",
            "starts_on": future,
        },
    )
    duplicate = await course.case.client.post(
        course.path + "/elements",
        json={
            "expected_version": course.state["version"],
            "kind": "text",
            "parent_id": table["id"],
            "row_index": 1,
            "column_index": 2,
            "body": "Duplicate",
        },
    )
    assert duplicate.status_code == 409
    await course.login(course.student)
    visible = (await course.case.client.get(course.path)).text
    assert "VISIBLE-TABLE-CELL" in visible and "FUTURE-TABLE-CELL" in visible
    await course.login(course.owner)
    await course.mutation(
        f"/elements/{table['id']}/table",
        {"action": "rename_column", "index": 0, "label": "Mon intitulé"},
    )
    await course.mutation(
        f"/elements/{table['id']}/table", {"action": "add_column", "label": "Autre titre"}
    )
    await course.mutation(f"/elements/{table['id']}/table", {"action": "add_row"})
    await course.mutation(f"/elements/{table['id']}/table", {"action": "remove_column", "index": 1})
    updated = next(item for item in course.state["elements"] if item["id"] == table["id"])
    assert updated["table_columns"] == ["Mon intitulé", "Annexes", "Autre titre"]
    assert updated["table_rows"] == 3
    survivor = next(
        item for item in course.state["elements"] if item["body"] == "VISIBLE-TABLE-CELL"
    )
    assert survivor["column_index"] == 1
    assert not any(item["id"] == resource["id"] for item in course.state["elements"])
    async with course.case.database.sessions() as session:
        assert await session.scalar(select(LessonFileDeletion.storage_key)) is not None
    await cleanup_documents(
        course.case.database, DocumentStorage(course.case.app.state.document_settings)
    )


@pytest.mark.asyncio
async def test_upload_rejections_conflicts_and_subtree_cleanup(
    documents: CourseHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject invalid/stale uploads and retain failed disk deletions for durable retry."""
    course = documents
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    section = course.state["elements"][0]["id"]
    for changes, status in (
        ({"filename": "../x.py"}, 422),
        ({"filename": "x.exe"}, 422),
        ({"size_bytes": 1048577}, 413),
    ):
        response = await course.case.client.post(
            course.path + "/uploads",
            json={
                "parent_id": section,
                "expected_version": course.state["version"],
                "title": "Nom",
                "filename": "code.py",
                "size_bytes": len(PAYLOAD),
                **changes,
            },
        )
        assert response.status_code == status
    key = await reserve(course, section)
    short = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=b"short",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert short.status_code == 422
    key = await reserve(course, section, filename="spoof.png")
    spoof = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=PAYLOAD,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert spoof.status_code == 422

    validate = DocumentStorage.validate

    async def change_while_validating(self: DocumentStorage, key: str, extension: str) -> str:
        """Simulate a real intervening edit while publication holds no course transaction."""
        mime = await validate(self, key, extension)
        await course.mutation("/elements", {"kind": "section", "title": "Concurrent edit"})
        return mime

    monkeypatch.setattr(DocumentStorage, "validate", change_while_validating)
    key = await reserve(course, section)
    conflict = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=PAYLOAD,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert conflict.status_code == 409
    monkeypatch.setattr(DocumentStorage, "validate", validate)

    def unavailable(self: DocumentStorage, key: str) -> None:
        """Simulate a storage failure before publication."""
        raise OSError("Storage unavailable")

    publish = DocumentStorage.publish
    monkeypatch.setattr(DocumentStorage, "publish", unavailable)
    key = await reserve(course, section)
    refused = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=PAYLOAD,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert refused.status_code == 503
    monkeypatch.setattr(DocumentStorage, "publish", publish)
    resource = await upload(course, section)
    storage = DocumentStorage(course.case.app.state.document_settings)
    async with course.case.database.sessions() as session:
        record = await session.get(LessonFile, resource["file"]["id"])
        file_path = storage.path(record.storage_key)
    await course.mutation(f"/elements/{section}", {}, "delete")
    assert file_path.exists()
    with monkeypatch.context() as context:
        context.setattr(
            DocumentStorage,
            "remove",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("busy")),
        )
        await cleanup_documents(course.case.database, storage)
    async with course.case.database.sessions() as session:
        job = await session.get(LessonFileDeletion, record.storage_key)
        assert job is not None and job.attempts == 1
        assert await session.scalar(select(LessonUpload.id)) is None
    await cleanup_documents(course.case.database, storage)
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_replacement_and_whole_course_deletion(documents: CourseHarness) -> None:
    """Use immutable keys on replacement and remove all course files through real SQL cascades."""
    course = documents
    await course.mutation("/elements", {"kind": "section", "title": "Ressources"})
    section = course.state["elements"][0]["id"]
    first = await upload(course, section)
    replaced = await upload(course, section, element_id=first["id"], title="Nouveau nom")
    assert first["id"] == replaced["id"] and first["file"]["id"] != replaced["file"]["id"]
    await course.mutation(f"/collaborators/{course.collaborator_id}", {}, "put")
    await course.login(course.collaborator)
    assert (
        await course.case.client.request(
            "DELETE", course.path, json={"expected_version": course.state["version"]}
        )
    ).status_code == 403
    await course.login(course.owner)
    assert (
        await course.case.client.request(
            "DELETE", course.path, json={"expected_version": course.state["version"]}
        )
    ).status_code == 204
    assert (await course.case.client.get(course.path)).status_code == 404
    async with course.case.database.sessions() as session:
        assert len((await session.scalars(select(LessonFileDeletion.storage_key))).all()) == 2
    storage = DocumentStorage(course.case.app.state.document_settings)
    await cleanup_documents(course.case.database, storage)
    assert not list((storage.settings.root / "objects").iterdir())


@pytest.mark.asyncio
async def test_direct_document_endpoints_enforce_editor_and_reservation_ownership(
    documents: CourseHarness,
) -> None:
    """Deny student writes and stolen upload IDs without consuming the owner's reservation."""
    course = documents
    await course.promotion()
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    section = course.state["elements"][0]["id"]
    resource = await upload(course, section)
    file_path = course.path + f"/files/{resource['file']['id']}"
    key = await reserve(course, section)
    reservation_path = course.path + f"/uploads/{key}"
    await course.login(course.student)
    denied = await course.case.client.post(
        course.path + "/uploads",
        json={
            "expected_version": course.state["version"],
            "parent_id": section,
            "title": "Forbidden",
            "filename": "code.py",
            "size_bytes": len(PAYLOAD),
        },
    )
    assert denied.status_code == 403
    assert (
        await course.case.client.put(
            reservation_path, content=PAYLOAD, headers={"Content-Type": "application/octet-stream"}
        )
    ).status_code == 404
    assert (await course.case.client.delete(reservation_path)).status_code == 204
    async with course.case.database.sessions() as session:
        pending = await session.get(LessonUpload, key)
        assert pending is not None and pending.started_at is None
    await course.login(course.collaborator)
    assert (
        await course.case.client.put(
            reservation_path, content=PAYLOAD, headers={"Content-Type": "application/octet-stream"}
        )
    ).status_code == 404
    await course.login(course.owner)
    assert (
        await course.case.client.put(
            reservation_path,
            content=PAYLOAD,
            headers={"Content-Type": "application/octet-stream", "Origin": "https://evil.example"},
        )
    ).status_code == 403
    assert (
        await course.case.client.put(
            reservation_path, content=PAYLOAD, headers={"Content-Type": "application/octet-stream"}
        )
    ).status_code == 200
    assert (
        await course.case.client.put(
            reservation_path, content=PAYLOAD, headers={"Content-Type": "application/octet-stream"}
        )
    ).status_code == 404
    other = await course.case.client.post(
        "/api/v1/lessons",
        json={
            "title": f"Other {course.case.prefix}",
            "description": "Independent course",
            "subject_id": course.state["subject_id"],
        },
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    course.course_ids.append(other_id)
    assert (
        await course.case.client.get(f"/api/v1/lessons/{other_id}/files/{resource['file']['id']}")
    ).status_code == 404
    await course.login(course.student)
    promotion_id = course.promotion_ids[0]
    course.case.as_admin()
    assert (
        await course.case.client.delete(
            f"/api/v1/admin/users/{course.student_id}/promotions/{promotion_id}"
        )
    ).status_code == 204
    await course.login(course.student)
    assert (await course.case.client.get(file_path)).status_code == 403
    course.case.client.cookies.clear()
    assert (await course.case.client.get(file_path)).status_code == 401
    assert (
        await course.case.client.put(
            reservation_path, content=PAYLOAD, headers={"Content-Type": "application/octet-stream"}
        )
    ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "revocation,status", [("logout", 401), ("subject", 403), ("disabled", 401)]
)
async def test_upload_rechecks_revocation_after_validation(
    documents: CourseHarness,
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
    status: int,
) -> None:
    """Refuse publication after session, subject or account revocation and clean staged bytes."""
    course = documents
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    section = course.state["elements"][0]["id"]
    key = await reserve(course, section)
    validate = DocumentStorage.validate

    async def revoke_while_validating(self: DocumentStorage, key: str, extension: str) -> str:
        """Change live security state after real parsing, outside the upload's SQL transaction."""
        mime = await validate(self, key, extension)
        if revocation == "logout":
            assert (await course.case.client.post("/api/v1/auth/logout")).status_code == 204
        else:
            async with course.case.database.sessions.begin() as session:
                if revocation == "subject":
                    await session.execute(
                        delete(TeacherSubject).where(TeacherSubject.user_id == course.owner_id)
                    )
                else:
                    user = await session.get(User, course.owner_id)
                    user.status = "disabled"
        return mime

    monkeypatch.setattr(DocumentStorage, "validate", revoke_while_validating)
    response = await course.case.client.put(
        course.path + f"/uploads/{key}",
        content=PAYLOAD,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == status, response.text
    storage = DocumentStorage(course.case.app.state.document_settings)
    assert not storage.path(key).exists()
    assert not storage.path(key, temporary=True).exists()
    async with course.case.database.sessions() as session:
        assert await session.get(LessonUpload, key) is None
        assert await session.scalar(select(LessonFile.id)) is None


@pytest.mark.asyncio
async def test_upload_reservations_bound_count_and_concurrent_quota(
    documents: CourseHarness,
) -> None:
    """Bound abandoned uploads and serialize competing quota claims before receiving any bytes."""
    course = documents
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    section = course.state["elements"][0]["id"]
    keys = [await reserve(course, section) for _ in range(4)]
    data = {
        "expected_version": course.state["version"],
        "parent_id": section,
        "title": "Reserved document",
        "filename": "code.py",
        "size_bytes": len(PAYLOAD),
    }
    assert (await course.case.client.post(course.path + "/uploads", json=data)).status_code == 429
    for key in keys:
        assert (await course.case.client.delete(course.path + f"/uploads/{key}")).status_code == 204
    settings = course.case.app.state.document_settings
    course.case.app.state.document_settings = settings.model_copy(
        update={"course_quota_bytes": 50 * 1024 * 1024}
    )
    try:
        results = await asyncio.gather(
            *(
                course.case.client.post(
                    course.path + "/uploads",
                    json={**data, "filename": "archive.zip", "size_bytes": 30 * 1024 * 1024},
                )
                for _ in range(2)
            )
        )
        assert sorted(result.status_code for result in results) == [201, 413]
        async with course.case.database.sessions() as session:
            pending = list((await session.scalars(select(LessonUpload))).all())
            assert len(pending) == 1 and pending[0].size_bytes == 30 * 1024 * 1024
    finally:
        course.case.app.state.document_settings = settings


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_queued_download_rechecks_live_authorization(
    documents: CourseHarness, revoked: bool
) -> None:
    """Queue without a SQL transaction and recheck live rights before opening file bytes."""
    course = documents
    await course.mutation("/elements", {"kind": "section", "title": "Documents"})
    resource = await upload(course, course.state["elements"][0]["id"])
    original_slots = course.case.app.state.document_download_slots
    slots = anyio.Semaphore(1, max_value=1)
    course.case.app.state.document_download_slots = slots
    await slots.acquire()
    held = True
    pending = asyncio.create_task(
        course.case.client.get(course.path + f"/files/{resource['file']['id']}")
    )
    try:
        with anyio.fail_after(10):
            while slots.statistics().tasks_waiting != 1:
                assert not pending.done()
                await anyio.sleep(0.01)
            if revoked:
                # This independent write must not wait on a user lock held by the queued download.
                async with course.case.database.sessions.begin() as session:
                    user = await session.get(User, course.owner_id, with_for_update=True)
                    user.status = "disabled"
            slots.release()
            held = False
            response = await pending
        assert response.status_code == (401 if revoked else 200), response.text
        if not revoked:
            assert response.content == PAYLOAD
        else:
            assert PAYLOAD not in response.content
        assert slots.value == 1
    finally:
        if held:
            slots.release()
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
        course.case.app.state.document_download_slots = original_slots
