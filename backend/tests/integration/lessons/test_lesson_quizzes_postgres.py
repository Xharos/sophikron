"""Course quiz permissions, frozen cards, and first-passage persistence."""

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from app.models.quiz import QuizQuestion
from tests.support.lessons import CourseHarness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("in_table", [False, True])
async def test_lesson_quiz_first_passage_and_replay(course: CourseHarness, in_table: bool) -> None:
    """Exercise course editing, saved retries, immutable answers and current access checks."""
    client = course.case.client
    subject_id = course.state["subject_id"]
    bank_path = f"/api/v1/quiz/subjects/{subject_id}/questions"
    await course.promotion()
    definition = {
        "title": "Courant",
        "prompt": "Donnez l’unité.",
        "rule": {"kind": "text", "accepted": ["ampère"]},
    }
    try:
        created = await client.post(bank_path, json=definition)
        assert created.status_code == 201, created.text
        card_id = created.json()["id"]
        options = await client.get(course.path + "/quiz-options?q=cour")
        assert options.json() == [{"id": card_id, "title": "Courant"}]
        await course.mutation("/elements", {"kind": "section", "title": "Électricité"})
        section = course.state["elements"][-1]["id"]
        parent = section
        coordinates = {}
        if in_table:
            await course.mutation(
                "/elements", {"kind": "table", "title": "Activités", "parent_id": section}
            )
            parent = next(
                item["id"] for item in course.state["elements"] if item["kind"] == "table"
            )
            coordinates = {"row_index": 0, "column_index": 0}
        await course.mutation(
            "/elements",
            {
                "kind": "quiz",
                "title": "Entraînement",
                "parent_id": parent,
                **coordinates,
                "quiz_question_ids": [card_id],
            },
        )
        block = next(item["id"] for item in course.state["elements"] if item["kind"] == "quiz")
        path = f"{course.path}/quizzes/{block}"

        edited = await client.put(
            bank_path + f"/{card_id}",
            json={
                **definition,
                "rule": {"kind": "text", "accepted": ["volt"]},
                "version": 0,
            },
        )
        assert edited.status_code == 200, edited.text

        await course.login(course.student)
        assert (await client.get(path + "/results")).status_code == 403
        assert (await client.get(course.path + "/quiz-options")).status_code == 403
        assert (await client.post(path + "/start", json={"replay": True})).status_code == 409
        start = await client.post(path + "/start", json={})
        assert start.status_code == 200, start.text
        assert "rule" not in start.json()["card"]
        first = start.json()
        invalid = await client.post(
            path + "/answer", json={"revision": first["revision"], "answer": " "}
        )
        assert invalid.status_code == 422
        wrong = await client.post(
            path + "/answer",
            json={
                "revision": first["revision"],
                "answer": "volt",
            },
        )
        assert wrong.status_code == 200 and wrong.json()["correct"] is False
        stale = await client.post(
            path + "/answer",
            json={
                "revision": first["revision"],
                "answer": "ampere",
            },
        )
        assert stale.status_code == 409
        detail = await client.get(course.path)
        element = next(item for item in detail.json()["elements"] if item["id"] == block)
        assert element["quiz_progress"] == {"completed": 0, "total": 1, "started": True}
        assert element["quiz_questions"] is None
        assert element["parent_id"] == parent
        assert element["row_index"] == (0 if in_table else None)
        await course.login(course.owner)
        await course.mutation(
            f"/elements/{block}", {"title": "Entraînement", "quiz_question_ids": [card_id]}, "put"
        )
        await course.login(course.student)
        resumed = (await client.post(path + "/start", json={})).json()
        assert resumed["card"] == first["card"]
        finish = await client.post(
            path + "/answer",
            json={
                "revision": resumed["revision"],
                "answer": "Ampére",
            },
        )
        assert finish.status_code == 200 and finish.json()["completed"] == 1
        replay = await client.post(path + "/start", json={"replay": True})
        assert replay.status_code == 200, replay.text
        result = await client.post(path + "/replay", json={"index": 0, "answer": "ampère"})
        assert result.json() == {"correct": True}

        await course.login(course.owner)
        report = await client.get(path + "/results")
        assert report.status_code == 200, report.text
        pupil = report.json()["pupils"][0]
        assert pupil["id"] == course.student_id
        assert pupil["status"] == "completed"
        assert pupil["trials"] == pupil["cards"][0]["attempts"] == 2

        yesterday = (date.fromisoformat(course.state["today"]) - timedelta(days=1)).isoformat()
        await course.mutation(
            f"/elements/{block}",
            {
                "title": "Entraînement",
                "schedule_mode": "range",
                "starts_on": yesterday,
                "ends_on": yesterday,
            },
            "put",
        )
        await course.login(course.student)
        assert (await client.post(path + "/start", json={})).status_code == 409
        assert (await client.post(path + "/replay", json={"index": 0})).status_code == 409
        # Like document readers, staff can practice outside the pupil availability period.
        await course.login(course.owner)
        staff_start = await client.post(path + "/start", json={})
        assert staff_start.status_code == 200, staff_start.text
        assert staff_start.json()["completed"] == 0
        staff_answer = await client.post(
            path + "/answer",
            json={"revision": staff_start.json()["revision"], "answer": "volt"},
        )
        assert staff_answer.status_code == 200, staff_answer.text
        assert staff_answer.json()["correct"] is True
        assert (await client.get(path + "/results")).json()["pupils"] == [pupil]
    finally:
        async with course.case.database.sessions.begin() as session:
            await session.execute(delete(QuizQuestion).where(QuizQuestion.subject_id == subject_id))
