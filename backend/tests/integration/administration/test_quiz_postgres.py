"""Verify the question bank's persistence and live account boundaries."""

import os
from base64 import b64encode
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import delete, select

from app.models.activity import ActivityEvent
from app.models.curricula import Competency, Curriculum, CurriculumSubject
from app.models.quiz import QuizQuestion
from tests.support.lessons import CourseHarness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_quiz_bank_access_revisions_and_competencies(course: CourseHarness) -> None:
    """Manage a subject as its teacher, preview across subjects, and override as admin."""
    case = course.case
    subject_id = course.state["subject_id"]
    subject_path = f"/api/v1/quiz/subjects/{subject_id}"
    questions_path = subject_path + "/questions"
    _, other_teacher = await case.create("teacher")
    async with case.database.sessions.begin() as session:
        curriculum = Curriculum(title="Référentiel quiz")
        session.add(curriculum)
        await session.flush()
        curriculum_id = curriculum.id
        session.add(CurriculumSubject(curriculum_id=curriculum_id, subject_id=subject_id))
        await session.flush()
        competency = Competency(curriculum_id=curriculum_id, subject_id=subject_id, name="Calculer")
        session.add(competency)
        await session.flush()
        competency_id = competency.id
    with BytesIO() as output:
        Image.effect_noise((256, 256), 100).save(output, format="JPEG")
        image = "data:image/jpeg;base64," + b64encode(output.getvalue()).decode("ascii")
    assert len(image) > 16384
    definition = {
        "title": "Calcul d’une moitié",
        "statement": "L'élève lit **l’énoncé** et la notation <figure>.",
        "image": image,
        "image_alt": "Motif pour le test de dépôt",
        "prompt": r"Calculez $\frac{1}{2}$.",
        "rule": {"kind": "number", "expected": "1/2", "tolerance": "0,01"},
        "competency_ids": [competency_id],
    }
    try:
        await course.login(course.owner)
        invalid = await case.client.post(questions_path, json={**definition, "image_alt": ""})
        assert invalid.status_code == 422
        assert "Décrivez l’image" in invalid.json()["detail"]
        invalid = await case.client.post(
            questions_path, json={**definition, "rule": {**definition["rule"], "expected": "1/0"}}
        )
        assert invalid.status_code == 422
        assert "Valeur attendue" in invalid.json()["detail"]
        response = await case.client.post(questions_path, json=definition)
        assert response.status_code == 201, response.text
        question_id = response.json()["id"]
        question_path = f"{questions_path}/{question_id}"
        edit = await case.client.get(question_path + "?edit=true")
        assert edit.json()["competency_ids"] == [competency_id]
        assert edit.json()["rule"] == definition["rule"]
        assert edit.json()["statement"] == definition["statement"]
        assert edit.json()["image"].startswith("data:image/jpeg;base64,")
        async with case.database.sessions() as session:
            event = await session.scalar(
                select(ActivityEvent).where(
                    ActivityEvent.event_type == "quiz.created",
                    ActivityEvent.resource_id == question_id,
                )
            )
            assert event.actor_user_id == course.owner_id
            assert event.data["title"] == definition["title"]
            assert event.data["subject_name"].startswith("Maths")
            assert set(event.data) == {"title", "subject_name"}
        assert (
            await case.client.put(
                question_path,
                json={
                    **definition,
                    "competency_ids": [2**63 - 1],
                    "version": 0,
                },
            )
        ).status_code == 422

        await course.login(other_teacher)
        assert (await case.client.get(subject_path)).json()["can_edit"] is False
        preview = await case.client.get(question_path)
        assert preview.status_code == 200
        assert "rule" not in preview.json()
        assert (await case.client.get(question_path + "?edit=true")).status_code == 403
        assert (await case.client.post(questions_path, json=definition)).status_code == 403
        assert (
            await case.client.patch(question_path, json={"version": 0, "archived": True})
        ).status_code == 403
        result = await case.client.post(
            question_path + "/preview",
            json={
                "version": 0,
                "answer": "0.49",
            },
        )
        assert result.json() == {"correct": True}

        await course.login(course.student)
        assert (await case.client.get("/api/v1/quiz")).status_code == 403
        assert (await case.client.get(question_path)).status_code == 403

        case.as_admin()
        assert (await case.client.get(subject_path)).json()["can_edit"] is True
        assert (
            await case.client.patch(question_path, json={"version": 0, "archived": True})
        ).status_code == 204
        assert (
            await case.client.put(question_path, json={**definition, "version": 0})
        ).status_code == 409
        catalog = (await case.client.get("/api/v1/quiz")).json()
        stats = next(subject for subject in catalog if subject["id"] == subject_id)
        assert (stats["total"], stats["archived"]) == (1, 1)
        assert (
            await case.client.request("DELETE", question_path, json={"version": 1})
        ).status_code == 204
        assert (await case.client.get(question_path)).status_code == 404
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(QuizQuestion).where(QuizQuestion.subject_id == subject_id))
            await session.execute(delete(Curriculum).where(Curriculum.id == curriculum_id))
