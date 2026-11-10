"""Live annual calendars, authorization, archival and bounded-query personal feeds."""

import os
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import pytest
from icalendar import Calendar
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError

from app.models import (
    KholleWish,
    KholloscopeRun,
    KholloscopeWorkflow,
    PromotionGroup,
    PromotionGroupMember,
    PromotionPartition,
    Subject,
    TeacherAvailability,
    TeacherSubject,
    TimetableCalendar,
    TimetablePreferences,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableSeries,
    TimetableYear,
    User,
    UserPromotion,
)
from app.services.timetable_engine import PARIS
from app.services.timetable_lifecycle import rollover
from tests.support.administration import clear_promotions, make_promotion
from tests.support.authentication import PASSWORD
from tests.support.timetable import Workspace

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_kholloscope_database_constraints(workspace: "Workspace") -> None:
    """Enforce commitments, workflow uniqueness, room bounds and queue exclusivity in PostgreSQL."""
    w = workspace
    now = datetime.now(timezone.utc)
    async with w.case.database.sessions() as session, session.begin():
        subject_id = await session.scalar(
            Subject.__table__.insert()
            .values(
                name=w.case.prefix + "-constraints",
                name_key=w.case.prefix + "-constraints",
                color="#123456",
                icon="book",
            )
            .returning(Subject.id)
        )
        wish = dict(
            school_year=w.school_year, user_id=w.teacher_id, subject_id=subject_id, sessions=1
        )
        await session.execute(KholleWish.__table__.insert().values(**wish))
        workflow = dict(school_year=w.school_year, data={}, revision="a" * 32)
        await session.execute(KholloscopeWorkflow.__table__.insert().values(**workflow))
        run = dict(
            id="a" * 32,
            school_year=w.school_year,
            status="queued",
            source_revision="b" * 64,
            revision="c" * 32,
            options={},
            snapshot={},
            logs=[],
            created_at=now,
            updated_at=now,
        )
        await session.execute(KholloscopeRun.__table__.insert().values(**run))
        rejected = [
            (KholleWish.__table__, wish),
            (KholleWish.__table__, {**wish, "user_id": w.pupil_id, "sessions": -1}),
            (KholleWish.__table__, {**wish, "user_id": w.pupil_id, "sessions": 1001}),
            (KholleWish.__table__, {**wish, "subject_id": 9223372036854775807}),
            (KholloscopeWorkflow.__table__, workflow),
            (KholloscopeRun.__table__, {**run, "id": "d" * 32, "status": "running"}),
            (KholloscopeRun.__table__, {**run, "id": "d" * 32, "status": "unknown"}),
            *[
                (
                    TimetableRoom.__table__,
                    dict(
                        name=w.case.prefix,
                        name_key=w.case.prefix,
                        revision="e" * 32,
                        kholle_capacity=capacity,
                    ),
                )
                for capacity in (-1, 101)
            ],
        ]
        for table, values in rejected:
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(table.insert().values(**values))
        # Terminal history may coexist with the active job for the same year.
        await session.execute(
            KholloscopeRun.__table__.insert().values(
                **{**run, "id": "f" * 32, "status": "completed"}
            )
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_kholle_counts_exclude_archived_only_groups_and_retain_mixed_groups(
    workspace: Workspace,
) -> None:
    """Count mixed groups once and exclude empty/archived groups with the shared SQL rule."""
    from app.repositories.groups import active_kholle_group

    w = workspace
    archived = [(await w.case.create())[0] for _ in range(2)]
    w.case.as_admin()
    response = await w.case.client.post(
        f"/api/v1/admin/promotions/{w.promotion_id}/users", json={"user_ids": archived}
    )
    assert response.status_code == 204, response.text
    async with w.case.database.sessions.begin() as db:
        for identifier in archived:
            (await db.get(User, identifier)).status = "disabled"
        db.add(
            PromotionPartition(
                promotion_id=w.promotion_id, kind="kholles", target_size=3, revision="a" * 32
            )
        )
        await db.flush()
        db.add_all(
            [
                PromotionGroup(promotion_id=w.promotion_id, kind="kholles", number=n, x=0, y=0)
                for n in (2, 7, 9)
            ]
        )
        await db.flush()
        db.add_all(
            [
                PromotionGroupMember(
                    promotion_id=w.promotion_id, kind="kholles", group_number=n, user_id=p
                )
                for n, p in ((2, w.pupil_id), (2, archived[0]), (7, archived[1]))
            ]
        )
    path = f"/api/v1/timetable/calendars/{w.calendar_id}/kholle/preview"
    preview = (await w.case.client.post(path)).json()
    assert preview["group_count"] == 1
    async with w.case.database.sessions.begin() as db:
        numbers = list(
            await db.scalars(
                select(PromotionGroup.number).where(
                    PromotionGroup.promotion_id == w.promotion_id,
                    PromotionGroup.kind == "kholles",
                    active_kholle_group(),
                )
            )
        )
        assert numbers == [2]  # Keep original numbering, including gaps.
        (await db.get(User, w.pupil_id)).status = "disabled"
    assert (await w.case.client.post(path)).json()["group_count"] == 0
    async with w.case.database.sessions.begin() as db:
        (await db.get(User, archived[1])).status = "active"
    assert (await w.case.client.post(path)).json()["group_count"] == 1


@pytest.mark.asyncio
async def test_room_capacity_create_edit_preserve_and_permissions(workspace: Workspace) -> None:
    """Persist capacity edits, preserve omitted values and enforce revisions and staff access."""
    w = workspace
    w.case.as_admin()
    created = await w.case.client.post(
        "/api/v1/timetable/rooms", json={"name": f"{w.case.prefix}-cap", "kholle_capacity": 3}
    )
    assert created.status_code == 201, created.text
    room = created.json()
    assert room["kholle_capacity"] == 3
    path = f"/api/v1/timetable/rooms/{room['id']}"
    try:
        for fields in (
            {"name": f"{w.case.prefix}-renamed"},
            {"name": f"{w.case.prefix}-renamed", "kholle_capacity": 0},
        ):
            response = await w.case.client.put(
                path, json={**fields, "expected_revision": room["revision"]}
            )
            assert response.status_code == 200, response.text
            room["revision"] = response.json()["revision"]
            config = (await w.case.client.get("/api/v1/timetable/configuration")).json()
            actual = next(item for item in config["rooms"] if item["id"] == room["id"])
            assert actual["kholle_capacity"] == fields.get("kholle_capacity", 3)
        assert (
            await w.case.client.put(
                path,
                json={"name": "C105", "kholle_capacity": -1, "expected_revision": room["revision"]},
            )
        ).status_code == 422
        assert (
            await w.case.client.put(path, json={"name": "C105", "expected_revision": "f" * 32})
        ).status_code == 409
        await w.login(w.teacher_name)
        assert (
            await w.case.client.put(
                path, json={"name": "C105", "expected_revision": room["revision"]}
            )
        ).status_code == 403
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room["id"]))


