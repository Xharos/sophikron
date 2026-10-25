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
from app.models import ActivityEvent, Promotion, Role, User, UserPromotion, UserRole
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
        for role in ("user", "teacher", "admin"):
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
