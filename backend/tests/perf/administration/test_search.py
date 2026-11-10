"""Encrypted PostgreSQL search latency at representative volumes."""

import asyncio
import os
from math import ceil
from time import perf_counter

import pytest
from sqlalchemy import insert, select, text

from app.models import Role, User, UserPromotion, UserRole
from tests.support.administration import clear_promotions, make_promotion
from tests.support.authentication import Harness

pytestmark = [
    pytest.mark.perf,
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Disposable PostgreSQL required"
    ),
]


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