@pytest.mark.asyncio
async def test_room_capacity_cut_requires_fresh_confirmation_and_preserves_bookings(
    workspace: Workspace,
) -> None:
    """Preview cuts without writes, recheck changed bookings and authorize confirmation."""
    w = workspace
    w.case.as_admin()
    room = (
        await w.case.client.post(
            "/api/v1/timetable/rooms",
            json={"name": f"{w.case.prefix}-confirm", "kholle_capacity": 2},
        )
    ).json()
    path = f"/api/v1/timetable/rooms/{room['id']}"
    payload = {
        "name": f"{w.case.prefix}-renamed",
        "kholle_capacity": 0,
        "expected_revision": room["revision"],
    }
    try:
        await w.add(kind="kholle", room_id=room["id"])
        preview = await w.case.client.put(path, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["confirmation_required"] is True
        async with w.case.database.sessions.begin() as session:
            actual = await session.get(TimetableRoom, room["id"])
            assert actual.kholle_capacity == 2
            assert actual.name == room["name"]
            assert actual.revision == room["revision"]
        assert (
            await w.case.client.request(
                "DELETE", path, json={"expected_revision": room["revision"]}
            )
        ).status_code == 409
        await w.add(kind="kholle", room_id=room["id"], start_slot=2)
        confirmed = {
            **payload,
            "confirmed_capacity_reduction": True,
            "expected_impact_revision": preview.json()["impact_revision"],
        }
        changed = await w.case.client.put(path, json=confirmed)
        assert changed.json()["confirmation_required"] is True
        assert changed.json()["impact_revision"] != confirmed["expected_impact_revision"]
        confirmed["expected_impact_revision"] = changed.json()["impact_revision"]
        await w.login(w.teacher_name)
        assert (await w.case.client.put(path, json=confirmed)).status_code == 403
        w.case.as_admin()
        response = await w.case.client.put(path, json=confirmed)
        assert response.status_code == 200, response.text
        assert response.json()["revision_required"] is True
        async with w.case.database.sessions.begin() as session:
            actual = await session.get(TimetableRoom, room["id"])
            assert actual.kholle_capacity == 0
        assert any(e["room_id"] == room["id"] for e in (await w.board())["events"])
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableSeries).where(TimetableSeries.room_id == room["id"])
            )
        response = await w.case.client.request(
            "DELETE", path, json={"expected_revision": response.json()["revision"]}
        )
        assert response.status_code == 200, response.text
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableSeries).where(TimetableSeries.room_id == room["id"])
            )
            await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room["id"]))


@pytest.mark.asyncio
async def test_kholloscope_workflow_order_rooms_and_invalidation(workspace: Workspace) -> None:
    """Enforce saved milestone ordering, room eligibility, year scope and stale inputs."""
    w = workspace
    kholleur_id, _ = await w.case.create("kholleur")
    w.case.as_admin()
    initial = (
        await w.case.client.post(f"/api/v1/timetable/calendars/{w.calendar_id}/kholle/preview")
    ).json()
    weeks = [week for week in initial["weeks"] if week["eligible"]][:2]
    async with w.case.database.sessions.begin() as session:
        subject = Subject(
            name=f"{w.case.prefix}-flow",
            name_key=f"{w.case.prefix}-flow",
            icon="book",
            color="#334455",
        )
        room = TimetableRoom(
            name=f"{w.case.prefix}-room", name_key=f"{w.case.prefix}-room", revision="a" * 32
        )
        session.add_all([subject, room])
        await session.flush()
        subject_id, room_id = subject.id, room.id
        session.add(TeacherSubject(user_id=w.teacher_id, subject_id=subject_id))
        session.add(TeacherSubject(user_id=kholleur_id, subject_id=subject_id))
        session.add(UserPromotion(user_id=kholleur_id, promotion_id=w.promotion_id))
        session.add(
            KholleWish(
                school_year=w.school_year, user_id=kholleur_id, subject_id=subject_id, sessions=0
            )
        )
        session.add(
            PromotionPartition(
                promotion_id=w.promotion_id, kind="kholles", target_size=3, revision="a" * 32
            )
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
            "subjects": [{"subject_id": subject_id, "minutes": 540}],
        }
        session.add(
            KholleWish(
                school_year=w.school_year, user_id=w.teacher_id, subject_id=subject_id, sessions=9
            )
        )
    path = f"/api/v1/timetable/kholloscope/{w.school_year}/workflow"
    other_years = [w.school_year - 1, w.school_year + 1]
    other_promotion = await make_promotion(w.case, "PREFERENCE")
    other_calendar = await w.create(promotion=other_promotion)
    async with w.case.database.sessions.begin() as session:
        original = await session.get(TimetableCalendar, w.calendar_id)
        second = await session.get(TimetableCalendar, other_calendar)
        second.kholle_settings = {
            **original.kholle_settings,
            "subjects": [{"subject_id": subject_id, "minutes": 0}],
        }
        session.add(
            PromotionPartition(
                promotion_id=other_promotion, kind="kholles", target_size=3, revision="a" * 32
            )
        )
        await session.flush()
        session.add(
            PromotionGroup(promotion_id=other_promotion, kind="kholles", number=1, x=0, y=0)
        )
        await session.flush()
        session.add(UserPromotion(user_id=w.pupil_id, promotion_id=other_promotion))
        await session.flush()
        session.add(
            PromotionGroupMember(
                promotion_id=other_promotion, kind="kholles", group_number=1, user_id=w.pupil_id
            )
        )
    try:
        response = await w.case.client.get(path)
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["errors"] == state["wish_errors"] == []
        assert state["teacher_preferences"] == [
            {
                "user_id": w.teacher_id,
                "prefer_own_promotion": True,
                "effective": True,
                "promotion_ids": [w.promotion_id],
            },
            {
                "user_id": kholleur_id,
                "prefer_own_promotion": True,
                "effective": True,
                "promotion_ids": [w.promotion_id],
            },
        ]
        assert not any(state["validated"].values())
        assert (
            await w.case.client.put(
                path, json={"step": "service", "expected_revision": state["revision"]}
            )
        ).status_code == 409
        for step in ("volumes", "wishes"):
            response = await w.case.client.put(
                path, json={"step": step, "expected_revision": state["revision"]}
            )
            assert response.status_code == 200, response.text
            state = response.json()
            assert state["validated"][step]
        payload = {
            "step": "service",
            "expected_revision": state["revision"],
            "rooms": [{"subject_id": subject_id, "room_ids": [room_id]}],
            "teacher_preferences": [
                {"user_id": w.teacher_id, "prefer_own_promotion": False},
                {"user_id": kholleur_id, "prefer_own_promotion": False},
            ],
        }
        assert (await w.case.client.put(path, json={**payload, "rooms": []})).status_code == 422
        invalid = [{"subject_id": subject_id, "room_ids": [9223372036854775807]}]
        assert (
            await w.case.client.put(path, json={**payload, "rooms": invalid})
        ).status_code == 422
        response = await w.case.client.put(path, json=payload)
        assert response.status_code == 200, response.text
        assert all(response.json()["validated"].values())
        assert response.json()["teacher_preferences"][0]["prefer_own_promotion"] is False
        assert response.json()["teacher_preferences"][1]["prefer_own_promotion"] is False
        async with w.case.database.sessions.begin() as session:
            session.add(UserPromotion(user_id=w.teacher_id, promotion_id=other_promotion))
        shared = (await w.case.client.get(path)).json()
        assert not shared["teacher_preferences"][0]["effective"]
        assert not shared["teacher_preferences"][0]["prefer_own_promotion"]
        assert shared["validated"] == {"volumes": True, "wishes": True, "service": False}
        reconfirmed = await w.case.client.put(
            path, json={**payload, "expected_revision": shared["revision"]}
        )
        assert reconfirmed.status_code == 200, reconfirmed.text
        async with w.case.database.sessions.begin() as session:
            session.add_all(
                [TimetableSchoolYear(school_year=year, revision="c" * 32) for year in other_years]
            )
        for year in other_years:
            other_path = f"/api/v1/timetable/kholloscope/{year}/workflow"
            other = (await w.case.client.get(other_path)).json()
            assert other["errors"] and not any(other["validated"].values())
            assert (
                await w.case.client.put(
                    other_path, json={"step": "volumes", "expected_revision": other["revision"]}
                )
            ).status_code == 422
        assert all((await w.case.client.get(path)).json()["validated"].values())
        assert (await w.case.client.put(path, json=payload)).status_code == 409
        async with w.case.database.sessions.begin() as session:
            wish = await session.get(KholleWish, (w.school_year, w.teacher_id, subject_id))
            wish.sessions = 8
        changed = (await w.case.client.get(path)).json()
        assert changed["validated"] == {"volumes": True, "wishes": False, "service": False}
        assert changed["available"] == {"volumes": True, "wishes": True, "service": False}
        assert changed["review"] == {"volumes": False, "wishes": True, "service": True}
        assert changed["wish_errors"]
        async with w.case.database.sessions.begin() as session:
            room = await session.get(TimetableRoom, room_id)
            room.is_active = False
        changed = (await w.case.client.get(path)).json()
        assert changed["review"]["service"] and not changed["available"]["service"]
        assert "inactive" in changed["conflicts"]["service"][0]
        async with w.case.database.sessions.begin() as session:
            room = await session.get(TimetableRoom, room_id)
            room.is_active, room.revision = True, "d" * 32
            wish = await session.get(KholleWish, (w.school_year, w.teacher_id, subject_id))
            wish.sessions = 9
        before = (await w.case.client.get(path)).json()
        assert before["validated"] == {"volumes": True, "wishes": True, "service": False}
        reconfirmed = await w.case.client.put(
            path, json={**payload, "expected_revision": before["revision"]}
        )
        assert reconfirmed.status_code == 200, reconfirmed.text
        before = reconfirmed.json()
        assert all(before["validated"].values())
        settings_path = f"/api/v1/timetable/calendars/{w.calendar_id}/kholle"
        current = (await w.case.client.post(settings_path + "/preview")).json()
        save_payload = {
            "expected_revision": current["revision"],
            "expected_year_revision": current["year_revision"],
            "settings": current["settings"],
        }
        unchanged = await w.case.client.put(settings_path, json=save_payload)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["revision"] == current["revision"]
        assert (await w.case.client.get(path)).json() == before
        save_payload["settings"]["subjects"][0]["minutes"] += 60
        changed = await w.case.client.put(settings_path, json=save_payload)
        assert changed.status_code == 200, changed.text
        after = (await w.case.client.get(path)).json()
        assert after["validated"] == {"volumes": False, "wishes": False, "service": False}
        assert not after["available"]["wishes"] and not after["available"]["service"]
        assert after["selected_rooms"] == before["selected_rooms"]
        assert after["subjects"] == before["subjects"]
        assert after["wish_errors"]
        assert (
            await w.case.client.put(
                path,
                json={
                    "step": "service",
                    "expected_revision": after["revision"],
                    "rooms": after["selected_rooms"],
                },
            )
        ).status_code == 409
        await w.login(w.teacher_name)
        assert (await w.case.client.get(path)).status_code == 403
        assert (await w.case.client.put(path, json=payload)).status_code == 403
    finally:
        async with w.case.database.sessions.begin() as session:
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            calendar.kholle_settings = None
            await session.execute(
                delete(KholloscopeWorkflow).where(KholloscopeWorkflow.school_year == w.school_year)
            )
            await session.execute(delete(KholleWish).where(KholleWish.subject_id == subject_id))
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.execute(delete(TimetableRoom).where(TimetableRoom.id == room_id))
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year.in_(other_years))
            )
            await session.execute(
                delete(TimetableCalendar).where(TimetableCalendar.id == other_calendar)
            )
        await clear_promotions([other_promotion])


