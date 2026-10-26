"""Real PostgreSQL dashboard, encryption, role/permission and journal boundaries."""

import asyncio
import os
from math import ceil
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.config import DatabaseSettings
from app.core.database import Database
from app.models import (
    ActivityEvent,
    Promotion,
    PromotionAccountBlock,
    Role,
    User,
    UserPromotion,
    UserRole,
)
from tests.test_auth_postgres import PASSWORD, Harness

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


async def make_promotion(case: Harness, identifier: str = "PTSI") -> int:
    """Create a synthetic promotion and return its generated integer identity."""
    case.as_admin()
    response = await case.client.post(
        "/api/v1/admin/promotions",
        json={
            "year": 2019,
            "identifier": identifier,
            "color": "#123abc",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def clear_promotions(ids: list[int]) -> None:
    """Remove synthetic catalogue rows through the migration role after memberships are gone."""
    database = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    try:
        async with database.sessions.begin() as session:
            await session.execute(
                delete(PromotionAccountBlock).where(PromotionAccountBlock.promotion_id.in_(ids))
            )
            await session.execute(delete(UserPromotion).where(UserPromotion.promotion_id.in_(ids)))
            await session.execute(delete(Promotion).where(Promotion.id.in_(ids)))
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_promotion_memberships_and_archive(auth_case: Harness) -> None:
    """Archive/reactivate without deleting users or memberships; journal only actual changes."""
    case = auth_case
    promotion_id = await make_promotion(case)
    try:
        assert (
            await case.client.post(
                "/api/v1/admin/promotions",
                json={
                    "year": 2019,
                    "identifier": "PTSI",
                    "color": "#123ABC",
                },
            )
        ).status_code == 409
        ids = []
        for role in ("user", "teacher", "kholleur"):
            user_id, _ = await case.create(role, activate=False)
            ids.append(user_id)
            path = f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}"
            assert (await case.client.put(path)).status_code == 204
            assert (await case.client.put(path)).status_code == 204
        response = await case.client.get(f"/api/v1/admin/promotions/{promotion_id}/users?limit=2")
        assert response.status_code == 200 and response.json()["total"] == 3
        assert len(response.json()["items"]) == 2
        path = f"/api/v1/admin/promotions/{promotion_id}"
        assert (await case.client.get(path)).json()["member_count"] == 3
        assert (await case.client.delete(path)).status_code == 405
        assert (await case.client.patch(path, json={"is_active": False})).status_code == 200
        memberships = await case.client.get(f"/api/v1/admin/users/{ids[0]}/promotions")
        assert memberships.json()["items"][0]["is_active"] is False
        other, _ = await case.create(activate=False)
        assert (
            await case.client.put(f"/api/v1/admin/users/{other}/promotions/{promotion_id}")
        ).status_code == 409
        assert (await case.client.get("/api/v1/admin/promotions?is_active=true")).json()[
            "total"
        ] == 0
        assert (await case.client.patch(path, json={"is_active": True})).status_code == 200
        link = f"/api/v1/admin/users/{ids[0]}/promotions/{promotion_id}"
        assert (await case.client.delete(link)).status_code == 204
        assert (await case.client.delete(link)).status_code == 204
        events = (
            await case.client.get(
                f"/api/v1/admin/events?resource_type=promotion&resource_id={promotion_id}"
            )
        ).json()["items"]
        assert sum(event["event_type"] == "promotion.member_added" for event in events) == 3
        assert sum(event["event_type"] == "promotion.member_removed" for event in events) == 1
        assert {"promotion.created", "promotion.archived", "promotion.reactivated"} <= {
            event["event_type"] for event in events
        }
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_promotion_role_eligibility_and_teaching_filter(auth_case: Harness) -> None:
    """Enforce all assignment paths and page the union of teaching roles without duplicates."""
    case = auth_case
    promotion_id = await make_promotion(case)
    try:
        ids = []
        for index, roles in enumerate(
            [
                ["user"],
                ["teacher"],
                ["kholleur"],
                ["teacher", "kholleur"],
                ["admin", "teacher"],
                ["admin", "kholleur"],
                ["admin", "teacher", "kholleur"],
            ]
        ):
            response = await case.client.post(
                "/api/v1/admin/users",
                json={
                    "first_name": "Camille",
                    "last_name": "Martin",
                    "email": f"{case.prefix}-eligible-{index}@example.org",
                    "roles": roles,
                    "promotion_ids": [promotion_id],
                },
            )
            assert response.status_code == 201, response.text
            user_id = response.json()["id"]
            case.ids.append(user_id)
            ids.append(user_id)
            link = f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}"
            assert (await case.client.delete(link)).status_code == 204
            assert (await case.client.put(link)).status_code == 204
        path = f"/api/v1/admin/promotions/{promotion_id}/users"
        assert (await case.client.post(path, json={"user_ids": ids})).status_code == 204
        assert (await case.client.get(path)).json()["total"] == 7
        for root, params in [
            (path, {}),
            ("/api/v1/admin/users", {"promotion_id": promotion_id}),
        ]:
            paged = []
            for offset in [0, 2, 4]:
                response = await case.client.get(
                    root,
                    params={
                        **params,
                        "role": "teaching",
                        "offset": offset,
                        "limit": 2,
                    },
                )
                assert response.status_code == 200, response.text
                assert response.json()["total"] == 6
                paged.extend(item["id"] for item in response.json()["items"])
            assert paged == ids[1:]
        searched = await case.client.get(
            "/api/v1/admin/users/search",
            params={
                "q": "Camille",
                "role": "teaching",
                "promotion_id": promotion_id,
            },
        )
        assert searched.status_code == 200, searched.text
        assert {item["id"] for item in searched.json()} == set(ids[1:])

        admin_id, _ = await case.create("admin", activate=False)
        pupil_id, _ = await case.create(activate=False)
        assert (
            await case.client.put(f"/api/v1/admin/users/{admin_id}/promotions/{promotion_id}")
        ).status_code == 422
        assert (
            await case.client.post(
                path,
                json={
                    "user_ids": [pupil_id, admin_id],
                },
            )
        ).status_code == 422
        assert (await case.client.get(path)).json()["total"] == 7
        assert (await case.client.get(f"/api/v1/admin/users/{pupil_id}/promotions")).json()[
            "total"
        ] == 0
        rejected = await case.client.post(
            "/api/v1/admin/users",
            json={
                "first_name": "Camille",
                "last_name": "Martin",
                "email": f"{case.prefix}-rejected@example.org",
                "roles": ["admin"],
                "promotion_ids": [promotion_id],
            },
        )
        assert rejected.status_code == 422
        # The failed creation must not reserve the email or leave a partial account.
        accepted = await case.client.post(
            "/api/v1/admin/users",
            json={
                "first_name": "Camille",
                "last_name": "Martin",
                "email": f"{case.prefix}-rejected@example.org",
                "roles": ["admin"],
            },
        )
        assert accepted.status_code == 201, accepted.text
        case.ids.append(accepted.json()["id"])
        async with case.database.sessions() as session:
            assert not list(
                await session.scalars(
                    select(ActivityEvent).where(
                        ActivityEvent.event_type == "promotion.member_added",
                        ActivityEvent.resource_id == promotion_id,
                        ActivityEvent.subject_user_id.in_([admin_id, pupil_id]),
                    )
                )
            )
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles", [["user"], ["teacher"], ["kholleur"], ["admin", "teacher", "kholleur"]]
)
async def test_promotion_candidates_exclude_members(auth_case: Harness, roles: list[str]) -> None:
    """Exclude current members before pagination/ranking while retaining other promotion members.

    Parameters
    ----------
    auth_case
        Authenticated administrator and isolated PostgreSQL identities.
    roles
        Pupil or combined teaching grants for candidate accounts.
    """
    case = auth_case
    promotion_id = await make_promotion(case, "TARGET")
    other_id = await make_promotion(case, "OTHER")
    ids = []
    category = "user" if roles == ["user"] else "teaching"
    try:
        for index in range(3):
            response = await case.client.post(
                "/api/v1/admin/users",
                json={
                    "first_name": "Camille",
                    "last_name": "Exclusion",
                    "email": f"{case.prefix}-exclude-{index}@example.org",
                    "roles": roles,
                    "promotion_ids": [promotion_id]
                    if index == 0
                    else [other_id]
                    if index == 1
                    else [],
                },
            )
            assert response.status_code == 201, response.text
            user_id = response.json()["id"]
            ids.append(user_id)
            case.ids.append(user_id)
        params = {"role": category, "exclude_promotion_id": promotion_id}
        for offset, expected_id in enumerate(ids[1:]):
            response = await case.client.get(
                "/api/v1/admin/users", params={**params, "limit": 1, "offset": offset}
            )
            assert response.status_code == 200, response.text
            assert response.json()["total"] == 2
            assert [item["id"] for item in response.json()["items"]] == [expected_id]
        for limit in [1, 20]:
            response = await case.client.get(
                "/api/v1/admin/users/search", params={**params, "q": "Exclusion", "limit": limit}
            )
            assert response.status_code == 200, response.text
            assert len(response.json()) == min(2, limit)
            assert {item["id"] for item in response.json()} <= set(ids[1:])
        link = f"/api/v1/admin/users/{ids[0]}/promotions/{promotion_id}"
        assert (await case.client.delete(link)).status_code == 204
        response = await case.client.get("/api/v1/admin/users", params=params)
        assert {item["id"] for item in response.json()["items"]} == set(ids)
        assert (await case.client.put(link)).status_code == 204
        response = await case.client.get(
            "/api/v1/admin/users/search", params={**params, "q": "Exclusion"}
        )
        assert {item["id"] for item in response.json()} == set(ids[1:])
        for root, query in [
            ("/api/v1/admin/users", {}),
            ("/api/v1/admin/users/search", {"q": "Exclusion"}),
        ]:
            for value, expected_status in [(0, 422), (9223372036854775807, 404)]:
                response = await case.client.get(
                    root, params={**query, "exclude_promotion_id": value}
                )
                assert response.status_code == expected_status, response.text
        await case.client.post("/api/v1/auth/logout")
        denied = await case.client.get("/api/v1/admin/users", params=params)
        assert denied.status_code == 401
    finally:
        await clear_promotions([promotion_id, other_id])


