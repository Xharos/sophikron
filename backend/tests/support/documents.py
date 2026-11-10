"""Shared synthetic fixtures and helpers; never collected as tests."""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import delete

from app.models.lessons import LessonFile, LessonUpload
from app.services.document_storage import DocumentStorage, cleanup_documents
from tests.support.lessons import CourseHarness

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