@pytest.mark.asyncio
async def test_kholle_wishes_roundtrip_atomicity_years_and_permissions(
    workspace: Workspace,
) -> None:
    """Persist exact subject wishes, isolate years and reject stale or unauthorized writes."""
    w = workspace
    kholleur, kholleur_name = await w.case.create("kholleur")
    async with w.case.database.sessions.begin() as session:
        subject = Subject(
            name=f"{w.case.prefix}-wishes",
            name_key=f"{w.case.prefix}-wishes",
            icon="book",
            color="#334455",
        )
        session.add(subject)
        await session.flush()
        subject_id = subject.id
        session.add_all(
            [
                TeacherSubject(user_id=user_id, subject_id=subject_id)
                for user_id in (w.teacher_id, kholleur)
            ]
        )
    path = f"/api/v1/timetable/kholloscope/{w.school_year}/wishes"
    future_year = w.school_year + 1
    try:
        w.case.as_admin()
        response = await w.case.client.get(path)
        assert response.status_code == 200, response.text
        initial = response.json()
        people = next(s for s in initial["subjects"] if s["id"] == subject_id)["staff"]
        assert {p["id"] for p in people} == {w.teacher_id, kholleur}
        assert all(p["first_name"] and p["last_name"] and p["sessions"] is None for p in people)
        assert next(p for p in people if p["id"] == kholleur)["roles"] == ["kholleur"]
        entries = [
            {
                "user_id": p["id"],
                "subject_id": s["id"],
                "sessions": 15 if p["id"] == w.teacher_id else 0,
            }
            for s in initial["subjects"]
            for p in s["staff"]
        ]
        payload = {"expected_revision": initial["revision"], "entries": entries}
        response = await w.case.client.put(path, json=payload)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["revision"] != initial["revision"]
        assert (await w.case.client.put(path, json=payload)).status_code == 409
        payload["expected_revision"] = saved["revision"]
        invalid = [*entries, {"user_id": w.pupil_id, "subject_id": subject_id, "sessions": 10}]
        assert (
            await w.case.client.put(path, json={**payload, "entries": invalid})
        ).status_code == 422
        assert (await w.case.client.get(path)).json() == saved
        assert (
            await w.case.client.put(path, json={**payload, "entries": entries[:-1]})
        ).status_code == 422
        async with w.case.database.sessions.begin() as session:
            session.add(TimetableSchoolYear(school_year=future_year, revision="b" * 32))
        future = await w.case.client.get(f"/api/v1/timetable/kholloscope/{future_year}/wishes")
        assert future.status_code == 200
        assert all(p["sessions"] is None for s in future.json()["subjects"] for p in s["staff"])
        payload["entries"] = [{**entry, "sessions": None} for entry in entries]
        response = await w.case.client.put(path, json=payload)
        assert response.status_code == 200
        assert all(p["sessions"] is None for s in response.json()["subjects"] for p in s["staff"])
        async with w.case.database.sessions.begin() as session:
            assignment = await session.get(TeacherSubject, (kholleur, subject_id))
            await session.delete(assignment)
        payload["expected_revision"] = response.json()["revision"]
        assert (await w.case.client.put(path, json=payload)).status_code == 409
        for username in (w.teacher_name, kholleur_name, w.pupil_name):
            await w.login(username)
            assert (await w.case.client.get(path)).status_code == 403
            assert (await w.case.client.put(path, json=payload)).status_code == 403
        w.case.client.cookies.clear()
        assert (await w.case.client.get(path)).status_code == 401
        w.case.as_admin()
        assert (
            await w.case.client.get("/api/v1/timetable/kholloscope/1900/wishes")
        ).status_code == 404
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(delete(KholleWish).where(KholleWish.subject_id == subject_id))
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == future_year)
            )