@pytest.mark.asyncio
async def test_losing_promotion_eligibility_removes_memberships_atomically(
    auth_case: Harness,
) -> None:
    """Remove active/archived memberships only on eligibility loss, with rollback and audit."""
    case = auth_case
    promotions = [await make_promotion(case, name) for name in ("ACTIVE", "ARCHIVED")]
    user_id, _ = await case.create("teacher", activate=False)
    try:
        for promotion_id in promotions:
            assert (
                await case.client.put(f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}")
            ).status_code == 204
        assert (
            await case.client.patch(
                f"/api/v1/admin/promotions/{promotions[1]}", json={"is_active": False}
            )
        ).status_code == 200
        path = f"/api/v1/admin/users/{user_id}/profile"
        for version, roles in enumerate(
            [
                ["admin", "teacher", "kholleur"],
                ["admin", "kholleur"],
                ["user"],
            ]
        ):
            response = await case.client.patch(
                path, json={"expected_version": version, "roles": roles}
            )
            assert response.status_code == 200, response.text
            assert len(response.json()["promotions"]) == 2
        email = (await case.client.get(f"/api/v1/admin/users/{case.administrator}")).json()["email"]
        rejected = await case.client.patch(
            path,
            json={
                "expected_version": 3,
                "roles": ["admin"],
                "email": email,
            },
        )
        assert rejected.status_code == 409
        current = (await case.client.get(path)).json()
        assert current["roles"] == ["user"] and len(current["promotions"]) == 2
        assert (
            await case.client.patch(
                path,
                json={
                    "expected_version": 2,
                    "roles": ["admin"],
                },
            )
        ).status_code == 409
        accepted = await case.client.patch(path, json={"expected_version": 3, "roles": ["admin"]})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["promotions"] == []
        assert accepted.json()["profile_version"] == 4
        async with case.database.sessions() as session:
            removed = list(
                await session.scalars(
                    select(ActivityEvent).where(
                        ActivityEvent.event_type == "promotion.member_removed",
                        ActivityEvent.subject_user_id == user_id,
                    )
                )
            )
            assert {item.resource_id for item in removed} == set(promotions)
            assert all(item.data == {"reason": "role_removed"} for item in removed)
            assert all(item.subject_role == "user" for item in removed)
        restored = await case.client.patch(
            path, json={"expected_version": 4, "roles": ["kholleur"]}
        )
        assert restored.status_code == 200 and restored.json()["promotions"] == []
    finally:
        await clear_promotions(promotions)


