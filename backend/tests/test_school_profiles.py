"""Validation, authorization and encrypted storage coverage for private school profiles."""

import asyncio
import json
import os
from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models import AccountInvitation, ActivityEvent, User
from app.schemas.profile import AdminProfileUpdate, Baccalaureate, SchoolProfile
from app.services.profiles import calculate_age
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

integration = pytest.mark.skipif(
    os.environ.get("DB_INTEGRATION") != "1", reason="PostgreSQL required"
)


@pytest.mark.parametrize(
    "birth,today,expected",
    [
        (None, date(2026, 5, 17), None),
        (date(2006, 5, 17), date(2026, 5, 16), 19),
        (date(2006, 5, 17), date(2026, 5, 17), 20),
        (date(2004, 2, 29), date(2025, 2, 28), 20),
        (date(2004, 2, 29), date(2025, 3, 1), 21),
    ],
)
def test_age_birthday_boundaries(birth: date | None, today: date, expected: int | None) -> None:
    """Keep birthday boundaries and leap-day handling explicit without persisting an age."""
    assert calculate_age(birth, today) == expected


@pytest.mark.parametrize(
    "body",
    [
        {"birth_date": (date.today() + timedelta(days=1)).isoformat()},
        {"phone": "hello"},
        {"postal_code": "7500"},
        {"orientation_project": "x" * 201},
        {"reference_adult": {"first_name": "Paul", "last_name": "Roy"}},
        {"baccalaureate": {"overall_grade": 20.01}},
        {"baccalaureate": {"subjects": [{"name": "Maths", "grade": -1}]}},
        {"baccalaureate": {"subjects": [{"name": "Maths"}, {"name": "maths"}]}},
    ],
)
def test_invalid_private_fields(body: dict[str, object]) -> None:
    """Reject invalid dates, contact details, oversized text and out-of-range marks."""
    with pytest.raises(ValidationError):
        SchoolProfile.model_validate(body)


def test_profile_validation_and_immutable_username() -> None:
    """Accept zero marks and normalize contact numbers while rejecting username patches."""
    assert SchoolProfile(phone="06 12 34 56 78").phone == "+33612345678"
    assert Baccalaureate(overall_grade=0).overall_grade == 0
    with pytest.raises(ValidationError):
        AdminProfileUpdate(expected_version=0, username="changed103")
    with pytest.raises(ValidationError):
        AdminProfileUpdate(expected_version=0, email=None)


@pytest.mark.parametrize("roles", [None, [], ["unknown"], ["user", "teacher"], ["admin", "admin"]])
def test_invalid_profile_roles(roles: object) -> None:
    """Reject null, empty, unknown, duplicate and incompatible grants before persistence."""
    with pytest.raises(ValidationError):
        AdminProfileUpdate.model_validate({"expected_version": 0, "roles": roles})