@pytest.mark.asyncio
async def test_kholloscope_requires_an_active_calendar(workspace: Workspace) -> None:
    """Exclude archives and explain an empty workspace before all other prerequisites."""
    w = workspace
    async with w.case.database.sessions.begin() as session:
        calendar = await session.get(TimetableCalendar, w.calendar_id)
        calendar.is_archived = True
    w.case.as_admin()
    path = "/api/v1/timetable/kholloscope"
    result = await w.case.client.get(path)
    assert result.status_code == 200
    assert result.json()["errors"] == ["Créer un calendrier en premier."]
    assert (await w.case.client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_kholle_configuration_roundtrip_and_permissions(workspace: Workspace) -> None:
    """Persist exact group volumes, recalculate groups and enforce rights and revisions."""
    w = workspace
    path = f"/api/v1/timetable/calendars/{w.calendar_id}/kholle"
    w.case.as_admin()
    response = await w.case.client.post(path + "/preview")
    assert response.status_code == 200, response.text
    initial = response.json()
    assert initial["settings"] is None
    overview_path = "/api/v1/timetable/kholloscope"
    assert (await w.case.client.get(overview_path)).status_code == 200
    blocked = (await w.case.client.get(overview_path)).json()
    assert blocked["errors"] == [f"Saisir les khôlles du calendrier {w.calendar_id}."]
    async with w.case.database.sessions.begin() as session:
        subject = Subject(
            name=f"{w.case.prefix}-kholle",
            name_key=f"{w.case.prefix}-kholle",
            icon="book",
            color="#334455",
        )
        session.add(subject)
        await session.flush()
        subject_id = subject.id
        session.add(
            PromotionPartition(
                promotion_id=w.promotion_id,
                kind="kholles",
                target_size=3,
                revision="a" * 32,
            )
        )
        await session.flush()
        session.add_all(
            [
                PromotionGroup(promotion_id=w.promotion_id, kind="kholles", number=i, x=0, y=0)
                for i in range(1, 16)
            ]
        )
        await session.flush()
        session.add(
            PromotionGroupMember(
                promotion_id=w.promotion_id, kind="kholles", group_number=1, user_id=w.pupil_id
            )
        )
    try:
        eligible = [week for week in initial["weeks"] if week["eligible"]]
        payload = {
            "expected_revision": initial["revision"],
            "expected_year_revision": initial["year_revision"],
            "settings": {
                "start": eligible[0]["start"],
                "end": eligible[-1]["end"],
                "subjects": [{"subject_id": subject_id, "minutes": 1290}],
            },
        }
        response = await w.case.client.put(path, json=payload)
        assert response.status_code == 200, response.text
        state = (await w.case.client.post(path + "/preview")).json()
        assert state["settings"] == payload["settings"]
        assert state["group_count"] == 1  # The fourteen empty groups are excluded.
        assert state["group_size"] == 3
        overview = await w.case.client.get(overview_path)
        assert overview.status_code == 200, overview.text
        assert overview.json()["calendars"][0]["group_count"] == 1
        assert overview.json()["calendars"][0]["settings"]["subjects"][0]["minutes"] == 1290
        future_year = w.school_year + 1
        async with w.case.database.sessions.begin() as session:
            session.add(TimetableSchoolYear(school_year=future_year, revision="b" * 32))
        previous_settings = w.settings
        try:
            w.settings = {
                **w.settings,
                "start": f"{future_year}-09-01",
                "end": f"{future_year + 1}-08-31",
            }
            draft = await w.create(school_year=future_year)
            newest = (await w.case.client.get(overview_path)).json()
            assert newest["school_year"] == future_year
            assert newest["errors"][0] == f"Affecter le calendrier {draft} à une promo."
            older = (
                await w.case.client.get(overview_path, params={"school_year": w.school_year})
            ).json()
            assert older["errors"] == []
            assert [c["id"] for c in older["calendars"]] == [w.calendar_id]
            assert (
                await w.case.client.get(overview_path, params={"school_year": 1900})
            ).status_code == 422
        finally:
            w.settings = previous_settings
            async with w.case.database.sessions.begin() as session:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id.in_(w.calendar_ids[1:]))
                )
                await session.execute(
                    delete(TimetableSchoolYear).where(
                        TimetableSchoolYear.school_year == future_year
                    )
                )
        assert (await w.case.client.put(path, json=payload)).status_code == 409
        payload["expected_revision"] = state["revision"]
        payload["settings"]["subjects"][0]["subject_id"] = 9223372036854775807
        assert (await w.case.client.put(path, json=payload)).status_code == 422
        unassigned = await w.create()
        blocked = (await w.case.client.get(overview_path)).json()
        assert blocked["errors"] == [
            f"Affecter le calendrier {unassigned} à une promo.",
            f"Saisir les khôlles du calendrier {unassigned}.",
        ]
        assert (await w.case.client.get(overview_path)).status_code == 200
        assert (
            await w.case.client.post(f"/api/v1/timetable/calendars/{unassigned}/kholle/preview")
        ).status_code == 422
        for username in (w.teacher_name, w.pupil_name):
            await w.login(username)
            assert (await w.case.client.get(overview_path)).status_code == 403
            assert (await w.case.client.post(path + "/preview")).status_code == 403
            assert (await w.case.client.put(path, json=payload)).status_code == 403
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(delete(Subject).where(Subject.id == subject_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["course", "td", "tp", "kholle"])
async def test_teacher_promotion_warning_is_nonblocking(workspace: Workspace, kind: str) -> None:
    """Warn for external co-teachers only outside kholles, until promotion assignment."""
    w = workspace
    foreign, _ = await w.case.create("teacher")
    state = await w.add(kind=kind, teacher_ids=[w.teacher_id, foreign])
    code = f"teacher-promotion-{state['years'][0]['id']}-{foreign}"
    assert any(issue["code"] == code for issue in state["issues"]) == (kind != "kholle")
    if kind == "kholle":
        state = await w.add(kind="course", teacher_ids=[w.teacher_id, foreign])
        assert any(issue["code"] == code for issue in state["issues"])
    w.case.as_admin()
    response = await w.case.client.post(
        f"/api/v1/admin/promotions/{w.promotion_id}/users", json={"user_ids": [foreign]}
    )
    assert response.status_code == 204, response.text
    state = await w.board()
    assert not any(issue["code"] == code for issue in state["issues"])
    catalog = (await w.case.client.get("/api/v1/timetable/catalog")).json()
    assert (
        w.promotion_id
        in next(t for t in catalog["teachers"] if t["id"] == foreign)["promotion_ids"]
    )


@pytest.mark.asyncio
async def test_week_pdf_scope_and_private_unpublished_calendar(workspace: Workspace) -> None:
    """Allow authorized unpublished exports and deny unrelated calendars, pupils and bad nodes."""
    w = workspace
    state = await w.add(title="Export PDF")
    year = state["years"][0]
    params = {"year_id": year["id"], "day": state["events"][0]["start"][:10]}
    path = f"/api/v1/timetable/calendars/{w.calendar_id}/pdf"
    response = await w.case.client.get(path, params=params)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    assert len(PdfReader(BytesIO(response.content)).pages) == 1
    assert (
        await w.case.client.get(path, params={**params, "node": "student-999999"})
    ).status_code == 404
    standalone = await w.create()
    own = await w.board(standalone)
    standalone_params = {**params, "year_id": own["years"][0]["id"]}
    standalone_path = f"/api/v1/timetable/calendars/{standalone}/pdf"
    exported = await w.case.client.get(standalone_path, params=standalone_params)
    assert exported.status_code == 200
    assert PdfReader(BytesIO(exported.content)).metadata.title == own["calendars"][0]["name"]
    await w.login(w.teacher_name)
    assert (await w.case.client.get(standalone_path, params=standalone_params)).status_code == 404
    await w.login(w.pupil_name)
    assert (await w.case.client.get(path, params=params)).status_code == 403
    w.case.client.cookies.clear()
    assert (await w.case.client.get(path, params=params)).status_code == 401


@pytest.mark.asyncio
async def test_live_confirmation_stale_write_and_removed_endpoints(workspace: Workspace) -> None:
    """Confirm every live mutation and refuse stale edits, publication and template endpoints."""
    w = workspace
    state = await w.add()
    state = await w.broadcast()
    year = state["years"][0]
    block = {
        key: value
        for key, value in year["series"][0].items()
        if key in {"starts_on", "start_slot", "duration_slots", "teacher_id", "title", "interval"}
    }
    endpoint = f"/api/v1/timetable/years/{year['id']}/series"
    response = await w.case.client.post(
        endpoint, json={"expected_revision": year["revision"], "block": block}
    )
    assert response.status_code == 409
    response = await w.case.client.post(
        endpoint, json={"expected_revision": "0" * 32, "confirmed_live": True, "block": block}
    )
    assert response.status_code == 409
    assert (
        await w.case.client.post(f"/api/v1/timetable/years/{year['id']}/publish", json={})
    ).status_code == 404
    assert (
        await w.case.client.get(f"/api/v1/timetable/years/{year['id']}/template")
    ).status_code == 404
    assert (await w.board())["events"] == state["events"]


@pytest.mark.asyncio
async def test_unique_name_assignment_archival_and_restore(workspace: Workspace) -> None:
    """Enforce uniqueness in services and the database, with archives read-only and reversible."""
    w = workspace
    state = await w.add()
    other = await w.create()
    agenda = (await w.board(other))["calendars"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{other}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "confirmed_assignment": True,
            "is_paused": True,
        },
    )
    assert response.status_code == 409
    current = state["calendars"][0]
    response = await w.case.client.post(
        f"/api/v1/timetable/calendars/{w.calendar_id}/archive",
        json={"expected_revision": current["revision"]},
    )
    assert response.status_code == 200, response.text
    archive_revision = response.json()["revision"]
    catalog = (await w.case.client.get("/api/v1/timetable/catalog")).json()
    assert any(item["id"] == w.calendar_id and item["is_archived"] for item in catalog["calendars"])
    await w.login(w.teacher_name)
    catalog = (await w.case.client.get("/api/v1/timetable/catalog")).json()
    assert catalog["can_read_archives"]
    assert any(item["id"] == w.calendar_id for item in catalog["calendars"])
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 200
    w.case.as_admin()
    kholleur, username = await w.case.create("kholleur")
    assert (
        await w.case.client.put(f"/api/v1/admin/users/{kholleur}/promotions/{w.promotion_id}")
    ).status_code == 204
    await w.login(username)
    catalog = (await w.case.client.get("/api/v1/timetable/catalog")).json()
    assert not catalog["can_read_archives"]
    assert all(item["id"] != w.calendar_id for item in catalog["calendars"])
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 404
    w.case.as_admin()
    year = state["years"][0]
    assert (
        await w.case.client.put(
            f"/api/v1/timetable/years/{year['id']}/settings",
            json={"expected_revision": year["revision"], "settings": year["settings"]},
        )
    ).status_code == 409
    response = await w.case.client.get(
        "/api/v1/timetable/staff/board",
        params={"school_year": w.school_year, "teacher_ids": w.teacher_id},
    )
    assert response.status_code == 200 and response.json()["events"] == []
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{other}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "confirmed_assignment": True,
            "is_paused": True,
        },
    )
    assert response.status_code == 200, response.text
    endpoint = f"/api/v1/timetable/calendars/{w.calendar_id}/restore"
    response = await w.case.client.post(endpoint, json={"expected_revision": archive_revision})
    assert response.status_code == 409
    response = await w.case.client.post(
        endpoint, json={"expected_revision": archive_revision, "detach_promotion": True}
    )
    assert response.status_code == 200, response.text
    restored = (await w.board())["calendars"][0]
    assert (
        restored["promotion_id"] is None and restored["is_paused"] and not restored["is_archived"]
    )


