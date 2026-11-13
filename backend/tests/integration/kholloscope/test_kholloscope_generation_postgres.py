"""Real durable queue, authorization, stale-source checks and publication in PostgreSQL."""

import asyncio
import os
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.models import (
    KholleWish,
    KholloscopeRun,
    PromotionGroup,
    PromotionGroupMember,
    PromotionPartition,
    Subject,
    TeacherAvailability,
    TeacherSubject,
    TimetableCalendar,
    TimetableRoom,
    TimetableSeries,
    TimetableYear,
)
from app.services.kholloscope_worker import generation_maintenance
from app.services.timetable_engine import PARIS
from tests.support.timetable import Workspace, workspace  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_scope", ["future", "all"])
async def test_durable_generation_assignment_and_live_application(
    workspace: Workspace,  # noqa: F811
    remove_scope: str,
) -> None:
    """Exercise actual API rights, queue cancellation, CP-SAT execution and atomic application."""
    w = workspace
    w.case.as_admin()
    path = f"/api/v1/timetable/kholloscope/{w.school_year}"
    preview = (
        await w.case.client.post(f"/api/v1/timetable/calendars/{w.calendar_id}/kholle/preview")
    ).json()
    weeks = [week for week in preview["weeks"] if week["days"] == 5][:2]
    async with w.case.database.sessions.begin() as session:
        subject = Subject(
            name=f"{w.case.prefix}-generator",
            name_key=f"{w.case.prefix}-generator",
            color="#123456",
            icon="book",
        )
        room = TimetableRoom(
            name=f"{w.case.prefix}-solver",
            name_key=f"{w.case.prefix}-solver",
            is_active=True,
            revision="a" * 32,
            kholle_capacity=1,
        )
        session.add_all([subject, room])
        await session.flush()
        subject_id, room_id = subject.id, room.id
        session.add_all(
            [
                TeacherSubject(user_id=w.teacher_id, subject_id=subject_id),
                KholleWish(
                    school_year=w.school_year,
                    user_id=w.teacher_id,
                    subject_id=subject_id,
                    sessions=1,
                ),
                PromotionPartition(
                    promotion_id=w.promotion_id, kind="kholles", target_size=3, revision="b" * 32
                ),
            ]
        )
        await session.flush()
        session.add(PromotionGroup(promotion_id=w.promotion_id, kind="kholles", number=1, x=0, y=0))
        await session.flush()
        session.add(
            PromotionGroupMember(
                promotion_id=w.promotion_id, kind="kholles", group_number=1, user_id=w.pupil_id
            )
        )
        calendar = await session.get(TimetableCalendar, w.calendar_id)
        calendar.kholle_settings = {
            "start": weeks[0]["start"],
            "end": weeks[1]["end"],
            "subjects": [{"subject_id": subject_id, "minutes": 60}],
        }
    worker = None
    try:
        for step in ("volumes", "wishes", "service"):
            workflow = (await w.case.client.get(path + "/workflow")).json()
            response = await w.case.client.put(
                path + "/workflow",
                json={
                    "step": step,
                    "expected_revision": workflow["revision"],
                    "rooms": [{"subject_id": subject_id, "room_ids": [room_id]}]
                    if step == "service"
                    else [],
                },
            )
            assert response.status_code == 200, response.text
        view = (await w.case.client.get(path + "/generation")).json()
        payload = {"expected_revision": view["source_revision"], "rules": {"time_limit": 10}}
        queued = await w.case.client.post(path + "/generation", json=payload)
        assert queued.status_code == 200, queued.text
        assert (await w.case.client.post(path + "/generation", json=payload)).status_code == 409
        assert (
            await w.case.client.post(path + "/generation/cancel", json={"run_id": "f" * 32})
        ).status_code == 409
        assert (
            await w.case.client.post(
                path + "/generation/cancel", json={"run_id": queued.json()["id"]}
            )
        ).status_code == 200
        assert (await w.case.client.get(path + "/generation")).json()["run"][
            "status"
        ] == "cancelled"
        # A failed job must not become a saved generation after Service is edited/reconfirmed.
        async with w.case.database.sessions.begin() as session:
            failed = await session.get(KholloscopeRun, queued.json()["id"])
            failed.status = "failed"
        assert (await w.case.client.get(path + "/groups")).status_code == 409
        state = (await w.case.client.get(path + "/workflow")).json()
        changed_service = await w.case.client.put(
            path + "/workflow",
            json={
                "step": "service",
                "expected_revision": state["revision"],
                "rooms": state["selected_rooms"],
                "teacher_preferences": [
                    {"user_id": p["user_id"], "prefer_own_promotion": False}
                    for p in state["teacher_preferences"]
                ],
            },
        )
        assert changed_service.status_code == 200, changed_service.text
        view = (await w.case.client.get(path + "/generation")).json()
        assert view["run"]["status"] == "failed" and view["run"]["stale"]
        assert (await w.case.client.get(path + "/groups")).status_code == 409
        assert (
            await w.case.client.post(
                path + "/generation/apply",
                json={
                    "expected_revision": view["run"]["revision"],
                    "confirmed_live": True,
                },
            )
        ).status_code == 409
        payload["expected_revision"] = view["source_revision"]
        queued = await w.case.client.post(path + "/generation", json=payload)
        assert queued.status_code == 200, queued.text
        worker = asyncio.create_task(generation_maintenance(w.case.database))
        for _ in range(80):
            view = (await w.case.client.get(path + "/generation")).json()
            if view["run"]["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.25)
        run = view["run"]
        assert run["status"] == "completed", run["logs"]
        assert len(run["result"]["sessions"]) == 1
        assert "track" not in run["result"]["sessions"][0]
        assert (await w.case.client.get(path + "/groups")).status_code == 409
        assert (
            await w.case.client.post(
                path + "/generation/save", json={"expected_revision": "f" * 32}
            )
        ).status_code == 409
        saved = await w.case.client.post(
            path + "/generation/save", json={"expected_revision": run["revision"]}
        )
        assert saved.status_code == 200, saved.text
        run = (await w.case.client.get(path + "/generation")).json()["run"]
        assert run["result"]["saved"]
        service = (await w.case.client.get(path + "/workflow")).json()
        unchanged = await w.case.client.put(
            path + "/workflow",
            json={
                "step": "service",
                "expected_revision": service["revision"],
                "rooms": service["selected_rooms"],
                "teacher_preferences": [
                    {"user_id": p["user_id"], "prefer_own_promotion": p["prefer_own_promotion"]}
                    for p in service["teacher_preferences"]
                ],
            },
        )
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["revision"] == service["revision"]
        assert not (await w.case.client.get(path + "/generation")).json()["run"]["stale"]
        assert (
            await w.case.client.post(
                path + "/generation", json={**payload, "expected_revision": "f" * 64}
            )
        ).status_code == 409
        seat = run["result"]["sessions"][0]
        correction = {
            "expected_revision": run["revision"],
            "session_id": seat["id"],
            "day": seat["day"],
            "start": seat["start"],
            "room_id": seat["room_id"],
            "locked": True,
        }
        assert (
            await w.case.client.put(path + "/generation/session", json={**correction, "start": 1})
        ).status_code == 422
        corrected = await w.case.client.put(path + "/generation/session", json=correction)
        assert corrected.status_code == 200, corrected.text
        assert (
            await w.case.client.put(path + "/generation/session", json=correction)
        ).status_code == 409
        run = (await w.case.client.get(path + "/generation")).json()["run"]
        assert run["result"]["sessions"][0]["locked"]
        assert not run["result"]["saved"]
        assert (await w.case.client.get(path + "/groups")).status_code == 409
        saved = await w.case.client.post(
            path + "/generation/save", json={"expected_revision": run["revision"]}
        )
        assert saved.status_code == 200, saved.text
        run = (await w.case.client.get(path + "/generation")).json()["run"]
        async with w.case.database.sessions.begin() as session:
            session.add(
                TeacherAvailability(
                    user_id=w.teacher_id, school_year=w.school_year, ranges=[], revision="d" * 32
                )
            )
        assert (await w.case.client.get(path + "/generation")).json()["run"]["stale"]
        assert (
            await w.case.client.put(
                path + "/groups",
                json={
                    "expected_revision": run["revision"],
                    "mappings": [{"calendar_id": w.calendar_id, "track": 1, "group": 1}],
                },
            )
        ).status_code == 409
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.user_id == w.teacher_id)
            )
        choices = (await w.case.client.get(path + "/groups")).json()
        assert choices["calendars"][0]["groups"] == [1]
        invalid = {"expected_revision": run["revision"], "mappings": []}
        assert (await w.case.client.put(path + "/groups", json=invalid)).status_code == 422
        assigned = await w.case.client.put(
            path + "/groups",
            json={**invalid, "mappings": [{"calendar_id": w.calendar_id, "track": 1, "group": 1}]},
        )
        assert assigned.status_code == 200, assigned.text
        exported = await w.case.client.get(path + "/pdf")
        assert exported.status_code == 200, exported.text if exported.status_code != 200 else ""
        assert exported.headers["content-type"] == "application/pdf"
        assert exported.headers["cache-control"] == "private, no-store"
        assert exported.content.startswith(b"%PDF-")
        revision = assigned.json()["revision"]
        assert (
            await w.case.client.post(
                path + "/generation/apply", json={"expected_revision": revision}
            )
        ).status_code == 409
        applied = await w.case.client.post(
            path + "/generation/apply", json={"expected_revision": revision, "confirmed_live": True}
        )
        assert applied.status_code == 200, applied.text
        board = await w.board()
        assert len([e for e in board["events"] if e["kind"] == "kholle"]) == 1
        courses = {e["id"] for e in board["events"] if e["kind"] != "kholle"}
        assert (
            await w.case.client.post(
                path + "/generation/apply",
                json={"expected_revision": revision, "confirmed_live": True},
            )
        ).status_code == 409
        # Historical source changes must not bypass the publication freeze.
        async with w.case.database.sessions.begin() as session:
            live = await session.scalar(
                select(TimetableSeries)
                .where(TimetableSeries.year_id == board["years"][0]["id"])
                .order_by(TimetableSeries.id)
            )
            if live is not None:
                live.data = {**live.data, "title": "Correction après publication"}
            annual = await session.get(TimetableYear, board["years"][0]["id"])
            annual.revision = uuid4().hex
        current = (await w.case.client.get(path + "/generation")).json()
        removal = {
            "expected_revision": current["run"]["revision"],
            "expected_source_revision": current["source_revision"],
            "scope": remove_scope,
            "confirmation": "SUPPRIMER",
        }
        assert (
            await w.case.client.post(
                path + "/generation/remove", json={**removal, "confirmation": ""}
            )
        ).status_code == 409
        assert (
            await w.case.client.post(
                path + "/generation/remove", json={**removal, "expected_source_revision": "f" * 64}
            )
        ).status_code == 409
        await w.login(w.teacher_name)
        assert (await w.case.client.get(path + "/generation")).status_code == 403
        assert (await w.case.client.get(path + "/pdf")).status_code == 403
        assert (await w.case.client.get(path + "/groups")).status_code == 403
        assert (await w.case.client.post(path + "/generation", json=payload)).status_code == 403
        assert (
            await w.case.client.post(path + "/generation/remove", json=removal)
        ).status_code == 403
        w.case.as_admin()
        removed = await w.case.client.post(path + "/generation/remove", json=removal)
        if remove_scope == "all":
            assert removed.status_code == 409, removed.text
            expected = 0
        else:
            assert removed.status_code == 200, removed.text
            expected = int(seat["day"] > datetime.now(PARIS).date().isoformat())
            assert removed.json()["removed"] == expected
        board = await w.board()
        assert {e["id"] for e in board["events"] if e["kind"] != "kholle"} == courses
        assert len([e for e in board["events"] if e["kind"] == "kholle"]) == 1 - expected
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.id == w.calendar_id)
            )
            await session.execute(delete(KholleWish).where(KholleWish.subject_id == subject_id))
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room_id))
