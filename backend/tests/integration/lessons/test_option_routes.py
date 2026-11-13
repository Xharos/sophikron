"""Live course option authorization and document-limit contracts."""

import os

import pytest

from app.services.file_validation import FILE_TYPES
from tests.support.lessons import CourseHarness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Disposable PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_course_options_require_live_editor_and_admin_rights(course: CourseHarness) -> None:
    """Expose promotion metadata to editors and responsibility candidates only to admins."""
    promotion = await course.promotion()
    case = course.case
    response = await case.client.get(course.path + "/promotion-options")
    assert response.status_code == 200
    assert promotion in {row["id"] for row in response.json()}
    assert (await case.client.get(course.path + "/promotion-options?limit=0")).status_code == 422
    params = {"subject_id": course.state["subject_id"], "q": "a"}
    assert (
        await case.client.get(course.path + "/responsible-options", params=params)
    ).status_code == 422
    params["q"] = "zz"
    assert (
        await case.client.get(course.path + "/responsible-options", params=params)
    ).status_code == 403
    case.as_admin()
    response = await case.client.get(course.path + "/responsible-options", params=params)
    assert response.status_code == 200 and response.json() == []
    await course.login(course.student)
    assert (await case.client.get(course.path + "/promotion-options")).status_code == 403
    response = await case.client.get("/api/v1/lessons/document-limits")
    assert response.status_code == 200
    assert response.json() == {"types": {key: value[0] for key, value in FILE_TYPES.items()}}
