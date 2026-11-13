"""Real PostgreSQL programme rights, shared nodes, constraints and atomic edits."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models.curricula import CompetencyLink, Curriculum
from tests.support.authentication import Harness
from tests.support.lessons import CourseHarness
from tests.support.postgres import run_alembic

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_curriculum_json_roundtrip_rights_and_undo(course: CourseHarness) -> None:
    """Append complete shared graphs atomically, preserve existing nodes and undo one batch."""
    case = course.case
    identifier = await create_programme(case, course.state["subject_id"])
    path = f"/api/v1/curricula/{identifier}/subjects/{course.state['subject_id']}"
    try:
        await course.login(course.owner)
        ids = []
        for version, name in enumerate(("A", "B", "Shared")):
            response = await case.client.post(
                path + "/nodes",
                json={
                    "name": name,
                    "expected_version": version,
                    "parent_ids": ids if version == 2 else [],
                    "knowledge": "<script>inert</script>",
                    "comment": "Note",
                    "color": "#123456",
                    "semester": 2,
                },
            )
            assert response.status_code == 201, response.text
            ids.append(
                next(node["id"] for node in response.json()["nodes"] if node["name"] == name)
            )
        exported = await case.client.get(path + "/export")
        assert exported.status_code == 200, exported.text
        document = exported.json()
        assert len(document["nodes"]) == 3
        assert (
            next(node for node in document["nodes"] if node["name"] == "Shared")["parent_ids"]
            == ids[:2]
        )
        assert document["nodes"][0]["knowledge"] == "<script>inert</script>"
        imported = await case.client.post(
            path + "/import", json={"expected_version": 3, "document": json.dumps(document)}
        )
        assert imported.status_code == 200, imported.text
        assert len(imported.json()["nodes"]) == 6 and len(imported.json()["edges"]) == 4
        assert {node["id"] for node in imported.json()["nodes"]} >= set(ids)
        assert len({node["id"] for node in imported.json()["nodes"]}) == 6
        undone = await case.client.post(
            f"/api/v1/curricula/{identifier}/undo", json={"expected_version": 4}
        )
        assert undone.status_code == 200 and len(undone.json()["nodes"]) == 3
        assert (
            await case.client.post(
                path + "/import", json={"expected_version": 0, "document": document}
            )
        ).status_code == 409
        document["nodes"][0]["parent_ids"] = [document["nodes"][0]["id"]]
        assert (
            await case.client.post(
                path + "/import", json={"expected_version": 5, "document": document}
            )
        ).status_code == 422
        assert (await case.client.get(path)).json()["version"] == 5
        _, reader = await case.create("kholleur")
        await course.login(reader)
        assert (await case.client.get(path + "/export")).status_code == 200
        valid = (await case.client.get(path + "/export")).json()
        assert (
            await case.client.post(
                path + "/import", json={"expected_version": 5, "document": valid}
            )
        ).status_code == 403
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Curriculum).where(Curriculum.id == identifier))


def test_curriculum_migration_matches_metadata(migrated_database: None) -> None:
    """Compare the migrated disposable database to every registered SQLAlchemy model."""
    run_alembic("check")


@pytest.mark.asyncio
async def test_curriculum_baseline_upgrade_and_downgrade(migrated_database: None) -> None:
    """Round-trip the consolidated migration while preserving older promotions and calendars."""
    run_alembic("downgrade", "0008_kholloscope")
    database = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    async with database.sessions.begin() as session:
        subject = await session.scalar(
            text(
                "INSERT INTO sophikron.subjects (name, name_key, icon, color) VALUES ('Baseline "
                "SII', 'baseline-sii', 'book', '#4361EE') RETURNING id"
            )
        )
        promotion = await session.scalar(
            text(
                "INSERT INTO sophikron.promotions (year, identifier, color) VALUES (2026, "
                "'Baseline preservation', '#4361EE') RETURNING id"
            )
        )
        calendar = await session.scalar(
            text(
                "INSERT INTO sophikron.timetable_calendars (name, name_key, promotion_id, "
                "revision) VALUES ('Baseline calendar', 'baseline-calendar', :promotion, "
                "'unchanged') RETURNING id"
            ).bindparams(promotion=promotion)
        )
    try:
        for _ in range(2):
            run_alembic("upgrade", "head")
            run_alembic("check")
            async with database.sessions.begin() as session:
                assert (
                    await session.scalar(text("SELECT version_num FROM sophikron.alembic_version"))
                    == "0009_curricula"
                )
                assert await session.scalar(text("SELECT to_regclass('sophikron.tracks')")) is None
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM information_schema.columns WHERE "
                            "table_schema='sophikron' AND table_name='competencies' AND "
                            "column_name='code'"
                        )
                    )
                    == 0
                )
                grants = (
                    await session.execute(
                        text(
                            "SELECT p.code, r.code FROM sophikron.permissions p JOIN "
                            "sophikron.role_permissions rp ON rp.permission_id=p.id JOIN "
                            "sophikron.roles r ON r.id=rp.role_id WHERE p.code LIKE 'curricula.%'"
                        )
                    )
                ).all()
                assert set(grants) == {
                    ("curricula.read", "admin"),
                    ("curricula.read", "teacher"),
                    ("curricula.read", "kholleur"),
                    ("curricula.edit", "teacher"),
                    ("curricula.manage", "admin"),
                }
                programme = await session.scalar(
                    text(
                        "INSERT INTO sophikron.curricula (title, description) VALUES ('Baseline "
                        "programme', 'Current official programme') RETURNING id"
                    )
                )
                await session.execute(
                    text(
                        "INSERT INTO sophikron.curriculum_subjects VALUES (:programme, :subject)"
                    ).bindparams(programme=programme, subject=subject)
                )
                await session.execute(
                    text(
                        "INSERT INTO sophikron.competencies (curriculum_id, subject_id, name) "
                        "VALUES (:programme, :subject, 'Analyser')"
                    ).bindparams(programme=programme, subject=subject)
                )
                await session.execute(
                    text(
                        "UPDATE sophikron.promotions SET curriculum_id=:programme WHERE id=:id"
                    ).bindparams(programme=programme, id=promotion)
                )
            run_alembic("downgrade", "0008_kholloscope")
            async with database.sessions.begin() as session:
                assert (
                    await session.scalar(
                        text("SELECT identifier FROM sophikron.promotions WHERE id=:id").bindparams(
                            id=promotion
                        )
                    )
                    == "Baseline preservation"
                )
                assert (
                    await session.scalar(
                        text("SELECT name FROM sophikron.subjects WHERE id=:id").bindparams(
                            id=subject
                        )
                    )
                    == "Baseline SII"
                )
                assert (
                    await session.execute(
                        text(
                            "SELECT promotion_id, revision FROM sophikron.timetable_calendars "
                            "WHERE id=:id"
                        ).bindparams(id=calendar)
                    )
                ).one() == (promotion, "unchanged")
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM sophikron.permissions WHERE code LIKE "
                            "'curricula.%'"
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(text("SELECT to_regclass('sophikron.curriculum_undo')"))
                    is None
                )
                assert (
                    await session.scalar(text("SELECT to_regclass('sophikron.curricula')")) is None
                )
        run_alembic("upgrade", "head")
        run_alembic("check")
    finally:
        run_alembic("upgrade", "head")
        async with database.sessions.begin() as session:
            await session.execute(
                text("DELETE FROM sophikron.timetable_calendars WHERE id=:id").bindparams(
                    id=calendar
                )
            )
            await session.execute(
                text("DELETE FROM sophikron.promotions WHERE id=:id").bindparams(id=promotion)
            )
            await session.execute(
                text("DELETE FROM sophikron.subjects WHERE id=:id").bindparams(id=subject)
            )
        await database.close()


async def create_programme(case: Harness, subject_id: int) -> int:
    """Create programme metadata using an administrator with no teacher role."""
    case.as_admin()
    response = await case.client.post(
        "/api/v1/curricula",
        json={
            "title": "Programme des deux années",
            "description": "Description du programme officiel",
            "subject_ids": [subject_id],
            "source_url": "https://education.gouv.fr/programme.pdf",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["description"] == "Description du programme officiel"
    assert "track_id" not in response.json()
    return response.json()["id"]


@pytest.mark.asyncio
async def test_curriculum_undo_preserves_identity_and_rejects_other_writers(
    course: CourseHarness,
) -> None:
    """Restore deleted identities, unwind several edits, and deny stale inverse operations."""
    case = course.case
    identifier = await create_programme(case, course.state["subject_id"])
    base = f"/api/v1/curricula/{identifier}"
    path = base + f"/subjects/{course.state['subject_id']}"
    try:
        await course.login(course.owner)
        created = await case.client.post(
            path + "/nodes", json={"name": "Original", "expected_version": 0}
        )
        assert created.status_code == 201, created.text
        node_id = created.json()["nodes"][0]["id"]
        edited = await case.client.put(
            path + f"/nodes/{node_id}", json={"name": "Edited", "expected_version": 1}
        )
        assert edited.status_code == 200, edited.text
        removed = await case.client.request(
            "DELETE", path + f"/nodes/{node_id}", json={"expected_version": 2}
        )
        assert removed.status_code == 200, removed.text
        for version, expected in ((3, "Edited"), (4, "Original"), (5, None)):
            response = await case.client.post(base + "/undo", json={"expected_version": version})
            assert response.status_code == 200, response.text
            if expected:
                assert response.json()["nodes"][0]["id"] == node_id
                assert response.json()["nodes"][0]["name"] == expected
            else:
                assert response.json()["nodes"] == []
        parent = await case.client.post(
            path + "/nodes", json={"name": "Parent", "expected_version": 6}
        )
        parent_id = parent.json()["nodes"][0]["id"]
        child = await case.client.post(
            path + "/nodes",
            json={"name": "Child", "parent_ids": [parent_id], "expected_version": 7},
        )
        expected_edges = child.json()["edges"]
        removed = await case.client.request(
            "DELETE", path + f"/nodes/{parent_id}", json={"expected_version": 8}
        )
        assert removed.status_code == 200 and removed.json()["edges"] == []
        restored = await case.client.post(base + "/undo", json={"expected_version": 9})
        assert restored.status_code == 200, restored.text
        assert restored.json()["edges"] == expected_edges
        await case.client.post(path + "/nodes", json={"name": "Owner edit", "expected_version": 10})
        await course.login(course.collaborator)
        await case.client.post(
            path + "/nodes", json={"name": "Other writer", "expected_version": 11}
        )
        await course.login(course.owner)
        assert (
            await case.client.post(base + "/undo", json={"expected_version": 12})
        ).status_code == 409
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Curriculum).where(Curriculum.id == identifier))


@pytest.mark.asyncio
async def test_curriculum_collaboration_and_integrity(course: CourseHarness) -> None:
    """Enforce subject rights, sharing, cycles, stale edits and child-preserving deletion."""
    case = course.case
    curriculum_id = await create_programme(case, course.state["subject_id"])
    path = f"/api/v1/curricula/{curriculum_id}/subjects/{course.state['subject_id']}"
    try:
        await course.login(course.student)
        assert (await case.client.get("/api/v1/curricula/catalog")).status_code == 403
        await course.login(course.owner)
        assert (
            await case.client.post(
                "/api/v1/curricula",
                json={
                    "title": "Denied",
                    "subject_ids": [course.state["subject_id"]],
                },
            )
        ).status_code == 403
        version = 0
        ids = []
        for name in ("Analyser", "Modéliser", "Compétence partagée"):
            response = await case.client.post(
                path + "/nodes",
                json={
                    "name": name,
                    "expected_version": version,
                    "parent_ids": ids if len(ids) == 2 else [],
                },
            )
            assert response.status_code == 201, response.text
            state = response.json()
            ids.append(next(node["id"] for node in state["nodes"] if node["name"] == name))
            version = state["version"]
        assert len(state["edges"]) == 2
        assert {n["id"]: n["code"] for n in state["nodes"]} == {
            ids[0]: "A",
            ids[1]: "B",
            ids[2]: "A.1",
        }
        assert (
            await case.client.put(
                path + f"/nodes/{ids[2]}",
                json={
                    "name": "Code manuel",
                    "code": "Z",
                    "expected_version": version,
                },
            )
        ).status_code == 422
        rejected = await case.client.put(
            path + f"/nodes/{ids[0]}",
            json={
                "name": "Cycle",
                "expected_version": version,
                "parent_ids": [ids[2]],
            },
        )
        assert rejected.status_code == 422
        assert (await case.client.get(path)).json()["version"] == version
        await course.login(course.collaborator)
        assert (
            await case.client.put(
                path + f"/nodes/{ids[2]}",
                json={
                    "name": "Stale",
                    "expected_version": 0,
                },
            )
        ).status_code == 409
        response = await case.client.put(
            path + f"/nodes/{ids[2]}",
            json={
                "name": "Actualisée partout",
                "expected_version": version,
                "parent_ids": ids[:2],
            },
        )
        assert response.status_code == 200, response.text
        version = response.json()["version"]
        # Composite foreign keys reject a spoofed subject independently of service checks.
        with pytest.raises(IntegrityError):
            async with case.database.sessions.begin() as session:
                session.add(
                    CompetencyLink(
                        curriculum_id=curriculum_id,
                        subject_id=999999,
                        parent_id=ids[0],
                        child_id=ids[1],
                    )
                )
        response = await case.client.request(
            "DELETE", path + f"/nodes/{ids[0]}", json={"expected_version": version}
        )
        assert response.status_code == 200, response.text
        state = response.json()
        assert {n["id"] for n in state["nodes"]} == set(ids[1:])
        assert state["edges"] == [{"parent_id": ids[1], "child_id": ids[2]}]
        assert {n["id"]: n["code"] for n in state["nodes"]} == {ids[1]: "A", ids[2]: "A.1"}
        response = await case.client.put(
            path + f"/nodes/{ids[2]}",
            json={
                "name": "Racine détachée",
                "expected_version": state["version"],
                "parent_ids": [],
            },
        )
        assert response.status_code == 200 and response.json()["edges"] == []
        assert {n["id"]: n["code"] for n in response.json()["nodes"]} == {ids[1]: "A", ids[2]: "B"}
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Curriculum).where(Curriculum.id == curriculum_id))


@pytest.mark.asyncio
async def test_curriculum_reader_and_unassigned_teacher(course: CourseHarness) -> None:
    """Kholleurs can read; unassigned teachers cannot mutate; promotion links stay optional."""
    case = course.case
    curriculum_id = await create_programme(case, course.state["subject_id"])
    path = f"/api/v1/curricula/{curriculum_id}/subjects/{course.state['subject_id']}"
    try:
        _, kholleur = await case.create("kholleur")
        _, stranger = await case.create("teacher")
        for username in (kholleur, stranger):
            await course.login(username)
            assert (await case.client.get(path)).status_code == 200
            assert (
                await case.client.post(
                    path + "/nodes",
                    json={
                        "name": "Denied",
                        "expected_version": 0,
                    },
                )
            ).status_code == 403
        case.as_admin()
        response = await case.client.post(
            "/api/v1/admin/promotions",
            json={
                "year": 2026,
                "identifier": case.prefix,
                "color": "#123456",
            },
        )
        assert response.status_code == 201 and response.json()["curriculum_id"] is None
        promotion_id = response.json()["id"]
        course.promotion_ids.append(promotion_id)
        response = await case.client.patch(
            f"/api/v1/admin/promotions/{promotion_id}", json={"curriculum_id": curriculum_id}
        )
        assert response.status_code == 200 and response.json()["curriculum_id"] == curriculum_id
        response = await case.client.patch(
            f"/api/v1/admin/promotions/{promotion_id}", json={"curriculum_id": None}
        )
        assert response.status_code == 200 and response.json()["curriculum_id"] is None
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(Curriculum).where(Curriculum.id == curriculum_id))
