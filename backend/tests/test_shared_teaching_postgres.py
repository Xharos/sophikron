"""Shared teaching assignments, pupil-only diffusion and current ICS usage eligibility."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from icalendar import Calendar

from app.models import TimetableSubscription
from tests.test_calendar_subscriptions_postgres import personal
from tests.test_timetable_workspace_postgres import Workspace, workspace  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
async def test_shared_session_private_staff_exports_and_eligible_ratio(
    workspace: Workspace,  # noqa: F811
) -> None:
    """Keep one occurrence for two teachers and deny unpublished exports to pupils."""
    w, case = workspace, workspace.case
    second, name = await case.create("teacher")
    case.as_admin()
    response = await case.client.put(f"/api/v1/admin/users/{second}/promotions/{w.promotion_id}")
    assert response.status_code == 204
    await w.add(teacher_ids=[w.teacher_id, second])
    await w.login(w.pupil_name)
    assert (await personal(case))["token"] is None
    uids = []
    for teacher_name in (w.teacher_name, name):
        await w.login(teacher_name)
        token = (await personal(case))["token"]
        response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
        events = Calendar.from_ical(response.content).walk("VEVENT")
        assert len(events) > 40
        assert len(str(events[0]["description"]).splitlines()) == 3
        uids.append({str(event["uid"]) for event in events})
    assert uids[0] == uids[1]
    case.as_admin()
    stats = (await case.client.get("/api/v1/admin/statistics?period=day")).json()
    assert stats["calendar_recent_users"] == stats["calendar_eligible_users"] == 2
    total = stats["calendar_requests_total"]
    assert total >= 2
    await w.broadcast()
    await w.login(w.pupil_name)
    pupil_token = (await personal(case))["token"]
    assert pupil_token
    response = await case.client.get(f"/api/v1/timetable/feed/{pupil_token}.ics")
    assert {
        str(event["uid"]) for event in Calendar.from_ical(response.content).walk("VEVENT")
    } == uids[0]
    case.as_admin()
    stats = (await case.client.get("/api/v1/admin/statistics?period=day")).json()
    assert stats["calendar_recent_users"] == stats["calendar_eligible_users"] == 3
    assert stats["calendar_requests_total"] == total + 1
    agenda = (await w.board())["calendars"][0]
    response = await case.client.put(
        f"/api/v1/timetable/calendars/{w.calendar_id}",
        json={
            "name": agenda["name"],
            "promotion_id": w.promotion_id,
            "is_paused": True,
            "expected_revision": agenda["revision"],
            "confirmed_live": True,
        },
    )
    assert response.status_code == 200
    response = await case.client.get(f"/api/v1/timetable/feed/{pupil_token}.ics")
    assert Calendar.from_ical(response.content).walk("VEVENT") == []
    response = await case.client.post(
        f"/api/v1/timetable/subscriptions/users/{w.teacher_id}", json={"action": "revoke"}
    )
    assert response.status_code == 200
    stats = (await case.client.get("/api/v1/admin/statistics?period=day")).json()
    assert stats["calendar_recent_users"] == stats["calendar_eligible_users"] == 1
    assert stats["calendar_requests_total"] == total + 1
    await w.login(name)
    response = await case.client.get(
        "/api/v1/timetable/staff/board",
        params={
            "school_year": w.school_year,
            "teacher_ids": second,
        },
    )
    assert response.status_code == 200
    assert response.json()["events"] and all(
        second in item["teacher_ids"] for item in response.json()["events"]
    )
    async with case.database.sessions.begin() as session:
        subscription = await session.get(TimetableSubscription, second)
        subscription.last_requested_at = datetime.now(UTC) - timedelta(days=8)
    case.as_admin()
    stats = (await case.client.get("/api/v1/admin/statistics?period=day")).json()
    assert stats["calendar_recent_users"] == 0 and stats["calendar_eligible_users"] == 1
    assert {item["label"]: item["value"] for item in stats["calendar_subscriptions"]} == {
        "Consulté": 0,
        "Non consulté sur la période": 1,
    }