@pytest.mark.asyncio
async def test_promotion_student_blocks_preserve_independent_causes(auth_case: Harness) -> None:
    """Revoke sessions and restore only pupils free of manual and other promotion blocks."""
    case = auth_case
    promotions = [await make_promotion(case, label) for label in ("FIRST", "SECOND")]
    students = [await case.create() for _ in range(3)]
    pending, _ = await case.create(activate=False)
    staff = [await case.create(role) for role in ("teacher", "kholleur", "admin")]
    try:
        for promotion_id in promotions:
            for user_id in [item[0] for item in students + staff[:2]] + [pending]:
                response = await case.client.put(
                    f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}"
                )
                assert response.status_code == 204, response.text
        first = f"/api/v1/admin/promotions/{promotions[0]}"
        second = f"/api/v1/admin/promotions/{promotions[1]}"
        regular, manual_before, manual_after = [item[0] for item in students]
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{manual_before}/archive", json={"archived": True}
            )
        ).status_code == 204
        # Default archive keeps every account's previous state.
        assert (await case.client.patch(first, json={"is_active": False})).status_code == 200
        async with case.database.sessions() as session:
            assert (await session.get(User, regular)).status == "active"
        assert (await case.client.patch(first, json={"is_active": True})).status_code == 200
        assert (await case.client.patch(first, json={"archive_students": True})).status_code == 422
        assert (
            await case.client.patch(
                first,
                json={
                    "is_active": False,
                    "archive_students": True,
                },
            )
        ).status_code == 409
        assert (await case.client.get(first)).json()["is_active"] is True
        preview = (await case.client.get(first + "/archive-impact")).json()
        assert preview["student_count"] == 4 and preview["accounts_to_disable"] == 3
        logged = await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": students[0][1],
                "password": PASSWORD,
            },
        )
        assert logged.status_code == 200
        token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
        case.as_admin()
        archive = {"is_active": False, "archive_students": True, "acknowledge_student_impact": True}
        assert (await case.client.patch(first, json=archive)).status_code == 200
        case.client.cookies.clear()
        case.client.cookies.set(case.app.state.auth_settings.cookie_name, token)
        assert (await case.client.get("/api/v1/auth/me")).status_code == 401
        disabled = await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": students[0][1],
                "password": PASSWORD,
            },
        )
        unknown = await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": "missing-account",
                "password": PASSWORD,
            },
        )
        assert disabled.status_code == unknown.status_code == 401
        assert disabled.json() == unknown.json()
        case.as_admin()
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{regular}/archive", json={"archived": False}
            )
        ).status_code == 409
        assert (await case.client.patch(second, json=archive)).status_code == 200
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{manual_after}/archive", json={"archived": True}
            )
        ).status_code == 204
        # A later membership removal must not lose the recorded cause or restoration.
        assert (
            await case.client.delete(f"/api/v1/admin/users/{pending}/promotions/{promotions[0]}")
        ).status_code == 204
        assert (await case.client.patch(first, json={"is_active": True})).status_code == 409
        restore = {"is_active": True, "acknowledge_student_impact": True}
        assert (await case.client.patch(first, json=restore)).status_code == 200
        async with case.database.sessions() as session:
            assert (await session.get(User, regular)).status == "disabled"
            for user_id, _ in staff:
                assert (await session.get(User, user_id)).status == "active"
        preview = (await case.client.get(second + "/archive-impact")).json()
        assert preview["accounts_to_restore"] == 2
        assert preview["accounts_remaining_disabled"] == 2
        assert (await case.client.patch(second, json=restore)).status_code == 200
        async with case.database.sessions() as session:
            assert (await session.get(User, regular)).status == "active"
            assert (await session.get(User, pending)).status == "pending_activation"
            for user_id in (manual_before, manual_after):
                user = await session.get(User, user_id)
                assert user.status == "disabled" and user.manually_archived
            assert not list(await session.scalars(select(PromotionAccountBlock)))
        events = (
            await case.client.get("/api/v1/admin/events", params={"subject_user_id": regular})
        ).json()["items"]
        automatic = [event for event in events if event["event_type"] == "user.archived"]
        assert len(automatic) == 1
        assert automatic[0]["data"]["promotion_id"] == promotions[0]
        assert automatic[0]["data"]["promotion"]["identifier"] == "FIRST"
        case.client.cookies.clear()
        case.client.cookies.set(case.app.state.auth_settings.cookie_name, token)
        assert (await case.client.get("/api/v1/auth/me")).status_code == 401
        assert (
            await case.client.post(
                "/api/v1/auth/login",
                json={
                    "identifier": students[0][1],
                    "password": PASSWORD,
                },
            )
        ).status_code == 200
    finally:
        await clear_promotions(promotions)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "teacher", "kholleur"])
