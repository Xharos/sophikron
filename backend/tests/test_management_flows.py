"""PostgreSQL integration coverage for staff dashboards, archives and renewed invitations."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AccountInvitation, ActivityEvent
from app.services.mail import DisabledMailer
from tests.test_auth_postgres import PASSWORD, SECOND_PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("activated", [False, True])
async def test_archive_restore_and_renew_access(auth_case: Harness, activated: bool) -> None:
    """Preserve activation state, revoke sessions/links and support manual access renewal."""
    case = auth_case
    user_id, username = await case.create(activate=activated)
    case.app.state.mailer = DisabledMailer()
    invited = await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")
    assert invited.status_code == 200, invited.text
    data = invited.json()
    assert data["delivery"] == "manual"
    assert data["purpose"] == ("reset" if activated else "activation")
    token = data["token"]
    old_cookie = None
    if activated:
        assert (
            await case.client.post(
                "/api/v1/auth/login",
                json={
                    "identifier": username,
                    "password": PASSWORD,
                },
            )
        ).status_code == 200
        old_cookie = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    case.as_admin()
    path = f"/api/v1/admin/users/{user_id}/archive"
    assert (await case.client.patch(path, json={"archived": True})).status_code == 204
    assert (await case.client.get(f"/api/v1/admin/users/{user_id}")).json()["archived_at"]
    assert (
        await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")
    ).status_code == 409
    async with case.database.sessions() as db:
        revoked = await db.scalar(
            select(AccountInvitation).where(
                AccountInvitation.user_id == user_id, AccountInvitation.used_at.is_(None)
            )
        )
        assert revoked is not None and revoked.revoked_at is not None
    assert (
        await case.client.post(
            "/api/v1/auth/activate", json={"token": token, "password": SECOND_PASSWORD}
        )
    ).status_code == 400
    if old_cookie:
        case.client.cookies.set(
            case.app.state.auth_settings.cookie_name,
            old_cookie,
            domain="testserver.local",
            path="/",
        )
        assert (await case.client.get("/api/v1/auth/me")).status_code == 401
        case.as_admin()
    assert (await case.client.patch(path, json={"archived": False})).status_code == 204
    detail = (await case.client.get(f"/api/v1/admin/users/{user_id}")).json()
    assert detail["status"] == ("active" if activated else "pending_activation")
    assert detail["archived_at"] is None
    assert (
        await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 400
    renewed = (await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")).json()
    assert (
        await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": renewed["token"],
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 204
    assert (
        await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": renewed["token"],
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 400
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_active_password_reset_revokes_sessions_and_email_delivery(
    auth_case: Harness,
) -> None:
    """Email reset uses one-use invitation without revealing its secret in the response."""
    case = auth_case
    user_id, username = await case.create()
    await case.client.post(
        "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    old_cookie = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    case.as_admin()
    result = await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")
    assert result.status_code == 200 and result.json()["delivery"] == "email"
    assert result.json()["token"] is None
    token = case.mailer.messages[-1][1]
    assert (
        await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 204
    case.client.cookies.set(
        case.app.state.auth_settings.cookie_name, old_cookie, domain="testserver.local", path="/"
    )
    assert (await case.client.get("/api/v1/auth/me")).status_code == 401
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": PASSWORD,
            },
        )
    ).status_code == 401
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": SECOND_PASSWORD,
            },
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_summary_self_protection_and_atomic_members(auth_case: Harness) -> None:
    """Count real account states, prohibit self-archive and reject partial batch assignments."""
    case = auth_case
    assert (
        await case.client.patch(
            f"/api/v1/admin/users/{case.administrator}/archive", json={"archived": True}
        )
    ).status_code == 409
    user_id, _ = await case.create(activate=False)
    summary = (await case.client.get("/api/v1/admin/summary")).json()
    assert summary["total_accounts"] == 2 and summary["pending_accounts"] == 1
    promotion_id = await make_promotion(case)
    try:
        path = f"/api/v1/admin/promotions/{promotion_id}/users"
        assert (
            await case.client.post(path, json={"user_ids": [user_id, 9223372036854775807]})
        ).status_code == 422
        assert (await case.client.get(path)).json()["total"] == 0
        assert (await case.client.post(path, json={"user_ids": [user_id]})).status_code == 204
        assert (await case.client.post(path, json={"user_ids": [user_id]})).status_code == 204
        assert (await case.client.get(path)).json()["total"] == 1
        assert (
            await case.client.get(
                "/api/v1/admin/users/search",
                params={
                    "q": (await case.client.get(f"/api/v1/admin/users/{user_id}")).json()[
                        "username"
                    ]
                },
            )
        ).json()[0]["id"] == user_id
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_teacher_scope_includes_archived_students(auth_case: Harness) -> None:
    """Teachers see archived students only within shared promotions, without admin security data."""
    case = auth_case
    teacher_id, teacher = await case.create("teacher")
    student_id, _ = await case.create(activate=False)
    outsider_id, _ = await case.create(activate=False)
    assigned = await make_promotion(case, "ASSIGNED")
    other = await make_promotion(case, "OTHER")
    try:
        await case.client.post(
            f"/api/v1/admin/promotions/{assigned}/users",
            json={"user_ids": [teacher_id, student_id]},
        )
        await case.client.post(
            f"/api/v1/admin/promotions/{other}/users", json={"user_ids": [outsider_id]}
        )
        await case.client.patch(
            f"/api/v1/admin/users/{student_id}/archive", json={"archived": True}
        )
        await case.client.patch(f"/api/v1/admin/promotions/{assigned}", json={"is_active": False})
        await case.client.post(
            "/api/v1/auth/login", json={"identifier": teacher, "password": PASSWORD}
        )
        own = (await case.client.get("/api/v1/auth/me/promotions")).json()
        assert [item["id"] for item in own] == [assigned]
        promotions = await case.client.get("/api/v1/teaching/promotions")
        assert promotions.status_code == 200
        assert [item["id"] for item in promotions.json()["items"]] == [assigned]
        students = await case.client.get("/api/v1/teaching/users")
        assert students.status_code == 200, students.text
        assert [item["id"] for item in students.json()["items"]] == [student_id]
        profile = await case.client.get(f"/api/v1/teaching/users/{student_id}")
        assert profile.status_code == 200 and profile.json()["status"] == "disabled"
        assert {"email", "login_count", "invitation", "permissions"}.isdisjoint(profile.json())
        assert (await case.client.get(f"/api/v1/teaching/users/{outsider_id}")).status_code == 404
        assert (
            await case.client.get(f"/api/v1/teaching/users?promotion_id={other}")
        ).status_code == 404
        matches = await case.client.get("/api/v1/teaching/users/search?q=valentin")
        assert [item["id"] for item in matches.json()] == [student_id]
        for path in ("/api/v1/admin/users", "/api/v1/admin/summary", "/api/v1/admin/events"):
            assert (await case.client.get(path)).status_code == 403
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{student_id}/archive", json={"archived": False}
            )
        ).status_code == 403
        case.as_admin()
        assert (await case.client.get("/api/v1/teaching/promotions")).status_code == 403
    finally:
        await clear_promotions([assigned, other])


@pytest.mark.asyncio
async def test_event_date_order_and_expired_invitation(auth_case: Harness) -> None:
    """Sort events by actual occurrence and reject expired links for either account state."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    future = datetime.now(UTC) + timedelta(days=1)
    async with case.database.sessions.begin() as session:
        event = ActivityEvent(
            event_type="user.created",
            actor_user_id=case.administrator,
            subject_user_id=user_id,
            occurred_at=future,
            data={},
        )
        session.add(event)
    page = await case.client.get("/api/v1/admin/events?limit=1")
    assert page.status_code == 200
    assert datetime.fromisoformat(page.json()["items"][0]["occurred_at"]) == future
    assert page.json()["items"][0]["subject_label"] == "Valentin Burgaud"
    cursor = page.json()["next_cursor"]
    next_page = await case.client.get("/api/v1/admin/events", params={"cursor": cursor, "limit": 1})
    assert next_page.json()["items"][0]["id"] != page.json()["items"][0]["id"]
    assert (await case.client.get("/api/v1/admin/events?cursor=invalid")).status_code == 422
    case.app.state.mailer = DisabledMailer()
    token = (await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")).json()[
        "token"
    ]
    async with case.database.sessions.begin() as session:
        invitation = await session.scalar(
            select(AccountInvitation).where(AccountInvitation.user_id == user_id)
        )
        invitation.created_at = datetime.now(UTC) - timedelta(days=3)
        invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
    assert (
        await case.client.post("/api/v1/auth/activate", json={"token": token, "password": PASSWORD})
    ).status_code == 400