@pytest.mark.asyncio
async def test_dates_hide_and_restore_events_without_destroying_exceptions(
    workspace: Workspace,
) -> None:
    """Retain data under vacation edits and reject changes to immutable grid/self settings."""
    w = workspace
    state = await w.add()
    year = state["years"][0]
    event = state["events"][0]
    changed = {
        **year["settings"],
        "holidays": [{"start": event["source_date"], "end": event["source_date"]}],
    }
    endpoint = f"/api/v1/timetable/years/{year['id']}/settings"
    response = await w.case.client.post(
        endpoint + "/preview", json={"expected_revision": year["revision"], "settings": changed}
    )
    assert response.status_code == 200 and response.json()["hidden"] == 1
    response = await w.case.client.put(
        endpoint, json={"expected_revision": year["revision"], "settings": changed}
    )
    assert response.status_code == 200, response.text
    after = await w.board()
    assert len(after["events"]) == len(state["events"]) - 1
    assert after["years"][0]["series"] == year["series"]
    response = await w.case.client.put(
        endpoint,
        json={"expected_revision": after["years"][0]["revision"], "settings": year["settings"]},
    )
    assert response.status_code == 200 and len((await w.board())["events"]) == len(state["events"])
    fresh = (await w.board())["years"][0]
    for key, value in {
        "day_start": 30000,
        "day_end": 65000,
        "session_minutes": 55,
        "lunch_end": 54000,
    }.items():
        response = await w.case.client.put(
            endpoint,
            json={
                "expected_revision": fresh["revision"],
                "settings": {**fresh["settings"], key: value},
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_availability_and_calendar_conflicts_use_the_same_year(workspace: Workspace) -> None:
    """Warn on explicit unavailability and external bookings without refusing a saved course."""
    w = workspace
    response = await w.case.client.put(
        f"/api/v1/timetable/staff/{w.school_year}/{w.teacher_id}/availability", json={"ranges": []}
    )
    assert response.status_code == 200, response.text
    state = await w.add()
    assert any("Disponibilité" in warning for warning in state["warnings"])
    other = await w.create()
    w.calendar_id, original = other, w.calendar_id
    second = await w.add()
    assert second["teacher_commitments"] and all(
        item["calendar_id"] == original for item in second["teacher_commitments"]
    )
    w.calendar_id = original
    assert any(item["calendar_id"] == other for item in (await w.board())["teacher_commitments"])
    response = await w.case.client.get("/api/v1/timetable/staff/catalog")
    settings = response.json()["years"][0]["settings"]
    assert settings["saturday"] and not settings["breaks"] and settings["day_end"] == 68400


@pytest.mark.asyncio
async def test_live_feed_private_scope_pause_archive_and_query_budget(workspace: Workspace) -> None:
    """Generate real ICS with bounded SQL and immediately honor diffusion and membership rights."""
    w = workspace
    state = await w.add()
    state = await w.broadcast()
    await w.login(w.pupil_name)
    assert (await w.case.client.get("/api/v1/timetable/catalog")).status_code == 403
    assert (await w.case.client.get("/api/v1/timetable/staff/catalog")).status_code == 403
    response = await w.case.client.get("/api/v1/timetable/subscription")
    token = response.json()["token"]
    statements = []

    def count_statement(*arguments: object) -> None:
        """Count real driver executions, including authorization and decoration queries."""
        statements.append(arguments[2])

    sqlalchemy_event.listen(
        w.case.database.engine.sync_engine, "before_cursor_execute", count_statement
    )
    try:
        response = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    finally:
        sqlalchemy_event.remove(
            w.case.database.engine.sync_engine, "before_cursor_execute", count_statement
        )
    assert response.status_code == 200, response.text
    exported = Calendar.from_ical(response.content).walk("VEVENT")
    assert len(exported) > 40 and len(statements) <= 15
    await w.login(w.teacher_name)
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 200
    assert (
        await w.case.client.post("/api/v1/timetable/school-years", json={"school_year": 2100})
    ).status_code == 403
    w.case.as_admin()
    year = state["years"][0]
    first = state["events"][0]
    block = {
        key: value
        for key, value in year["series"][0].items()
        if key in {"starts_on", "start_slot", "duration_slots", "teacher_id", "title", "interval"}
    }
    response = await w.case.client.put(
        f"/api/v1/timetable/years/{year['id']}/series/{first['series_id']}",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "occurrence": first["source_date"],
            "scope": "one",
            "block": {**block, "title": "Replacement"},
        },
    )
    assert response.status_code == 200, response.text
    assert (
        "Cours - REPLACEMENT"
        in (await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")).text
    )
    agenda = (await w.board())["calendars"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "expected_revision": agenda["revision"],
            "is_paused": True,
            "confirmed_live": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        Calendar.from_ical(
            (await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")).content
        ).walk("VEVENT")
        == []
    )
    await w.login(w.teacher_name)
    assert (
        await w.case.client.get("/api/v1/timetable/board", params={"calendar_ids": w.calendar_id})
    ).status_code == 404


@pytest.mark.asyncio
async def test_school_year_is_required_and_ever_used_availability_prevents_deletion(
    workspace: Workspace,
) -> None:
    """Require explicit tags and retain their usage marker even after availability reset."""
    w = workspace
    endpoint = "/api/v1/timetable/school-years"
    response = await w.case.client.post(
        "/api/v1/timetable/calendars",
        json={"name": w.case.prefix + "untagged", "settings": w.settings},
    )
    assert response.status_code == 422
    response = await w.case.client.post(endpoint, json={"school_year": 2080})
    revision = response.json()["revision"]
    assert response.status_code == 201
    assert (
        await w.case.client.request(
            "DELETE", endpoint + "/2080", json={"expected_revision": revision}
        )
    ).status_code == 200
    response = await w.case.client.post(endpoint, json={"school_year": 2080})
    revision = response.json()["revision"]
    try:
        availability = f"/api/v1/timetable/staff/2080/{w.teacher_id}/availability"
        response = await w.case.client.put(availability, json={"ranges": []})
        assert response.status_code == 200, response.text
        response = await w.case.client.put(
            availability, json={"ranges": None, "expected_revision": response.json()["revision"]}
        )
        assert response.status_code == 200
        assert (
            await w.case.client.request(
                "DELETE", endpoint + "/2080", json={"expected_revision": revision}
            )
        ).status_code == 409
        for invalid in [
            {"weekday": 5, "start": 40000, "end": 44000},
            {"weekday": 0, "start": 28000, "end": 30000},
        ]:
            assert (
                await w.case.client.put(availability, json={"ranges": [invalid]})
            ).status_code == 422
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.school_year == 2080)
            )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == 2080)
            )