@pytest.mark.parametrize("roles", [["user"], ["teacher"], ["admin"], ["teacher", "admin"]])
def test_valid_profile_roles(roles: list[str]) -> None:
    """Apply the same four role choices to profile edits as account creation."""
    assert AdminProfileUpdate(expected_version=0, roles=roles).roles == roles
    assert "roles" not in AdminProfileUpdate(expected_version=0).model_dump(exclude_unset=True)


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_private_profile_edit_encryption_and_version(
    auth_case: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Save encrypted details atomically, preserve username and prevent stale overwrites."""
    case = auth_case
    user_id, username = await case.create()
    invitation = await case.client.post(f"/api/v1/admin/users/{user_id}/access-invitation")
    assert invitation.status_code == 200

    async def commune(code: str, postcode: str) -> str:
        """Use a synthetic canonical location without making tests depend on a public service."""
        assert (code, postcode) == ("75056", "75001")
        return "Paris"

    monkeypatch.setattr("app.services.profiles.validate_commune", commune)
    path = f"/api/v1/admin/users/{user_id}/profile"
    patch = {
        "expected_version": 0,
        "first_name": "Élodie",
        "last_name": "Roy",
        "email": "updated-profile@example.org",
        "birth_date": "2006-05-17",
        "city": "untrusted label",
        "postal_code": "75001",
        "commune_code": "75056",
        "phone": "06 12 34 56 78",
        "previous_school": "Lycée Exemple",
        "baccalaureate": {
            "label": "Général",
            "year": 2024,
            "overall_grade": 15.5,
            "subjects": [{"name": "Mathématiques", "grade": 0}, {"name": "SI", "grade": 18}],
        },
        "orientation_project": "École d’ingénieurs",
        "reference_adult": {"first_name": "Marie", "last_name": "Roy", "phone": "01 23 45 67 89"},
    }
    response = await case.client.patch(path, json=patch)
    assert response.status_code == 200, response.text
    details = response.json()
    assert details["username"] == username and details["profile_version"] == 1
    assert details["profile"]["city"] == "Paris"
    assert details["profile"]["reference_adult"]["phone"] == "+33123456789"
    assert details["profile"]["baccalaureate"]["subjects"][0]["grade"] == 0
    assert (await case.client.patch(path, json=patch)).status_code == 409
    assert (
        await case.client.patch(path, json={"expected_version": 1, "username": "hack103"})
    ).status_code == 422
    async with case.database.sessions() as session:
        stored = await session.get(User, user_id)
        assert stored.email_verified_at is None
        issued = await session.scalar(
            select(AccountInvitation)
            .where(AccountInvitation.user_id == user_id)
            .order_by(AccountInvitation.id.desc())
            .limit(1)
        )
        assert issued.revoked_at is not None
        for field, value in details["profile"].items():
            encrypted = getattr(stored, field + "_encrypted")
            assert encrypted is not None
            assert (
                json.loads(case.app.state.identity_cipher.decrypt(user_id, field, encrypted))
                == value
            )
        journal = (
            await session.scalars(
                select(ActivityEvent).where(ActivityEvent.event_type == "user.profile_updated")
            )
        ).all()
        assert journal and all("changed_fields" in event.data for event in journal)
        assert "Roy" not in json.dumps([event.data for event in journal])
    user = (await case.client.get(f"/api/v1/admin/users/{user_id}")).json()
    assert "birth_date" not in user and "profile" not in user
    matches = await case.client.get("/api/v1/admin/users/search?q=elodie%20roy")
    assert matches.json()[0]["id"] == user_id
    login = await case.client.post(
        "/api/v1/auth/login",
        json={"identifier": "updated-profile@example.org", "password": PASSWORD},
    )
    assert login.status_code == 200 and login.json()["username"] == username
    own = await case.client.get("/api/v1/auth/me/profile")
    assert own.status_code == 200 and own.json()["profile"] == details["profile"]
    assert not own.json()["can_edit_all"]
    assert (
        await case.client.patch(path, json={"expected_version": 1, "phone": "+33612345678"})
    ).status_code == 403
    case.as_admin()
    await case.client.patch(f"/api/v1/admin/users/{user_id}/archive", json={"archived": True})
    assert (await case.client.get(path)).status_code == 200


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_profile_teacher_scope_and_field_permissions(auth_case: Harness) -> None:
    """Restrict teacher edits to orientation and reads to shared archived students."""
    case = auth_case
    teacher_id, teacher = await case.create("teacher")
    student_id, _ = await case.create(activate=False)
    outsider_id, _ = await case.create(activate=False)
    promotion_id = await make_promotion(case, "PROFILE")
    try:
        await case.client.post(
            f"/api/v1/admin/promotions/{promotion_id}/users",
            json={"user_ids": [teacher_id, student_id]},
        )
        await case.client.patch(
            f"/api/v1/admin/users/{student_id}/archive", json={"archived": True}
        )
        await case.client.post(
            "/api/v1/auth/login", json={"identifier": teacher, "password": PASSWORD}
        )
        path = f"/api/v1/teaching/users/{student_id}/profile"
        detail = await case.client.get(path)
        assert detail.status_code == 200, detail.text
        assert detail.json()["can_edit_orientation"] and not detail.json()["can_edit_all"]
        for field in ["first_name", "email", "phone", "reference_adult", "birth_date"]:
            assert (
                await case.client.patch(
                    path,
                    json={"expected_version": 0, "orientation_project": "Prépa", field: "invalid"},
                )
            ).status_code == 422
        updated = await case.client.patch(
            path, json={"expected_version": 0, "orientation_project": "  École   d’ingénieurs  "}
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["profile"]["orientation_project"] == "École d’ingénieurs"
        assert (
            await case.client.get(f"/api/v1/teaching/users/{outsider_id}/profile")
        ).status_code == 404
        assert (
            await case.client.patch(
                f"/api/v1/teaching/users/{outsider_id}/profile",
                json={"expected_version": 0, "orientation_project": "Test"},
            )
        ).status_code == 404
        assert (
            await case.client.get(f"/api/v1/teaching/users/{case.administrator}/profile")
        ).status_code == 404
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{student_id}/profile",
                json={"expected_version": 1, "phone": "+33612345678"},
            )
        ).status_code == 403
        own = await case.client.get("/api/v1/auth/me/profile")
        assert own.status_code == 200 and own.json()["id"] == teacher_id
        assert not own.json()["can_edit_orientation"]
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_profile_duplicate_email_rolls_back(auth_case: Harness) -> None:
    """Reject duplicate emails without partially saving other edited profile fields."""
    case = auth_case
    user_id, _ = await case.create()
    path = f"/api/v1/admin/users/{user_id}/profile"
    email = (await case.client.get(f"/api/v1/admin/users/{case.administrator}")).json()["email"]
    response = await case.client.patch(
        path, json={"expected_version": 0, "first_name": "Paul", "email": email}
    )
    assert response.status_code == 409
    detail = (await case.client.get(path)).json()
    assert detail["first_name"] == "Valentin" and detail["profile_version"] == 0


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_role_changes_apply_to_existing_sessions_and_journal(auth_case: Harness) -> None:
    """Promote and demote through all combinations, updating existing sessions immediately."""
    case = auth_case
    user_id, username = await case.create()
    login = await case.client.post(
        "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    assert login.status_code == 200
    cookie = case.app.state.auth_settings.cookie_name
    member_token = case.client.cookies.get(cookie)
    path = f"/api/v1/admin/users/{user_id}/profile"
    previous = ["user"]
    for version, roles in enumerate([["teacher"], ["teacher", "admin"], ["admin"], ["user"]]):
        case.as_admin()
        response = await case.client.patch(path, json={"expected_version": version, "roles": roles})
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["roles"] == sorted(roles)
        assert detail["profile_version"] == version + 1 and detail["username"] == username
        async with case.database.sessions() as session:
            event = await session.scalar(
                select(ActivityEvent)
                .where(
                    ActivityEvent.subject_user_id == user_id,
                    ActivityEvent.event_type == "user.roles_updated",
                )
                .order_by(ActivityEvent.id.desc())
                .limit(1)
            )
            assert event.actor_user_id == case.administrator
            assert event.actor_role == "admin"
            assert event.subject_role == ("admin" if "admin" in previous else previous[0])
            assert event.data == {"previous_roles": sorted(previous), "roles": sorted(roles)}
        case.client.cookies.clear()
        case.client.cookies.set(cookie, member_token, domain="testserver.local", path="/")
        me = await case.client.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["roles"] == sorted(roles)
        assert ("users.manage" in me.json()["permissions"]) == ("admin" in roles)
        assert ("teacher.access" in me.json()["permissions"]) == ("teacher" in roles)
        response = await case.client.get("/api/v1/admin/summary")
        assert response.status_code == (200 if "admin" in roles else 403)
        previous = roles


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_role_changes_noop_validation_and_atomicity(auth_case: Harness) -> None:
    """Reject invalid and stale edits, and roll back grants when a profile edit fails."""
    case = auth_case
    user_id, _ = await case.create("admin")
    path = f"/api/v1/admin/users/{user_id}/profile"
    response = await case.client.patch(
        path, json={"expected_version": 0, "roles": ["teacher", "admin"]}
    )
    assert response.status_code == 200, response.text
    response = await case.client.patch(
        path, json={"expected_version": 1, "roles": ["admin", "teacher"]}
    )
    assert response.status_code == 200 and response.json()["profile_version"] == 1
    assert (
        await case.client.patch(path, json={"expected_version": 0, "roles": ["user"]})
    ).status_code == 409
    for roles in [None, [], ["user", "admin"], ["teacher", "teacher"], ["unknown"]]:
        assert (
            await case.client.patch(path, json={"expected_version": 1, "roles": roles})
        ).status_code == 422
    email = (await case.client.get(f"/api/v1/admin/users/{case.administrator}")).json()["email"]
    response = await case.client.patch(
        path,
        json={"expected_version": 1, "email": email, "roles": ["user"], "first_name": "Paul"},
    )
    assert response.status_code == 409
    detail = (await case.client.get(path)).json()
    assert detail["roles"] == ["admin", "teacher"] and detail["profile_version"] == 1
    assert detail["first_name"] == "Valentin"
    async with case.database.sessions() as session:
        events = list(
            await session.scalars(
                select(ActivityEvent).where(
                    ActivityEvent.subject_user_id == user_id,
                    ActivityEvent.event_type == "user.roles_updated",
                )
            )
        )
        assert len(events) == 1


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_nonadministrators_cannot_change_roles(auth_case: Harness) -> None:
    """Reject student self-promotion and teacher attempts through both profile endpoints."""
    case = auth_case
    student_id, student = await case.create()
    _, teacher = await case.create("teacher")
    for username in [student, teacher]:
        await case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
        )
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{student_id}/profile",
                json={"expected_version": 0, "roles": ["admin"]},
            )
        ).status_code == 403
        response = await case.client.patch(
            f"/api/v1/teaching/users/{student_id}/profile",
            json={"expected_version": 0, "orientation_project": "Test", "roles": ["admin"]},
        )
        assert response.status_code == (422 if username == teacher else 403)
    case.as_admin()
    detail = (await case.client.get(f"/api/v1/admin/users/{student_id}/profile")).json()
    assert detail["roles"] == ["user"] and detail["profile_version"] == 0


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_concurrent_role_edits_do_not_overwrite(auth_case: Harness) -> None:
    """Serialize competing role updates and reject the stale profile version."""
    case = auth_case
    user_id, _ = await case.create()
    path = f"/api/v1/admin/users/{user_id}/profile"
    responses = await asyncio.gather(
        case.client.patch(path, json={"expected_version": 0, "roles": ["admin"]}),
        case.client.patch(path, json={"expected_version": 0, "roles": ["teacher"]}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    accepted = next(response.json() for response in responses if response.status_code == 200)
    detail = (await case.client.get(path)).json()
    assert detail["roles"] == accepted["roles"] and detail["profile_version"] == 1


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_administrator_cannot_remove_own_admin_role(auth_case: Harness) -> None:
    """Prevent losing one's own administrative access while allowing teacher grant changes."""
    case = auth_case
    path = f"/api/v1/admin/users/{case.administrator}/profile"
    for roles in [["user"], ["teacher"]]:
        response = await case.client.patch(
            path, json={"expected_version": 0, "roles": roles, "first_name": "Paul"}
        )
        assert response.status_code == 409
    detail = (await case.client.get(path)).json()
    assert detail["roles"] == ["admin"] and detail["first_name"] == "Valentin"
    assert detail["profile_version"] == 0
    for version, roles in enumerate([["teacher", "admin"], ["admin"]]):
        response = await case.client.patch(path, json={"expected_version": version, "roles": roles})
        assert response.status_code == 200, response.text
        assert response.json()["roles"] == sorted(roles)
    await case.create("admin")
    response = await case.client.patch(path, json={"expected_version": 2, "roles": ["user"]})
    assert response.status_code == 409
