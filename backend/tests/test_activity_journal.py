"""Historical participant roles, immutable resources and bounded journal navigation."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError

from app.models import ActivityEvent
from app.services.activity import EVENTS, DownloadFacts, EventDefinition, event_family, highest_role
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

integration = pytest.mark.skipif(
    os.environ.get("DB_INTEGRATION") != "1", reason="PostgreSQL required"
)


@pytest.mark.parametrize(
    "roles,expected",
    [
        ([], None),
        (["user"], "user"),
        (["teacher"], "teacher"),
        (["teacher", "admin"], "admin"),
        (["unknown"], None),
    ],
)
def test_highest_historical_role(roles: list[str], expected: str | None) -> None:
    """Resolve priority without attributing student access to unknown/system accounts."""
    assert highest_role(iter(roles)) == expected


def test_event_message_rejects_arbitrary_template_fields() -> None:
    """Reject arbitrary attributes, conversions and formatting in catalogue templates."""
    for message in ["{actor.password}", "{actor!r}", "{actor:20}"]:
        with pytest.raises(ValueError):
            EventDefinition(message=message)


def test_catalogue_families_and_download_title() -> None:
    """Cover every registered event with four families and accept historical downloads."""
    assert {event_family(code) for code in EVENTS} == {
        "accounts",
        "promotions",
        "lessons",
        "administration",
    }
    assert event_family("auth.login_succeeded") == "accounts"
    assert event_family("promotion.custom_group_created") == "promotions"
    assert event_family("lesson.file_downloaded") == "lessons"
    assert event_family("timetable.created") == "administration"
    assert DownloadFacts(file_id=1, size_bytes=12).document_title is None
    assert (
        DownloadFacts(file_id=1, size_bytes=12, document_title="Exercices").document_title
        == "Exercices"
    )
    with pytest.raises(ValueError):
        DownloadFacts(file_id=1, size_bytes=12, storage_key="private")


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_participant_family_filters_archives_and_cursor_scope(auth_case: Harness) -> None:
    """Include author and target once, preserve archives, and bind cursors to every filter."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    other_id, _ = await case.create(activate=False)
    await case.client.patch(f"/api/v1/admin/users/{user_id}/archive", json={"archived": True})
    stamp = datetime.now(UTC)
    expected = []
    async with case.database.sessions.begin() as session:
        for index, (author, target, code) in enumerate(
            [
                (user_id, other_id, "user.profile_updated"),
                (other_id, user_id, "user.profile_updated"),
                (user_id, user_id, "auth.login_succeeded"),
                (other_id, other_id, "user.profile_updated"),
                (user_id, None, "timetable.created"),
            ]
        ):
            row = ActivityEvent(
                event_type=code,
                actor_user_id=author,
                subject_user_id=target,
                occurred_at=stamp + timedelta(seconds=index),
                data={},
            )
            session.add(row)
            await session.flush()
            if index < 3:
                expected.append(row.id)
    params = {"user_id": user_id, "family": "accounts", "since": stamp.isoformat(), "limit": 2}
    result = await case.client.get("/api/v1/admin/events", params=params)
    assert result.status_code == 200, result.text
    page = result.json()
    assert [row["id"] for row in page["items"]] == expected[::-1][:2]
    assert all(row["subject_profile_available"] for row in page["items"])
    cursor = page["next_cursor"]
    assert cursor
    last = await case.client.get("/api/v1/admin/events", params=params | {"cursor": cursor})
    assert [row["id"] for row in last.json()["items"]] == expected[:1]
    for changed in ({"user_id": other_id}, {"family": "lessons"}):
        assert (
            await case.client.get(
                "/api/v1/admin/events", params=params | changed | {"cursor": cursor}
            )
        ).status_code == 422
    all_families = await case.client.get(
        "/api/v1/admin/events", params={"user_id": user_id, "since": stamp.isoformat(), "limit": 5}
    )
    assert len(all_families.json()["items"]) == 4
    for invalid in ({"family": "unknown"}, {"user_id": 0}):
        assert (await case.client.get("/api/v1/admin/events", params=invalid)).status_code == 422
    for role in ("teacher", "user"):
        _, username = await case.create(role)
        await case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
        )
        assert (
            await case.client.get("/api/v1/admin/events", params={"user_id": user_id})
        ).status_code == 403
        case.as_admin()


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_catalogue_is_dynamic_and_administrator_only(
    auth_case: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose newly registered types with no journal entries while retaining authorization."""
    case = auth_case
    monkeypatch.setitem(
        EVENTS,
        "test.completed",
        EventDefinition(
            subject=True, label="Tests terminés", message="{subject} a terminé un test."
        ),
    )
    response = await case.client.get("/api/v1/admin/events/types")
    assert response.status_code == 200
    assert (
        next(item for item in response.json() if item["code"] == "test.completed")["label"]
        == "Tests terminés"
    )
    for role in ["teacher", "user"]:
        _, username = await case.create(role)
        await case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
        )
        assert (await case.client.get("/api/v1/admin/events/types")).status_code == 403
    case.client.cookies.clear()
    assert (await case.client.get("/api/v1/admin/events/types")).status_code == 401


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_historical_roles_survive_later_changes(auth_case: Harness) -> None:
    """Keep the author's old role and target's before-role while resolving current names."""
    case = auth_case
    staff_id, staff = await case.create("admin")
    user_id, _ = await case.create()
    await case.client.post("/api/v1/auth/login", json={"identifier": staff, "password": PASSWORD})
    path = f"/api/v1/admin/users/{user_id}/profile"
    response = await case.client.patch(path, json={"expected_version": 0, "roles": ["teacher"]})
    assert response.status_code == 200, response.text
    case.as_admin()
    assert (
        await case.client.patch(
            f"/api/v1/admin/users/{staff_id}/profile",
            json={"expected_version": 0, "roles": ["teacher"]},
        )
    ).status_code == 200
    assert (
        await case.client.patch(
            path, json={"expected_version": 1, "roles": ["admin"], "first_name": "Marie"}
        )
    ).status_code == 200
    result = await case.client.get(
        "/api/v1/admin/events",
        params={"event_type": "user.roles_updated", "actor_user_id": staff_id},
    )
    entry = result.json()["items"][0]
    assert entry["actor_user_id"] == staff_id and entry["actor_role"] == "admin"
    assert entry["subject_user_id"] == user_id and entry["subject_role"] == "user"
    assert entry["subject_label"] == "Marie Burgaud"
    assert entry["data"] == {"previous_roles": ["user"], "roles": ["teacher"]}
    assert entry["actor_profile_available"] and entry["subject_profile_available"]


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_promotion_snapshot_and_explicit_changes(auth_case: Harness) -> None:
    """Preserve original resource tags and record useful before/after promotion metadata."""
    case = auth_case
    promotion_id = await make_promotion(case, "HISTORY")
    try:
        before = (await case.client.get(f"/api/v1/admin/promotions/{promotion_id}")).json()
        response = await case.client.patch(
            f"/api/v1/admin/promotions/{promotion_id}",
            json={"identifier": "RENAMED", "color": "#123456"},
        )
        assert response.status_code == 200
        result = (
            await case.client.get(
                "/api/v1/admin/events",
                params={"resource_type": "promotion", "resource_id": promotion_id},
            )
        ).json()["items"]
        created = next(item for item in result if item["event_type"] == "promotion.created")
        updated = next(item for item in result if item["event_type"] == "promotion.updated")
        assert created["promotion_snapshot"] == {
            field: before[field] for field in ("identifier", "year", "color")
        }
        assert updated["promotion_snapshot"]["identifier"] == "RENAMED"
        assert updated["data"]["previous"]["identifier"] == before["identifier"]
        assert updated["data"]["current"]["color"] == "#123456"
        assert updated["data"]["changed_fields"] == ["color", "identifier"]
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_journal_pages_both_orders_and_bound_cursors(auth_case: Harness) -> None:
    """Page through timestamp ties without duplicates, counts or unbounded related queries."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    start = datetime.now(UTC)
    async with case.database.sessions.begin() as session:
        session.add_all(
            [
                ActivityEvent(
                    event_type="test.pagination",
                    actor_user_id=case.administrator,
                    subject_user_id=user_id,
                    actor_role="admin",
                    subject_role="user",
                    occurred_at=start + timedelta(seconds=index // 3),
                    data={},
                )
                for index in range(35)
            ]
        )
    collected = {}
    for order in ["asc", "desc"]:
        ids, sizes = [], []
        cursor = None
        while True:
            params = {"event_type": "test.pagination", "order": order, "limit": 15}
            if cursor:
                params["cursor"] = cursor
            response = await case.client.get("/api/v1/admin/events", params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            ids.extend(item["id"] for item in page["items"])
            assert len(ids) <= 35
            sizes.append(len(page["items"]))
            cursor = page["next_cursor"]
            if not cursor:
                break
            assert (
                await case.client.get(
                    "/api/v1/admin/events",
                    params=params
                    | {"cursor": cursor, "order": "desc" if order == "asc" else "asc"},
                )
            ).status_code == 422
            assert (
                await case.client.get(
                    "/api/v1/admin/events",
                    params=params | {"cursor": cursor, "event_type": "user.created"},
                )
            ).status_code == 422
        assert sizes == [15, 15, 5] and len(set(ids)) == 35
        collected[order] = ids
    assert collected["desc"] == list(reversed(collected["asc"]))
    statements: list[str] = []

    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        """Observe real SQL to guard bounded reads and grouped participant resolution."""
        statements.append(statement)

    engine = case.app.state.database.engine.sync_engine
    sqlalchemy_event.listen(engine, "before_cursor_execute", capture)
    try:
        assert (
            await case.client.get(
                "/api/v1/admin/events", params={"event_type": "test.pagination", "limit": 15}
            )
        ).status_code == 200
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", capture)
    journal_queries = [
        statement for statement in statements if "FROM sophikron.activity_events" in statement
    ]
    assert len(journal_queries) == 1 and "LIMIT" in journal_queries[0]
    assert "count(" not in journal_queries[0].lower() and "OFFSET" not in journal_queries[0]
    assert not any("FROM sophikron.promotions" in statement for statement in statements)
    assert (
        len(
            [
                statement
                for statement in statements
                if "users.first_name_encrypted" in statement and " IN (" in statement
            ]
        )
        == 1
    )
    for query in ["order=invalid", "limit=0", "limit=101", "cursor=garbage"]:
        assert (await case.client.get("/api/v1/admin/events?" + query)).status_code == 422


@pytest.mark.integration
@integration
@pytest.mark.asyncio
async def test_snapshot_constraints(auth_case: Harness) -> None:
    """Reject invalid stored historical role codes through PostgreSQL constraints."""
    case = auth_case
    async with case.database.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    ActivityEvent(
                        event_type="test.invalid",
                        actor_user_id=case.administrator,
                        actor_role="owner",
                        data={},
                    )
                )