@pytest.mark.asyncio
async def test_active_promotion_uniqueness_is_also_enforced_by_postgresql(
    workspace: Workspace,
) -> None:
    """Protect the assignment invariant even if a writer bypasses the normal service validation."""
    w = workspace
    other = await w.create()
    with pytest.raises(IntegrityError):
        async with w.case.database.sessions.begin() as session:
            calendar = await session.get(TimetableCalendar, other)
            calendar.promotion_id = w.promotion_id
            await session.flush()
    state = await w.board()
    response = await w.case.client.post(
        "/api/v1/timetable/calendars",
        json={
            "name": state["calendars"][0]["name"].upper(),
            "is_paused": True,
            "settings": w.settings,
            "school_year": w.school_year,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_event_preview_is_read_only_and_uses_actual_lunch_checks(
    workspace: Workspace,
) -> None:
    """Show critical meal diagnostics before saving, without introducing any compact series row."""
    w = workspace
    state = await w.board()
    year = state["years"][0]
    beginning = date.fromisoformat(w.settings["start"])
    beginning += timedelta(days=(-beginning.weekday()) % 7)
    while beginning < date.today():
        beginning += timedelta(days=7)
    response = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/preview",
        json={
            "expected_revision": year["revision"],
            "block": {
                "starts_on": beginning.isoformat(),
                "start_slot": 9,
                "duration_slots": 2,
                "title": "Midday",
                "teacher_id": w.teacher_id,
                "interval": 0,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert any(
        issue["code"].startswith("lunch-") and issue["severity"] == "critical"
        for issue in response.json()["issues"]
    )
    assert (await w.board())["years"][0]["series"] == []
    await w.login(w.teacher_name)
    assert (
        await w.case.client.post(
            f"/api/v1/timetable/years/{year['id']}/preview",
            json={"expected_revision": year["revision"], "block": None},
        )
    ).status_code == 403


@pytest.mark.asyncio
async def test_future_year_bookings_and_availability_do_not_affect_current_year(
    workspace: Workspace,
) -> None:
    """Keep actual persisted bookings and availability isolated by their academic-year tag."""
    w = workspace
    future_year = w.school_year + 1
    response = await w.case.client.post(
        "/api/v1/timetable/school-years", json={"school_year": future_year}
    )
    assert response.status_code == 201, response.text
    future_calendar = None
    try:
        response = await w.case.client.put(
            f"/api/v1/timetable/staff/{future_year}/{w.teacher_id}/availability",
            json={"ranges": []},
        )
        assert response.status_code == 200, response.text
        response = await w.case.client.post(
            "/api/v1/timetable/calendars",
            json={
                "name": w.case.prefix + "future",
                "school_year": future_year,
                "settings": {
                    **w.settings,
                    "start": f"{future_year}-09-01",
                    "end": f"{future_year + 1}-08-31",
                },
                "is_paused": True,
            },
        )
        assert response.status_code == 201, response.text
        future_calendar = response.json()["id"]
        future = (await w.board(future_calendar))["years"][0]
        beginning = date(future_year, 9, 1)
        beginning += timedelta(days=(-beginning.weekday()) % 7)
        response = await w.case.client.post(
            f"/api/v1/timetable/years/{future['id']}/series",
            json={
                "expected_revision": future["revision"],
                "block": {
                    "starts_on": beginning.isoformat(),
                    "start_slot": 0,
                    "duration_slots": 2,
                    "teacher_id": w.teacher_id,
                    "title": "Future only",
                    "interval": 1,
                },
            },
        )
        assert response.status_code == 201, response.text
        assert any(
            "Disponibilité" in warning for warning in (await w.board(future_calendar))["warnings"]
        )
        current = await w.add()
        assert current["teacher_commitments"] == []
        assert not any("Disponibilité" in warning for warning in current["warnings"])
    finally:
        async with w.case.database.sessions.begin() as session:
            if future_calendar is not None:
                await session.execute(
                    delete(TimetableCalendar).where(TimetableCalendar.id == future_calendar)
                )
            await session.execute(
                delete(TeacherAvailability).where(TeacherAvailability.school_year == future_year)
            )
            await session.execute(
                delete(TimetableSchoolYear).where(TimetableSchoolYear.school_year == future_year)
            )


@pytest.mark.asyncio
async def test_free_schedule_round_trips_through_recurrence_edits_and_personal_ics(
    workspace: Workspace,
) -> None:
    """Keep exact custom times through the actual SQL, dated exception and ICS pipeline."""
    w = workspace
    state = await w.add(start_time=50820, end_time=53070, title="Exact custom course")
    assert all(
        event["start"][11:19] == "14:07:00" and event["end"][11:19] == "14:44:30"
        for event in state["events"]
    )
    state = await w.broadcast()
    year = state["years"][0]
    original = state["events"][0]
    response = await w.case.client.put(
        f"/api/v1/timetable/years/{year['id']}/series/{original['series_id']}",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "occurrence": original["source_date"],
            "scope": "one",
            "block": {
                "starts_on": original["source_date"],
                "start_time": 51060,
                "end_time": 52140,
                "teacher_id": w.teacher_id,
                "title": "Changed exact occurrence",
                "interval": 1,
            },
        },
    )
    assert response.status_code == 200, response.text
    await w.login(w.pupil_name)
    response = await w.case.client.get("/api/v1/timetable/subscription")
    token = response.json()["token"]
    response = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    events = Calendar.from_ical(response.content).walk("VEVENT")
    changed = next(
        event for event in events if str(event["summary"]) == "Cours - CHANGED EXACT OCCURRENCE"
    )
    assert changed.decoded("dtstart").astimezone(PARIS).strftime("%H:%M:%S") == "14:11:00"
    assert changed.decoded("dtend").astimezone(PARIS).strftime("%H:%M:%S") == "14:29:00"


@pytest.mark.asyncio
async def test_saved_unique_event_becomes_recurring_and_detached_nodes_stay_independent(
    workspace: Workspace,
) -> None:
    """Round-trip the linked chain behavior through real API previews and persisted SQL rows."""
    w = workspace
    state = await w.add(interval=0)
    first = state["events"][0]
    year = state["years"][0]
    endpoint = f"/api/v1/timetable/years/{year['id']}/series/{first['series_id']}"
    block = {"starts_on": first["source_date"], "title": "Weekly", "interval": 1}
    response = await w.case.client.put(
        endpoint,
        json={
            "expected_revision": year["revision"],
            "occurrence": first["source_date"],
            "scope": "one",
            "block": block,
        },
    )
    assert response.status_code == 200, response.text
    state = await w.board()
    assert len(state["events"]) > 40
    tenth = state["events"][9]
    ninth = state["events"][8]
    response = await w.case.client.put(
        endpoint,
        json={
            "expected_revision": state["years"][0]["revision"],
            "occurrence": tenth["source_date"],
            "scope": "one",
            "block": {**block, "starts_on": tenth["source_date"], "title": "Detached"},
        },
    )
    assert response.status_code == 200, response.text
    state = await w.board()
    detached = next(event for event in state["events"] if event["title"] == "Detached")
    assert detached["id"] == tenth["id"] and detached["series_id"] != tenth["series_id"]
    proposal = {
        "expected_revision": state["years"][0]["revision"],
        "occurrence": ninth["source_date"],
        "scope": "future",
        "block": {**block, "starts_on": ninth["source_date"], "title": "Future", "start_slot": 4},
    }
    preview = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/preview",
        json={**proposal, "series_id": first["series_id"]},
    )
    assert preview.status_code == 200, preview.text
    assert (
        next(event for event in preview.json()["events"] if event["title"] == "Detached")
        == detached
    )
    assert (await w.case.client.put(endpoint, json=proposal)).status_code == 200
    final = await w.board()
    assert [event for event in final["events"] if event["source_date"] == tenth["source_date"]] == [
        detached
    ]


@pytest.mark.asyncio
async def test_archived_custom_members_remain_editable_without_calendar_access(
    workspace: Workspace,
) -> None:
    """Keep archived memberships movable while denying login, subscription and feed contents."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Preserved", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    group = response.json()
    await w.add(title="Preserved option", target_kind="custom", target_number=group["id"])
    await w.broadcast()
    await w.login(w.pupil_name)
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    student_cookie = dict(w.case.client.cookies)
    feed_path = f"/api/v1/timetable/feed/{token}.ics"
    assert Calendar.from_ical((await w.case.client.get(feed_path)).content).walk("VEVENT")
    w.case.as_admin()
    response = await w.case.client.patch(
        f"/api/v1/admin/users/{w.pupil_id}/archive", json={"archived": True}
    )
    assert response.status_code == 204, response.text
    groups = (await w.case.client.get(path + "/groups")).json()["groups"]
    assert groups[0]["student_ids"] == [w.pupil_id]
    response = await w.case.client.put(
        path + f"/{group['id']}",
        json={
            "name": "Preserved renamed",
            "student_ids": [w.pupil_id],
            "expected_revision": group["revision"],
            "confirmed_live": True,
        },
    )
    assert response.status_code == 200, response.text
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Moved archived", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 200, response.text
    for invalid in ([w.teacher_id], [w.pupil_id, w.pupil_id]):
        response = await w.case.client.put(
            path + "/0",
            json={"name": "Invalid", "student_ids": invalid, "expected_revision": None},
        )
        assert response.status_code == 422, response.text
    w.case.client.cookies.clear()
    w.case.client.cookies.update(student_cookie)
    assert (await w.case.client.get("/api/v1/timetable/subscription")).status_code == 401
    assert not Calendar.from_ical((await w.case.client.get(feed_path)).content).walk("VEVENT")
    response = await w.case.client.post(
        "/api/v1/auth/login", json={"identifier": w.pupil_name, "password": PASSWORD}
    )
    assert response.status_code == 401, response.text
    w.case.as_admin()
    response = await w.case.client.delete(
        f"/api/v1/admin/users/{w.pupil_id}/promotions/{w.promotion_id}"
    )
    assert response.status_code == 204, response.text
    assert all(
        w.pupil_id not in item["student_ids"]
        for item in (await w.case.client.get(path + "/groups")).json()["groups"]
    )
    response = await w.case.client.put(
        path + "/0",
        json={"name": "Former pupil", "student_ids": [w.pupil_id], "expected_revision": None},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_named_groups_overlap_validate_roster_and_drive_personal_feeds(
    workspace: Workspace,
) -> None:
    """Authorize named audiences, confirm live changes and export only current recipients."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    for ids in ([], [w.teacher_id], [w.pupil_id, w.pupil_id]):
        response = await w.case.client.put(
            path + "/0", json={"name": "German", "student_ids": ids, "expected_revision": None}
        )
        assert response.status_code == 422, response.text
    group_ids = []
    for name in ("German", "European section"):
        response = await w.case.client.put(
            path + "/0", json={"name": name, "student_ids": [w.pupil_id], "expected_revision": None}
        )
        assert response.status_code == 200, response.text
        group_ids.append(response.json()["id"])
    response = await w.case.client.get(path + "/groups")
    assert len(response.json()["groups"]) == 2
    state = await w.add(title="German option", target_kind="custom", target_number=group_ids[0])
    assert all(event["audience_label"] == "German" for event in state["events"])
    assert any(
        group["kind"] == "custom" and group["student_ids"] == [w.pupil_id]
        for group in state["groups"]
    )
    assert not any(issue["code"].startswith("balance-") for issue in state["issues"])
    await w.broadcast()
    group = response.json()["groups"][0]
    body = {
        "name": group["name"] + " updated",
        "student_ids": [w.pupil_id],
        "expected_revision": group["revision"],
    }
    assert (await w.case.client.put(path + f"/{group['id']}", json=body)).status_code == 409
    assert (
        await w.case.client.put(path + f"/{group['id']}", json={**body, "confirmed_live": True})
    ).status_code == 200
    await w.login(w.pupil_name)
    assert (await w.case.client.get(path + "/groups")).status_code == 403
    assert (
        await w.case.client.put(path + "/0", json={**body, "expected_revision": None})
    ).status_code == 403
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert len(Calendar.from_ical(feed.content).walk("VEVENT")) > 40
    await w.login(w.teacher_name)
    assert (
        await w.case.client.put(path + "/0", json={**body, "expected_revision": None})
    ).status_code == 403
    w.case.as_admin()
    assert (
        await w.case.client.put(path + f"/{group['id']}", json={**body, "confirmed_live": True})
    ).status_code == 409


@pytest.mark.asyncio
async def test_option_hours_exclude_pupils_outside_its_custom_group(workspace: Workspace) -> None:
    """Return annual and weekly option hours for participants through the actual board API."""
    w = workspace
    other_pupil, _ = await w.case.create()
    w.case.as_admin()
    response = await w.case.client.post(
        f"/api/v1/admin/promotions/{w.promotion_id}/users", json={"user_ids": [other_pupil]}
    )
    assert response.status_code == 204, response.text
    response = await w.case.client.post(
        "/api/v1/admin/subjects", json={"name": f"German option {w.case.prefix}"}
    )
    assert response.status_code == 201, response.text
    subject_id = response.json()["id"]
    try:
        response = await w.case.client.put(
            f"/api/v1/promotion-groups/{w.promotion_id}/custom/0",
            json={"name": "German", "student_ids": [w.pupil_id], "expected_revision": None},
        )
        assert response.status_code == 200, response.text
        state = await w.add(
            title="German option",
            subject_id=subject_id,
            target_kind="custom",
            target_number=response.json()["id"],
        )
        annual = state["years"][0]
        hours = next(row for row in annual["hours"] if row["subject_id"] == subject_id)
        session_count = sum(event["subject_id"] == subject_id for event in state["events"])
        assert session_count > 0
        assert hours["course"] == hours["total"] == session_count
        assert hours["weekly"]["total"] == pytest.approx(session_count / len(annual["weeks"]))
    finally:
        async with w.case.database.sessions.begin() as session:
            await session.execute(
                delete(TimetableSeries).where(TimetableSeries.subject_id == subject_id)
            )
            await session.execute(delete(Subject).where(Subject.id == subject_id))


@pytest.mark.asyncio
async def test_custom_group_layout_and_retirement_preserve_existing_sessions(
    workspace: Workspace,
) -> None:
    """Persist bubble positions and retire choices without losing assigned recipients."""
    w = workspace
    path = f"/api/v1/promotion-groups/{w.promotion_id}/custom"
    payload = {
        "name": "German",
        "student_ids": [w.pupil_id],
        "expected_revision": None,
        "x": 620,
        "y": 370,
    }
    assert (await w.case.client.put(path + "/0", json={**payload, "x": -1})).status_code == 422
    created = await w.case.client.put(path + "/0", json=payload)
    assert created.status_code == 200, created.text
    group = (await w.case.client.get(path + "/groups")).json()["groups"][0]
    assert group["x"] == 620 and group["y"] == 370
    await w.add(title="German option", target_kind="custom", target_number=group["id"])
    await w.broadcast()
    endpoint = path + f"/{group['id']}"
    version = {"expected_revision": group["revision"]}
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 409
    await w.login(w.pupil_name)
    token = (await w.case.client.get("/api/v1/timetable/subscription")).json()["token"]
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    count = len(Calendar.from_ical(feed.content).walk("VEVENT"))
    assert count > 40
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 403
    await w.login(w.teacher_name)
    assert (await w.case.client.request("DELETE", endpoint, json=version)).status_code == 403
    w.case.as_admin()
    assert (
        await w.case.client.request(
            "DELETE", endpoint, json={"expected_revision": "0" * 32, "confirmed_live": True}
        )
    ).status_code == 409
    response = await w.case.client.request(
        "DELETE", endpoint, json={**version, "confirmed_live": True}
    )
    assert response.status_code == 200, response.text
    assert (await w.case.client.get(path + "/groups")).json()["groups"] == []
    state = await w.board()
    assert state["events"] and all(event["audience_label"] == "German" for event in state["events"])
    year = state["years"][0]
    response = await w.case.client.post(
        f"/api/v1/timetable/years/{year['id']}/series",
        json={
            "expected_revision": year["revision"],
            "confirmed_live": True,
            "block": {
                "starts_on": state["events"][0]["source_date"],
                "title": "Retired audience",
                "target_kind": "custom",
                "target_number": group["id"],
            },
        },
    )
    assert response.status_code == 422
    replacement = await w.case.client.put(path + "/0", json=payload)
    assert replacement.status_code == 200 and replacement.json()["id"] != group["id"]
    await w.login(w.pupil_name)
    feed = await w.case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert len(Calendar.from_ical(feed.content).walk("VEVENT")) == count


@pytest.mark.asyncio
async def test_past_year_rejection_and_automatic_rollover_policy(workspace: Workspace) -> None:
    """Apply September archival once, honor disabling and preserve manual restoration."""
    w = workspace
    assert (
        await w.case.client.post(
            "/api/v1/timetable/school-years", json={"school_year": w.school_year - 1}
        )
    ).status_code == 422
    await w.add()
    await w.broadcast()
    config = (await w.case.client.get("/api/v1/timetable/configuration")).json()
    assert config["preferences"]["auto_archive"]
    async with w.case.database.sessions.begin() as session:
        row = await session.get(TimetablePreferences, 1)
        saved_year = row.last_rollover_year
    try:
        result = await w.case.client.put(
            "/api/v1/timetable/preferences",
            json={"expected_revision": config["preferences"]["revision"], "auto_archive": False},
        )
        assert result.status_code == 200, result.text
        disabled = result.json()
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 1))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived
        result = await w.case.client.put(
            "/api/v1/timetable/preferences",
            json={"expected_revision": disabled["revision"], "auto_archive": True},
        )
        assert result.status_code == 200, result.text
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 8, 31))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived
        before_revision = (await w.board())["years"][0]["revision"]
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 1))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert calendar.is_archived and calendar.is_paused
            annual = await session.scalar(
                select(TimetableYear).where(TimetableYear.calendar_id == calendar.id)
            )
            assert annual.revision != before_revision
            calendar.is_archived = False
        async with w.case.database.sessions.begin() as session:
            await rollover(session, date(w.school_year + 1, 9, 2))
            calendar = await session.get(TimetableCalendar, w.calendar_id)
            assert not calendar.is_archived and calendar.is_paused
    finally:
        async with w.case.database.sessions.begin() as session:
            row = await session.get(TimetablePreferences, 1)
            row.auto_archive, row.last_rollover_year = True, saved_year
