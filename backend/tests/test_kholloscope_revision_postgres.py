"""Real PostgreSQL branch isolation, stale merge rejection and incremental publication."""

import asyncio
import os
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.models import (
    KholleWish,
    KholloscopeRun,
    KholloscopeWorkflow,
    PromotionGroup,
    PromotionGroupMember,
    PromotionPartition,
    Subject,
    TeacherSubject,
    TimetableCalendar,
    TimetableRoom,
    TimetableSeries,
    TimetableYear,
    User,
)
from app.schemas.kholloscope_generation import GenerationRules
from app.schemas.timetable import SeriesData
from app.services.kholloscope_worker import generation_maintenance
from app.services.timetable_engine import PARIS
from tests.test_timetable_workspace_postgres import Workspace, workspace  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("temporary", [False, True])
async def test_revision_isolated_merge_and_repeated_repair(
    workspace: Workspace,  # noqa: F811
    temporary: bool,
) -> None:
    """Keep live sessions stable through calculation, reject stale merges and protect history."""
    w = workspace
    replacement, _ = await w.case.create("kholleur")
    w.case.as_admin()
    path = f"/api/v1/timetable/kholloscope/{w.school_year}"
    today = datetime.now(PARIS).date()
    monday = today + timedelta(days=7 - today.weekday())
    # Keep the full test period inside the fixture's academic bounds, even near August.
    if monday + timedelta(days=32) > date(w.school_year + 1, 8, 31):
        pytest.skip("Insufficient future weeks in this academic year")
    worker = None
    subject_id = room_id = alternative_id = 0
    try:
        async with w.case.database.sessions.begin() as db:
            subject = Subject(
                name=w.case.prefix + "-revision",
                name_key=w.case.prefix + "-revision",
                color="#123456",
                icon="book",
            )
            room = TimetableRoom(
                name=w.case.prefix + "-revision",
                name_key=w.case.prefix + "-revision",
                kholle_capacity=1,
                revision=uuid4().hex,
            )
            db.add_all([subject, room])
            await db.flush()
            subject_id, room_id = subject.id, room.id
            db.add_all(
                [
                    TeacherSubject(user_id=w.teacher_id, subject_id=subject_id),
                    TeacherSubject(user_id=replacement, subject_id=subject_id),
                    KholleWish(
                        school_year=w.school_year,
                        user_id=w.teacher_id,
                        subject_id=subject_id,
                        sessions=1,
                    ),
                    KholleWish(
                        school_year=w.school_year,
                        user_id=replacement,
                        subject_id=subject_id,
                        sessions=0,
                    ),
                    PromotionPartition(
                        promotion_id=w.promotion_id,
                        kind="kholles",
                        target_size=3,
                        revision=uuid4().hex,
                    ),
                ]
            )
            await db.flush()
            db.add(PromotionGroup(promotion_id=w.promotion_id, kind="kholles", number=1, x=0, y=0))
            await db.flush()
            db.add(
                PromotionGroupMember(
                    promotion_id=w.promotion_id, kind="kholles", group_number=1, user_id=w.pupil_id
                )
            )
            calendar = await db.get(TimetableCalendar, w.calendar_id)
            calendar.kholle_settings = {
                "start": (monday - timedelta(days=7)).isoformat(),
                "end": (monday + timedelta(days=32)).isoformat(),
                "subjects": [{"subject_id": subject_id, "minutes": 180}],
            }
            db.add(
                KholloscopeWorkflow(
                    school_year=w.school_year,
                    revision=uuid4().hex,
                    data={"rooms": [{"subject_id": subject_id, "room_ids": [room_id]}]},
                )
            )
            annual = await db.scalar(
                select(TimetableYear).where(TimetableYear.calendar_id == w.calendar_id)
            )
            sessions = []
            for day in (
                monday - timedelta(days=7),
                monday + timedelta(days=7),
                monday + timedelta(days=14),
            ):
                identifier = uuid4().hex
                block = SeriesData(
                    id=identifier,
                    lineage=identifier,
                    starts_on=day,
                    interval=0,
                    start_slot=0,
                    duration_slots=2,
                    start_time=28800,
                    end_time=32400,
                    subject_id=subject_id,
                    teacher_id=w.teacher_id,
                    teacher_ids=[w.teacher_id],
                    room_id=room_id,
                    kind="kholle",
                    target_kind="kholles",
                    target_number=1,
                )
                db.add(
                    TimetableSeries(
                        id=identifier,
                        year_id=annual.id,
                        subject_id=subject_id,
                        teacher_id=w.teacher_id,
                        room_id=room_id,
                        data=block.model_dump(mode="json"),
                    )
                )
                sessions.append(
                    {
                        "id": identifier,
                        "calendar_id": w.calendar_id,
                        "day": day.isoformat(),
                        "original_day": day.isoformat(),
                        "start": 28800,
                        "end": 32400,
                        "subject_id": subject_id,
                        "teacher_id": w.teacher_id,
                        "room_id": room_id,
                        "track": 1,
                        "group": 1,
                    }
                )
            now = datetime.now(timezone.utc)
            published_id = uuid4().hex
            db.add(
                KholloscopeRun(
                    id=published_id,
                    school_year=w.school_year,
                    status="completed",
                    source_revision="a" * 64,
                    revision=uuid4().hex,
                    options=GenerationRules().model_dump(),
                    snapshot={
                        "calendars": [],
                        "subjects": [
                            {
                                "id": subject_id,
                                "staff": [
                                    {"id": w.teacher_id, "sessions": 1},
                                    {"id": replacement, "sessions": 0},
                                ],
                            }
                        ],
                    },
                    logs=[],
                    result={
                        "applied": True,
                        "sessions": sessions,
                        "assigned_sessions": sessions,
                        "template": [],
                        "quotas": [],
                        "mappings": [{"calendar_id": w.calendar_id, "track": 1, "group": 1}],
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
        original = (await w.board())["events"]
        # Publication freezes direct preparation writes, even with fresh revisions.
        wishes = (await w.case.client.get(path + "/wishes")).json()
        wishes_response = await w.case.client.put(
            path + "/wishes",
            json={
                "expected_revision": wishes["revision"],
                "entries": [
                    {"user_id": person["id"], "subject_id": subject["id"], "sessions": 0}
                    for subject in wishes["subjects"]
                    for person in subject["staff"]
                ],
            },
        )
        assert wishes_response.status_code == 409, wishes_response.text
        assert "Révision" in wishes_response.text
        workflow = (await w.case.client.get(path + "/workflow")).json()
        response = await w.case.client.put(
            path + "/workflow",
            json={"expected_revision": workflow["revision"], "step": "volumes", "rooms": []},
        )
        assert response.status_code == 409, response.text
        settings_path = f"/api/v1/timetable/calendars/{w.calendar_id}/kholle"
        settings = (await w.case.client.post(settings_path + "/preview")).json()
        assert settings["published"] is True
        response = await w.case.client.put(
            settings_path,
            json={
                "expected_revision": settings["revision"],
                "expected_year_revision": settings["year_revision"],
                "settings": settings["settings"],
            },
        )
        assert response.status_code == 409, response.text
        assert (await w.board())["events"] == original
        state = (await w.case.client.get(path + "/revision")).json()
        assert state["branch"] is None
        assert state["problems"] == []
        config = (await w.case.client.get("/api/v1/timetable/configuration")).json()
        room_state = next(r for r in config["rooms"] if r["id"] == room_id)
        room_path = f"/api/v1/timetable/rooms/{room_id}"
        reduction = {
            "name": room_state["name"],
            "expected_revision": room_state["revision"],
            "kholle_capacity": 0,
        }
        impact = (await w.case.client.put(room_path, json=reduction)).json()
        assert impact["confirmation_required"] is True
        reduced = await w.case.client.put(
            room_path,
            json={
                **reduction,
                "confirmed_capacity_reduction": True,
                "expected_impact_revision": impact["impact_revision"],
            },
        )
        assert reduced.status_code == 200, reduced.text
        problem_state = (await w.case.client.get(path + "/revision")).json()
        assert problem_state["needs_recalculation"] is True
        assert any(p["kind"] == "room_capacity" for p in problem_state["problems"])
        assert (await w.board())["events"] == original
        restored = await w.case.client.put(
            room_path,
            json={
                "name": room_state["name"],
                "expected_revision": reduced.json()["revision"],
                "kholle_capacity": 1,
            },
        )
        assert restored.status_code == 200, restored.text
        async with w.case.database.sessions.begin() as db:
            pupil = await db.get(User, w.pupil_id)
            previous_status = pupil.status
            pupil.status = "disabled"
        problem_state = (await w.case.client.get(path + "/revision")).json()
        assert any(
            p["kind"] == "groups" and p["expected_count"] == 1 and p["actual_count"] == 0
            for p in problem_state["problems"]
        )
        async with w.case.database.sessions.begin() as db:
            pupil = await db.get(User, w.pupil_id)
            pupil.status = previous_status
        state = (await w.case.client.get(path + "/revision")).json()
        assert state["problems"] == []
        create = {
            "expected_source_revision": state["source_revision"],
            "subject_ids": [subject_id],
            "effective_on": monday.isoformat(),
            "return_on": (monday + timedelta(days=14)).isoformat() if temporary else None,
        }
        assert (
            await w.case.client.post(
                path + "/revision",
                json={**create, "effective_on": (monday + timedelta(days=1)).isoformat()},
            )
        ).status_code == 422
        assert (await w.case.client.post(path + "/revision", json=create)).status_code == 200
        assert (await w.case.client.post(path + "/revision", json=create)).status_code == 409
        branch = (await w.case.client.get(path + "/revision")).json()["branch"]
        assert (await w.case.client.get(path + "/generation")).json()["run"]["id"] == published_id
        calculate = {
            "expected_revision": branch["revision"],
            "wishes": [
                {"subject_id": subject_id, "user_id": w.teacher_id, "sessions": 0},
                {"subject_id": subject_id, "user_id": replacement, "sessions": 1},
            ],
            "rules": {"time_limit": 5},
        }
        response = await w.case.client.post(path + "/revision/calculate", json=calculate)
        assert response.status_code == 200, response.text
        assert (await w.board())["events"] == original
        worker = asyncio.create_task(generation_maintenance(w.case.database))
        for _ in range(100):
            branch = (await w.case.client.get(path + "/revision")).json()["branch"]
            if branch["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.1)
        assert branch["status"] == "completed", branch["logs"]
        assert len(branch["result"]["changes"]) == (1 if temporary else 2)
        assert (await w.board())["events"] == original
        merge = {
            "expected_revision": branch["revision"],
            "effective_on": monday.isoformat(),
            "return_on": create["return_on"],
            "confirmed_live": True,
        }
        if temporary:
            assert (
                await w.case.client.post(
                    path + "/revision/merge", json={**merge, "return_on": None}
                )
            ).status_code == 409
        assert (
            await w.case.client.post(
                path + "/revision/merge", json={**merge, "confirmed_live": False}
            )
        ).status_code == 409
        assert (
            await w.case.client.post(
                path + "/revision/merge",
                json={**merge, "effective_on": (monday + timedelta(days=7)).isoformat()},
            )
        ).status_code == 409
        response = await w.case.client.post(path + "/revision/merge", json=merge)
        assert response.status_code == 200, response.text
        changed = (await w.board())["events"]
        assert len(changed) == len(original)
        assert changed[0] == original[0]
        assert changed[1]["id"] == original[1]["id"]
        assert changed[1]["teacher_id"] == replacement
        if temporary:
            assert changed[2] == original[2]
        assert (await w.case.client.post(path + "/revision/merge", json=merge)).status_code == 409
        state = (await w.case.client.get(path + "/revision")).json()
        # A second branch begins with the accepted service, without rewriting annual wishes.
        assert (
            await w.case.client.post(
                path + "/revision",
                json={**create, "expected_source_revision": state["source_revision"]},
            )
        ).status_code == 200
        branch = (await w.case.client.get(path + "/revision")).json()["branch"]
        assert (
            next(wish["sessions"] for wish in branch["wishes"] if wish["user_id"] == replacement)
            == 1
        )
        response = await w.case.client.post(
            path + "/revision/calculate",
            json={**calculate, "expected_revision": branch["revision"]},
        )
        assert response.status_code == 200, response.text
        for _ in range(100):
            branch = (await w.case.client.get(path + "/revision")).json()["branch"]
            if branch["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.1)
        assert branch["status"] == "completed", branch["logs"]
        assert branch["result"]["changes"] == []
        async with w.case.database.sessions.begin() as db:
            annual = await db.scalar(
                select(TimetableYear).where(TimetableYear.calendar_id == w.calendar_id)
            )
            annual.revision = uuid4().hex
        assert (
            await w.case.client.post(
                path + "/revision/merge", json={**merge, "expected_revision": branch["revision"]}
            )
        ).status_code == 409
        assert (
            await w.case.client.post(
                path + "/revision/calculate",
                json={**calculate, "expected_revision": branch["revision"]},
            )
        ).status_code == 409
        await w.login(w.teacher_name)
        assert (await w.case.client.get(path + "/revision")).status_code == 403
        assert (await w.case.client.post(path + "/revision", json=create)).status_code == 403
        assert (await w.case.client.post(path + "/revision/merge", json=merge)).status_code == 403
        assert (
            await w.case.client.post(
                path + "/revision/rollback",
                json={
                    "revision_id": published_id,
                    "expected_revision": "a" * 32,
                },
            )
        ).status_code == 403
        assert (
            await w.case.client.post(
                path + "/revision/room",
                json={
                    "expected_source_revision": "a" * 64,
                    "room_id": room_id,
                    "replacement_room_id": room_id + 1,
                    "starts_on": monday.isoformat(),
                    "subject_ids": [subject_id],
                },
            )
        ).status_code == 403
        assert (
            await w.case.client.post(path + "/revision/calculate", json=calculate)
        ).status_code == 403
        await w.login(w.pupil_name)
        assert (await w.case.client.get(path + "/revision")).status_code == 403
        assert (await w.case.client.post(path + "/revision/merge", json=merge)).status_code == 403
        w.case.as_admin()
        assert (
            await w.case.client.post(
                path + "/revision/discard", json={"expected_revision": branch["revision"]}
            )
        ).status_code == 200
        assert (await w.board())["events"] == changed
        state = (await w.case.client.get(path + "/revision")).json()
        pending = state["pending_publications"]
        assert len(pending) == 1 and pending[0]["can_rollback"]
        assert "rollback" not in state["branch"]["result"]
        rollback = {"revision_id": pending[0]["id"], "expected_revision": pending[0]["revision"]}
        # Content edits block rollback even when the publication token itself is still current.
        async with w.case.database.sessions.begin() as db:
            item = await db.scalar(
                select(TimetableSeries)
                .where(TimetableSeries.year_id == annual.id)
                .order_by(TimetableSeries.id)
                .limit(1)
            )
            saved_data = {**item.data}
            item.data = {**item.data, "title": "Changed since publication"}
            changed_series_id = item.id
        assert (
            await w.case.client.post(path + "/revision/rollback", json=rollback)
        ).status_code == 409
        async with w.case.database.sessions.begin() as db:
            item = await db.get(TimetableSeries, changed_series_id)
            item.data = saved_data
        response = await w.case.client.post(path + "/revision/rollback", json=rollback)
        assert response.status_code == 200, response.text
        assert (await w.board())["events"] == original
        assert not (await w.case.client.get(path + "/revision")).json()["pending_publications"]
        assert (
            await w.case.client.post(path + "/revision/rollback", json=rollback)
        ).status_code == 409

        async with w.case.database.sessions.begin() as db:
            alternative = TimetableRoom(
                name=w.case.prefix + "-alternative",
                name_key=w.case.prefix + "-alternative",
                kholle_capacity=1,
                revision=uuid4().hex,
            )
            db.add(alternative)
            await db.flush()
            alternative_id = alternative.id
        state = (await w.case.client.get(path + "/revision")).json()
        room_change = {
            "expected_source_revision": state["source_revision"],
            "room_id": room_id,
            "replacement_room_id": alternative_id,
            "starts_on": monday.isoformat(),
            "subject_ids": [subject_id],
        }
        response = await w.case.client.post(path + "/revision/room", json=room_change)
        assert response.status_code == 200, response.text
        assert response.json()["count"] == 2 and not response.json()["published"]
        assert (await w.board())["events"] == original
        response = await w.case.client.post(
            path + "/revision/room", json={**room_change, "confirmed_live": True}
        )
        assert response.status_code == 200, response.text
        adjusted = (await w.board())["events"]
        assert adjusted[0] == original[0]
        assert all(e["room_id"] == alternative_id for e in adjusted[1:])
        assert [e["start"] for e in adjusted] == [e["start"] for e in original]
        pending = (await w.case.client.get(path + "/revision")).json()["pending_publications"][0]
        assert (
            await w.case.client.post(
                path + "/revision/rollback",
                json={"revision_id": pending["id"], "expected_revision": pending["revision"]},
            )
        ).status_code == 200
        assert (await w.board())["events"] == original
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        async with w.case.database.sessions.begin() as db:
            await db.execute(
                delete(KholloscopeRun).where(KholloscopeRun.school_year == w.school_year)
            )
            await db.execute(delete(TimetableCalendar).where(TimetableCalendar.id == w.calendar_id))
            await db.execute(delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id))
            await db.execute(delete(KholleWish).where(KholleWish.subject_id == subject_id))
            await db.execute(delete(Subject).where(Subject.id == subject_id))
            await db.execute(delete(TimetableRoom).where(TimetableRoom.id == room_id))
            await db.execute(delete(TimetableRoom).where(TimetableRoom.id == alternative_id))