async def test_promotion_impact_and_team_are_admin_only(auth_case: Harness, role: str) -> None:
    """Deny staff directory and account archival previews to every non-admin role."""
    case = auth_case
    _, username = await case.create(role)
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": PASSWORD,
            },
        )
    ).status_code == 200
    for path in ("/api/v1/admin/team", "/api/v1/admin/promotions/1/archive-impact"):
        assert (await case.client.get(path)).status_code == 403


@pytest.mark.asyncio
async def test_atomic_creation_and_immutable_username(auth_case: Harness) -> None:
    """Create roles/memberships/events atomically and never accept a caller-chosen username."""
    case = auth_case
    promotion_id = await make_promotion(case)
    try:
        body = dict(
            first_name="Valentin",
            last_name="Rémi",
            email="atomic@example.org",
            roles=["teacher", "admin"],
            promotion_ids=[promotion_id],
        )
        response = await case.client.post("/api/v1/admin/users", json=body)
        assert response.status_code == 201, response.text
        user = response.json()
        case.ids.append(user["id"])
        assert isinstance(user["id"], int) and user["id"] > 0
        assert user["username"].startswith("vremi") and 100 <= int(user["username"][-3:]) <= 999
        assert {"teacher.access", "users.manage"} <= set(user["permissions"])
        before = (await case.client.get("/api/v1/admin/users")).json()["total"]
        for changes, expected in (
            ({"username": "chosen123"}, 422),
            ({"roles": ["user", "admin"]}, 422),
            ({"promotion_ids": [9223372036854775807], "email": "invalid-promo@example.org"}, 422),
            ({}, 409),
        ):
            assert (
                await case.client.post("/api/v1/admin/users", json=body | changes)
            ).status_code == expected
        assert (await case.client.get("/api/v1/admin/users")).json()["total"] == before
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{user['id']}", json={"username": "changed103"}
            )
        ).status_code == 405
        async with case.database.sessions() as session:
            stored = await session.get(User, user["id"])
            for field in ("username", "first_name", "last_name", "email"):
                encrypted = getattr(stored, field + "_encrypted")
                assert user[field].encode() not in encrypted
                assert (
                    case.app.state.identity_cipher.decrypt(stored.id, field, encrypted)
                    == user[field]
                )
            assert await session.get(UserPromotion, (stored.id, promotion_id)) is not None
        page = await case.client.get("/api/v1/admin/events?event_type=user.created&limit=1")
        assert page.status_code == 200 and page.json()["next_cursor"] is not None
        following = await case.client.get(
            "/api/v1/admin/events",
            params={
                "event_type": "user.created",
                "limit": 1,
                "cursor": page.json()["next_cursor"],
            },
        )
        assert following.json()["items"][0]["id"] < page.json()["items"][0]["id"]
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_search_filters_and_permissions(auth_case: Harness) -> None:
    """Expose identities only to administrators and enforce permission independence from roles."""
    case = auth_case
    assert "teacher.access" not in (await case.client.get("/api/v1/auth/me")).json()["permissions"]
    assert (await case.client.get("/api/v1/test/teacher")).status_code == 403
    user_id, username = await case.create("teacher")
    assert (
        await case.client.get("/api/v1/admin/users/search?q=valentin%20burgo&role=teacher")
    ).json()[0]["id"] == user_id
    assert (await case.client.get("/api/v1/admin/users/search?q=v")).status_code == 422
    assert (await case.client.get("/api/v1/admin/users/search?q=zzzzzzzz")).json() == []
    assert (await case.client.get("/api/v1/admin/users/search?q=val&limit=21")).status_code == 422
    assert (await case.client.get("/api/v1/admin/users?role=teacher")).json()["total"] == 1
    assert (await case.client.get("/api/v1/admin/users/9223372036854775807")).status_code == 404
    assert (
        await case.client.get("/api/v1/admin/events?since=2026-01-01T00:00:00")
    ).status_code == 422
    await case.client.post(
        "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
    )
    for path in ("users", "users/search?q=val", "promotions", "events"):
        assert (await case.client.get("/api/v1/admin/" + path)).status_code == 403
    case.client.cookies.clear()
    assert (await case.client.get("/api/v1/admin/users/search?q=val")).status_code == 401


