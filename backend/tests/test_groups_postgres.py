"""Real group API transactions, scope, lifecycle changes and foreign-key constraints."""

import asyncio
import copy
import os

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.models import PromotionGroupMember
from tests.test_auth_postgres import PASSWORD, Harness
from tests.test_dashboard_postgres import clear_promotions, make_promotion

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]


async def create_roster(case: Harness, promotion_id: int, count: int = 7) -> list[int]:
    """Create synthetic pending pupils and attach them through the real administration API."""
    pupils = []
    for _ in range(count):
        pupil, _ = await case.create(activate=False)
        pupils.append(pupil)
    response = await case.client.post(
        f"/api/v1/admin/promotions/{promotion_id}/users", json={"user_ids": pupils}
    )
    assert response.status_code == 204, response.text
    return pupils


async def preview_and_save(case: Harness, path: str, pupils: list[int], kind: str) -> dict:
    """Save one server-generated draft and return its complete revisioned representation."""
    body = {"expected_revision": None, "roster_ids": pupils}
    preview = await case.client.post(f"{path}/{kind}/preview", json=body)
    assert preview.status_code == 200, preview.text
    response = await case.client.put(f"{path}/{kind}", json={**body, "groups": preview.json()})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_archive_counts_preservation_regeneration_and_reactivation(
    auth_case: Harness,
) -> None:
    """Preserve archived links, exclude their sizes and reject stale status snapshots."""
    case = auth_case
    promotion_id = await make_promotion(case, "ARCHIVES")
    path = f"/api/v1/promotion-groups/{promotion_id}"
    try:
        pupils = await create_roster(case, promotion_id)
        saved = {
            kind: await preview_and_save(case, path, pupils, kind)
            for kind in ("halves", "thirds", "kholles")
        }
        archived_id = saved["kholles"]["groups"][-1]["student_ids"][0]
        original_groups = {
            kind: next(
                group["number"]
                for group in partition["groups"]
                if archived_id in group["student_ids"]
            )
            for kind, partition in saved.items()
        }
        teacher, _ = await case.create("teacher", activate=False)
        combined, _ = await case.create("kholleur", activate=False)
        response = await case.client.patch(
            f"/api/v1/admin/users/{combined}/profile",
            json={
                "expected_version": 0,
                "roles": ["teacher", "kholleur"],
            },
        )
        assert response.status_code == 200, response.text
        assert (
            await case.client.post(
                f"/api/v1/admin/promotions/{promotion_id}/users",
                json={"user_ids": [teacher, combined]},
            )
        ).status_code == 204
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{archived_id}/archive", json={"archived": True}
            )
        ).status_code == 204
        metadata = (await case.client.get(f"/api/v1/admin/promotions/{promotion_id}")).json()
        assert (
            metadata["non_archived_student_count"],
            metadata["teaching_count"],
            metadata["archived_count"],
        ) == (6, 2, 1)
        assert metadata["member_count"] == 9 and metadata["student_count"] == 7
        board = (await case.client.get(path)).json()
        assert (
            next(pupil for pupil in board["students"] if pupil["id"] == archived_id)["status"]
            == "disabled"
        )
        assert {item["kind"]: item for item in board["partitions"]} == saved
        stale = {
            "expected_revision": saved["kholles"]["revision"],
            "roster_ids": pupils,
            "groups": saved["kholles"]["groups"],
        }
        assert (await case.client.put(f"{path}/kholles", json=stale)).status_code == 409
        assert (
            await case.client.post(
                f"{path}/kholles/preview",
                json={
                    "expected_revision": saved["kholles"]["revision"],
                    "roster_ids": pupils,
                    "archived_ids": [],
                },
            )
        ).status_code == 409
        for kind in saved:
            body = {
                "expected_revision": saved[kind]["revision"],
                "roster_ids": pupils,
                "archived_ids": [archived_id],
            }
            response = await case.client.post(f"{path}/{kind}/preview", json=body)
            assert response.status_code == 200, response.text
            groups = response.json()
            assert (
                next(group["number"] for group in groups if archived_id in group["student_ids"])
                == original_groups[kind]
            )
            sizes = [
                sum(pupil != archived_id for pupil in group["student_ids"]) for group in groups
            ]
            if kind == "kholles":
                assert sorted(sizes) == [0, 3, 3]
            else:
                assert max(sizes) - min(sizes) <= 1
            response = await case.client.put(f"{path}/{kind}", json={**body, "groups": groups})
            assert response.status_code == 200, response.text
            saved[kind] = response.json()
        # Archived pupils remain manually movable; an archived-only group is not a size error.
        groups = copy.deepcopy(saved["kholles"]["groups"])
        source = next(group for group in groups if archived_id in group["student_ids"])
        source["student_ids"].remove(archived_id)
        groups[0]["student_ids"].append(archived_id)
        groups = [group for group in groups if group["student_ids"]]
        body = {
            "expected_revision": saved["kholles"]["revision"],
            "roster_ids": pupils,
            "archived_ids": [archived_id],
            "groups": groups,
        }
        response = await case.client.put(f"{path}/kholles", json=body)
        assert response.status_code == 200, response.text
        body["expected_revision"] = response.json()["revision"]
        retained_number = next(
            group["number"] for group in groups if archived_id in group["student_ids"]
        )
        # Archived staff are also excluded from the unique teaching-account counter.
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{teacher}/archive", json={"archived": True}
            )
        ).status_code == 204
        metadata = (await case.client.get(f"/api/v1/admin/promotions/{promotion_id}")).json()
        assert (
            metadata["non_archived_student_count"],
            metadata["teaching_count"],
            metadata["archived_count"],
        ) == (6, 1, 2)
        assert (
            await case.client.patch(
                f"/api/v1/admin/users/{archived_id}/archive", json={"archived": False}
            )
        ).status_code == 204
        metadata = (await case.client.get(f"/api/v1/admin/promotions/{promotion_id}")).json()
        assert (
            metadata["non_archived_student_count"],
            metadata["teaching_count"],
            metadata["archived_count"],
        ) == (7, 1, 1)
        board = (await case.client.get(path)).json()
        partition = next(
            partition for partition in board["partitions"] if partition["kind"] == "kholles"
        )
        assert (
            next(
                group["number"]
                for group in partition["groups"]
                if archived_id in group["student_ids"]
            )
            == retained_number
        )
        assert (await case.client.put(f"{path}/kholles", json=body)).status_code == 409
        assert (
            await case.client.put(f"{path}/kholles", json={**body, "archived_ids": []})
        ).status_code == 422
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_all_archived_promotion_can_generate_and_save(auth_case: Harness) -> None:
    """Preserve memberships and allow editing groups when all pupils are archived."""
    case = auth_case
    promotion_id = await make_promotion(case, "TOUS_ARCHIVES")
    path = f"/api/v1/promotion-groups/{promotion_id}"
    try:
        pupils = await create_roster(case, promotion_id, 2)
        for pupil in pupils:
            assert (
                await case.client.patch(
                    f"/api/v1/admin/users/{pupil}/archive", json={"archived": True}
                )
            ).status_code == 204
        for kind in ("halves", "thirds", "kholles"):
            body = {"expected_revision": None, "roster_ids": pupils, "archived_ids": pupils}
            response = await case.client.post(f"{path}/{kind}/preview", json=body)
            assert response.status_code == 200, response.text
            assert (
                await case.client.put(f"{path}/{kind}", json={**body, "groups": response.json()})
            ).status_code == 200
        metadata = (await case.client.get(f"/api/v1/admin/promotions/{promotion_id}")).json()
        assert metadata["non_archived_student_count"] == 0 and metadata["archived_count"] == 2
        assert metadata["student_count"] == 2 and metadata["member_count"] == 2
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_directory_and_profiles_scope_saved_group_tags(auth_case: Harness) -> None:
    """Expose saved tags in lists, searches and details without leaking unshared promotions."""
    case = auth_case
    shared = await make_promotion(case, "PARTAGEE")
    hidden = await make_promotion(case, "PRIVEE")
    try:
        pupils = await create_roster(case, shared, 6)
        assert (
            await case.client.post(
                f"/api/v1/admin/promotions/{hidden}/users", json={"user_ids": pupils}
            )
        ).status_code == 204
        expected = []
        saved = {}
        for promotion_id in (shared, hidden):
            for kind in ("halves", "thirds", "kholles"):
                partition = await preview_and_save(
                    case, f"/api/v1/promotion-groups/{promotion_id}", pupils, kind
                )
                saved[promotion_id, kind] = partition
                group = next(
                    group for group in partition["groups"] if pupils[0] in group["student_ids"]
                )
                expected.append(
                    {"promotion_id": promotion_id, "kind": kind, "number": group["number"]}
                )

        def tags(response: dict) -> set[tuple[int, str, int]]:
            """Compare only saved group identifiers independently of response ordering."""
            return {
                (tag["promotion_id"], tag["kind"], tag["number"])
                for tag in response["group_assignments"]
            }

        all_tags = tags({"group_assignments": expected})
        shared_tags = {tag for tag in all_tags if tag[0] == shared}
        for suffix in ("", "/profile"):
            response = await case.client.get(f"/api/v1/admin/users/{pupils[0]}{suffix}")
            assert response.status_code == 200, response.text
            assert tags(response.json()) == all_tags
        for path in (
            f"/api/v1/admin/users?promotion_id={shared}",
            f"/api/v1/admin/users/search?q=Valentin&promotion_id={shared}",
        ):
            response = (await case.client.get(path)).json()
            items = response if isinstance(response, list) else response["items"]
            assert tags(next(item for item in items if item["id"] == pupils[0])) == shared_tags
        global_items = (await case.client.get("/api/v1/admin/users")).json()["items"]
        assert tags(next(item for item in global_items if item["id"] == pupils[0])) == all_tags

        teacher_id, teacher = await case.create("teacher")
        assert (
            await case.client.put(f"/api/v1/admin/users/{teacher_id}/promotions/{shared}")
        ).status_code == 204
        assert (
            await case.client.post(
                "/api/v1/auth/login", json={"identifier": teacher, "password": PASSWORD}
            )
        ).status_code == 200
        for suffix in ("", "/profile"):
            response = await case.client.get(f"/api/v1/teaching/users/{pupils[0]}{suffix}")
            assert response.status_code == 200, response.text
            assert tags(response.json()) == shared_tags
            assert {promotion["id"] for promotion in response.json()["promotions"]} == {shared}
        for path in (
            "/api/v1/teaching/users",
            f"/api/v1/teaching/users?promotion_id={shared}",
            "/api/v1/teaching/users/search?q=Valentin",
            f"/api/v1/teaching/users/search?q=Valentin&promotion_id={shared}",
        ):
            response = (await case.client.get(path)).json()
            items = response if isinstance(response, list) else response["items"]
            assert tags(next(item for item in items if item["id"] == pupils[0])) == shared_tags
        assert (
            await case.client.get(f"/api/v1/teaching/users?promotion_id={hidden}")
        ).status_code == 404

        # Removing a partition immediately removes its tags on every subsequent read.
        case.as_admin()
        assert (
            await case.client.request(
                "DELETE",
                f"/api/v1/promotion-groups/{shared}/halves",
                json={"expected_revision": saved[shared, "halves"]["revision"]},
            )
        ).status_code == 204
        response = (await case.client.get(f"/api/v1/admin/users/{pupils[0]}/profile")).json()
        assert tags(response) == {tag for tag in all_tags if tag[:2] != (shared, "halves")}
        # A pupil becoming staff keeps promotion membership but must not retain pupil group tags.
        response = await case.client.patch(
            f"/api/v1/admin/users/{pupils[0]}/profile",
            json={"expected_version": response["profile_version"], "roles": ["teacher"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["group_assignments"] == []
        assert (await case.client.get(f"/api/v1/admin/users/{pupils[0]}")).json()[
            "group_assignments"
        ] == []
        # Revoking the reader's promotion membership also revokes both detail routes.
        assert (
            await case.client.delete(f"/api/v1/admin/users/{teacher_id}/promotions/{shared}")
        ).status_code == 204
        assert (
            await case.client.post(
                "/api/v1/auth/login", json={"identifier": teacher, "password": PASSWORD}
            )
        ).status_code == 200
        for suffix in ("", "/profile"):
            assert (
                await case.client.get(f"/api/v1/teaching/users/{pupils[1]}{suffix}")
            ).status_code == 404
    finally:
        await clear_promotions([shared, hidden])


@pytest.mark.asyncio
async def test_partition_atomicity_independence_and_roster_changes(auth_case: Harness) -> None:
    """Protect saved partitions against stale edits and preserve independent partitions."""
    case = auth_case
    promotion_id = await make_promotion(case)
    path = f"/api/v1/promotion-groups/{promotion_id}"
    try:
        pupils = await create_roster(case, promotion_id)
        body = {"expected_revision": None, "roster_ids": pupils}
        assert (await case.client.post(f"{path}/halves/preview", json=body)).status_code == 200
        assert (await case.client.get(path)).json()["partitions"] == []
        halves = await preview_and_save(case, path, pupils, "halves")
        thirds = await preview_and_save(case, path, pupils, "thirds")
        kholles = await preview_and_save(case, path, pupils, "kholles")
        baseline = (await case.client.get(path)).json()
        assert len(baseline["students"]) == 7
        assert set(baseline["students"][0]) == {"id", "first_name", "last_name", "status"}
        edited = {
            **body,
            "expected_revision": halves["revision"],
            "groups": copy.deepcopy(halves["groups"]),
        }
        edited["groups"][0]["x"] += 50
        replies = await asyncio.gather(
            *[case.client.put(f"{path}/halves", json=edited) for _ in range(2)]
        )
        assert sorted(reply.status_code for reply in replies) == [200, 409]
        current = next(reply.json() for reply in replies if reply.status_code == 200)
        invalid = {
            **body,
            "expected_revision": current["revision"],
            "groups": copy.deepcopy(current["groups"]),
        }
        invalid["groups"][0]["student_ids"] += invalid["groups"][1]["student_ids"]
        invalid["groups"][1]["student_ids"] = []
        assert (await case.client.put(f"{path}/halves", json=invalid)).status_code == 422
        assert (
            next(
                p
                for p in (await case.client.get(path)).json()["partitions"]
                if p["kind"] == "halves"
            )
            == current
        )
        assert (
            await case.client.request(
                "DELETE", f"{path}/halves", json={"expected_revision": halves["revision"]}
            )
        ).status_code == 409
        assert (
            await case.client.request(
                "DELETE", f"{path}/halves", json={"expected_revision": current["revision"]}
            )
        ).status_code == 204
        partitions = (await case.client.get(path)).json()["partitions"]
        assert partitions == sorted([thirds, kholles], key=lambda p: p["kind"])
        # Membership deletion cascades into every independent assignment, never other pupils.
        assert (
            await case.client.delete(f"/api/v1/admin/users/{pupils[0]}/promotions/{promotion_id}")
        ).status_code == 204
        result = (await case.client.get(path)).json()
        assert len(result["students"]) == 6
        assert all(
            pupils[0] not in g["student_ids"] for p in result["partitions"] for g in p["groups"]
        )
        stale = {**body, "expected_revision": thirds["revision"], "groups": thirds["groups"]}
        assert (await case.client.put(f"{path}/thirds", json=stale)).status_code == 409
        # Adding a new pupil leaves them explicitly unassigned rather than reshuffling classmates.
        new_pupil, _ = await case.create(activate=False)
        assert (
            await case.client.put(f"/api/v1/admin/users/{new_pupil}/promotions/{promotion_id}")
        ).status_code == 204
        result = (await case.client.get(path)).json()
        assert new_pupil in [student["id"] for student in result["students"]]
        assert all(
            new_pupil not in g["student_ids"] for p in result["partitions"] for g in p["groups"]
        )
        events = (
            await case.client.get(
                f"/api/v1/admin/events?resource_type=promotion&resource_id={promotion_id}"
            )
        ).json()["items"]
        assert sum(e["event_type"] == "promotion.groups_saved" for e in events) == 4
        assert sum(e["event_type"] == "promotion.groups_deleted" for e in events) == 1
    finally:
        await clear_promotions([promotion_id])


@pytest.mark.asyncio
async def test_staff_scope_and_database_constraints(auth_case: Harness) -> None:
    """Limit teacher/khôlleur reads and all writes, and enforce membership in PostgreSQL."""
    case = auth_case
    promotion_id = await make_promotion(case)
    other = await make_promotion(case, "AUTRE")
    path = f"/api/v1/promotion-groups/{promotion_id}"
    try:
        pupils = await create_roster(case, promotion_id, 6)
        partition = await preview_and_save(case, path, pupils, "kholles")
        body = {
            "expected_revision": partition["revision"],
            "roster_ids": pupils,
            "groups": partition["groups"],
        }
        # More than five pupils cannot be persisted, even through direct HTTP requests.
        invalid = copy.deepcopy(body)
        invalid["groups"] = [{"number": 1, "x": 0, "y": 0, "student_ids": pupils}]
        assert (await case.client.put(f"{path}/kholles", json=invalid)).status_code == 422
        # A formerly accepted 5/1 split must also be rejected for a target of three.
        invalid["groups"] = [
            {"number": 1, "x": 0, "y": 0, "student_ids": pupils[:5]},
            {"number": 2, "x": 300, "y": 0, "student_ids": pupils[5:]},
        ]
        assert (await case.client.put(f"{path}/kholles", json=invalid)).status_code == 422
        assert (await case.client.get(path)).json()["partitions"] == [partition]
        outsider, _ = await case.create(activate=False)
        async with case.database.sessions.begin() as db:
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(
                        insert(PromotionGroupMember).values(
                            promotion_id=promotion_id,
                            kind="kholles",
                            user_id=outsider,
                            group_number=1,
                        )
                    )
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(
                        insert(PromotionGroupMember).values(
                            promotion_id=promotion_id,
                            kind="kholles",
                            user_id=pupils[0],
                            group_number=2,
                        )
                    )
        for role in ("teacher", "kholleur", "user"):
            user_id, username = await case.create(role)
            assert (
                await case.client.put(f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}")
            ).status_code == 204
            assert (
                await case.client.post(
                    "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
                )
            ).status_code == 200
            expected = 403 if role == "user" else 200
            assert (await case.client.get(path)).status_code == expected
            assert (
                await case.client.get(f"/api/v1/promotion-groups/promotions/{promotion_id}")
            ).status_code == expected
            assert (await case.client.get(f"/api/v1/promotion-groups/{other}")).status_code == (
                403 if role == "user" else 404
            )
            assert (
                await case.client.get("/api/v1/promotion-groups/promotions")
            ).status_code == expected
            for method, suffix, data in [
                ("PUT", "", body),
                (
                    "POST",
                    "/preview",
                    {key: value for key, value in body.items() if key != "groups"},
                ),
                ("DELETE", "", {"expected_revision": partition["revision"]}),
            ]:
                assert (
                    await case.client.request(method, f"{path}/kholles{suffix}", json=data)
                ).status_code == 403
            case.as_admin()
            assert (
                await case.client.delete(f"/api/v1/admin/users/{user_id}/promotions/{promotion_id}")
            ).status_code == 204
            assert (
                await case.client.post(
                    "/api/v1/auth/login", json={"identifier": username, "password": PASSWORD}
                )
            ).status_code == 200
            assert (await case.client.get(path)).status_code == (403 if role == "user" else 404)
            case.as_admin()
        assert (
            await case.client.patch(
                f"/api/v1/admin/promotions/{promotion_id}", json={"is_active": False}
            )
        ).status_code == 200
        assert (await case.client.get(path)).status_code == 200
        assert (await case.client.put(f"{path}/kholles", json=body)).status_code == 409
        case.client.cookies.clear()
        assert (await case.client.get(path)).status_code == 401
    finally:
        await clear_promotions([promotion_id, other])