@pytest.mark.asyncio
async def test_database_role_constraints_and_journal_permissions(auth_case: Harness) -> None:
    """Deny incompatible role assignments and destructive runtime journal/catalogue writes."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    async with case.database.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                role_id = await session.scalar(select(Role.id).where(Role.code == "teacher"))
                session.add(UserRole(user_id=user_id, role_id=role_id))
    staff_id, _ = await case.create("teacher", activate=False)
    async with case.database.sessions.begin() as session:
        for code in ("kholleur", "admin"):
            role_id = await session.scalar(select(Role.id).where(Role.code == code))
            session.add(UserRole(user_id=staff_id, role_id=role_id))
    async with case.database.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                role_id = await session.scalar(select(Role.id).where(Role.code == "user"))
                session.add(UserRole(user_id=staff_id, role_id=role_id))
    # The exclusive pupil role must also reject the newly combinable kholleur role.
    async with case.database.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                role_id = await session.scalar(select(Role.id).where(Role.code == "kholleur"))
                session.add(UserRole(user_id=user_id, role_id=role_id))
    for statement in (
        "DELETE FROM sophikron.activity_events",
        "UPDATE sophikron.activity_events SET data = '{}'",
        "DELETE FROM sophikron.promotions",
        "DELETE FROM sophikron.role_permissions",
    ):
        async with case.database.sessions() as session:
            with pytest.raises(DBAPIError) as error:
                async with session.begin():
                    await session.execute(text(statement))
            assert error.value.orig.sqlstate == "42501"


@pytest.mark.asyncio
async def test_journal_failure_rolls_back_operation(auth_case: Harness) -> None:
    """Never commit a business mutation when its audit fact cannot be staged."""
    case = auth_case
    with patch("app.services.administration.record_event", side_effect=RuntimeError("synthetic")):
        with pytest.raises(RuntimeError, match="synthetic"):
            await case.client.post(
                "/api/v1/admin/promotions",
                json={
                    "year": 2026,
                    "identifier": "ROLLBACK",
                    "color": "#123456",
                },
            )
    async with case.database.sessions() as session:
        assert (
            await session.scalar(select(Promotion).where(Promotion.identifier == "ROLLBACK"))
            is None
        )


@pytest.mark.asyncio
async def test_parallel_membership_is_idempotent(auth_case: Harness) -> None:
    """Serialize concurrent memberships and emit exactly one addition event."""
    case = auth_case
    promotion_id = await make_promotion(case)
    try:
        user_id, _ = await case.create(activate=False)
        path = f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}"
        responses = await asyncio.gather(*(case.client.put(path) for _ in range(3)))
        assert [response.status_code for response in responses] == [204, 204, 204]
        async with case.database.sessions() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ActivityEvent)
                    .where(
                        ActivityEvent.subject_user_id == user_id,
                        ActivityEvent.event_type == "promotion.member_added",
                    )
                )
                == 1
            )
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_interactive_search_representative_volumes(auth_case: Harness) -> None:
    """Measure complete ASGI searches over encrypted PostgreSQL identities with three callers."""
    case = auth_case
    promotion_id = await make_promotion(case, "SEARCH-BENCHMARK")
    cipher = case.app.state.identity_cipher
    try:
        for count in (2000, 8000):
            async with case.database.sessions.begin() as session:
                ids = list(
                    (
                        await session.scalars(
                            text(
                                "SELECT nextval(pg_get_serial_sequence('sophikron.users', 'id')) "
                                "FROM generate_series(1, :count)"
                            ),
                            {"count": count},
                        )
                    ).all()
                )
                records = []
                for index, user_id in enumerate(ids):
                    username = f"benchmark{user_id}"
                    email = f"{username}@example.org"
                    first, last = (
                        ("Valentin", "Burgaud") if index % 10 == 0 else ("Alice", "Martin")
                    )
                    records.append(
                        dict(
                            id=user_id,
                            first_name_encrypted=cipher.encrypt(user_id, "first_name", first),
                            last_name_encrypted=cipher.encrypt(user_id, "last_name", last),
                            username_encrypted=cipher.encrypt(user_id, "username", username),
                            email_encrypted=cipher.encrypt(user_id, "email", email),
                            username_lookup=cipher.lookup("username", username),
                            email_lookup=cipher.lookup("email", email),
                        )
                    )
                await session.execute(insert(User), records)
                role_id = await session.scalar(select(Role.id).where(Role.code == "user"))
                await session.execute(
                    insert(UserRole), [dict(user_id=item, role_id=role_id) for item in ids]
                )
                await session.execute(
                    insert(UserPromotion),
                    [dict(user_id=item, promotion_id=promotion_id) for item in ids],
                )
            case.ids.extend(ids)

            async def timed_search() -> float:
                """Measure full authenticated query, database loading, decryption and ranking."""
                start = perf_counter()
                response = await case.client.get(
                    "/api/v1/admin/users/search",
                    params={
                        "q": "valentin burgo",
                        "promotion_id": promotion_id,
                    },
                )
                elapsed = perf_counter() - start
                assert response.status_code == 200 and len(response.json()) == 20
                assert all(item["last_name"] == "Burgaud" for item in response.json())
                return elapsed

            await timed_search()
            samples = []
            for _ in range(4):
                samples.extend(await asyncio.gather(*(timed_search() for _ in range(3))))
            p95 = sorted(samples)[ceil(len(samples) * 0.95) - 1]
            volume = 2000 if count == 2000 else 10000
            print(
                f"Search benchmark: {volume} accounts, 3 concurrent callers, "
                f"p95={p95 * 1000:.1f} ms"
            )
            # A broad regression ceiling avoids turning a hardware-specific target into flaky CI.
            assert p95 < 2, "Interactive search exceeded the two-second regression ceiling"
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_parallel_username_generation(auth_case: Harness) -> None:
    """Create distinct usernames for identical names through concurrent requests."""
    case = auth_case
    responses = await asyncio.gather(
        *(
            case.client.post(
                "/api/v1/admin/users",
                json={
                    "first_name": "Dionis",
                    "last_name": "DU SEJOUR",
                    "email": f"collision{index}@example.org",
                    "roles": ["user"],
                },
            )
            for index in range(3)
        )
    )
    for response in responses:
        assert response.status_code == 201, response.text
        case.ids.append(response.json()["id"])
    names = [response.json()["username"] for response in responses]
    assert len(set(names)) == 3 and all(name.startswith("dduse") for name in names)


@pytest.mark.asyncio
async def test_cached_search_observes_current_identity_and_filters(auth_case: Harness) -> None:
    """Warm cache entries cannot resurrect removed memberships or stale encrypted names."""
    case = auth_case
    promotion_id = await make_promotion(case)
    try:
        user_id, _ = await case.create(activate=False)
        membership = f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}"
        await case.client.put(membership)
        params = {"q": "burgaud", "promotion_id": promotion_id}
        assert (await case.client.get("/api/v1/admin/users/search", params=params)).json()[0][
            "id"
        ] == user_id
        async with case.database.sessions.begin() as session:
            user = await session.get(User, user_id)
            user.last_name_encrypted = case.app.state.identity_cipher.encrypt(
                user_id, "last_name", "Martin"
            )
        assert (await case.client.get("/api/v1/admin/users/search", params=params)).json() == []
        params["q"] = "martin"
        assert (await case.client.get("/api/v1/admin/users/search", params=params)).json()[0][
            "last_name"
        ] == "Martin"
        await case.client.delete(membership)
        assert (await case.client.get("/api/v1/admin/users/search", params=params)).json() == []
    finally:
        await clear_promotions([promotion_id])
