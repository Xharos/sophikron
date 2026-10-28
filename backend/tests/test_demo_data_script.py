"""Demonstration seeding contracts, safe retries and real local API compatibility."""

import ast
import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import anyio
import pytest
from sqlalchemy import delete

from app.models import Subject, TeacherSubject
from app.schemas.site import SubjectFields
from app.services.groups import generate_groups
from tests.test_auth_postgres import Harness
from tests.test_dashboard_postgres import clear_promotions


@pytest.fixture
def demo_script() -> ModuleType:
    """Load the standalone script with local credentials removed before execution.

    Returns
    -------
    ModuleType
        Isolated script definitions; its login entry point is never invoked.
    """
    path = Path(__file__).resolve().parents[2] / "script" / "creer_donnees_test.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {"EMAIL", "PASSWORD"}
            for target in node.targets
        ):
            node.value = ast.Constant("")
    module = ModuleType("demo_data_script")
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), module.__dict__)
    return module


def test_seven_subjects_have_unique_colors_and_teacher_identities(demo_script: ModuleType) -> None:
    """Validate real subject contracts and keep teacher emails distinct from all ninety pupils."""
    subjects = demo_script.SUBJECTS
    teachers = demo_script.build_teachers()
    assert len(subjects) == 7
    assert len(teachers) == 10
    assert len({item["color"].upper() for item in subjects}) == 7
    assert len({item["email"] for item in teachers}) == 10
    for subject in subjects:
        matching = [teacher for teacher in teachers if teacher["subject"] == subject["name"]]
        if subject["icon"] == "code":
            assert not matching
            assert sum(
                teacher.get("secondary_subject") == subject["name"] for teacher in teachers
            ) == 8
        else:
            assert len(matching) == (2 if subject in subjects[:4] else 1)
    assert not {item["email"] for item in teachers} & {
        item["email"] for item in demo_script.build_students()
    }
    for item in subjects:
        SubjectFields.model_validate({key: item[key] for key in ("name", "color", "icon")})


def test_kholleurs_have_one_subject_and_distinct_identities(demo_script: ModuleType) -> None:
    """Keep seven single-subject kholleurs distinct from teachers and pupils."""
    kholleurs = demo_script.build_kholleurs()
    assert len(kholleurs) == 7
    assert {person["subject"] for person in kholleurs} == {
        subject["name"] for subject in demo_script.SUBJECTS
    }
    assert all(person["role"] == "kholleur" for person in kholleurs)
    assert all("secondary_subject" not in person for person in kholleurs)
    people = [*kholleurs, *demo_script.build_teachers(), *demo_script.build_students()]
    assert len({person["email"] for person in people}) == len(people)


@pytest.mark.parametrize("assigned", [[], [1], [1, 2], [1, 3]])
def test_staff_subject_completion_and_memberships(
    demo_script: ModuleType, monkeypatch: pytest.MonkeyPatch, assigned: list[int]
) -> None:
    """Add missing subjects and promotions while refusing unexpected subject assignments."""
    teacher = demo_script.build_teachers()[0]
    writes = []

    def request(
        opener: object, method: str, path: str, payload: dict | None = None
    ) -> dict:
        """Return a synthetic profile and record any requested writes."""
        if method == "GET":
            return {"subject_ids": assigned, "profile_version": 4, "promotions": [{"id": 10}]}
        writes.append((method, path, payload))
        return {}

    monkeypatch.setattr(demo_script, "api_request", request)
    arguments = (
        None, [teacher], {teacher["email"]: {"id": 5}},
        {"PT": {"id": 10}, "PTSI": {"id": 11}},
        {teacher["subject"]: {"id": 1}, teacher["secondary_subject"]: {"id": 2}},
    )
    if 3 in assigned:
        with pytest.raises(demo_script.SeedError, match="autres matières"):
            demo_script.seed_teachers(*arguments)
        assert not writes
        return
    demo_script.seed_teachers(*arguments)
    patches = [payload for method, _, payload in writes if method == "PATCH"]
    assert patches == ([] if assigned == [1, 2] else [
        {"expected_version": 4, "subject_ids": [1, 2]}
    ])
    assert ("PUT", "/admin/users/5/promotions/11", None) in writes


def test_existing_subject_color_collisions_are_fixed_once(
    demo_script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep subject identities and icons, differentiate collisions and avoid updates on retry."""
    rows = [
        {
            "id": index,
            "name": item["name"],
            "color": "#244BC1",
            "icon": "book",
            "version": 0,
            "is_active": True,
        }
        for index, item in enumerate(demo_script.SUBJECTS, start=1)
    ]
    writes = []

    def pages(opener: object, path: str, filters: dict | None = None) -> list[dict]:
        """Supply active subjects without exposing any real catalogue or credentials."""
        return [] if filters else deepcopy(rows)

    def request(opener: object, method: str, path: str, payload: dict) -> dict:
        """Apply a versioned color change to a synthetic subject fixture."""
        assert method == "PUT"
        identifier = int(path.rsplit("/", 1)[1])
        row = rows[identifier - 1]
        assert payload["expected_version"] == row["version"]
        assert payload["icon"] == "book"
        row["color"] = payload["color"]
        row["version"] += 1
        writes.append(identifier)
        return deepcopy(row)

    monkeypatch.setattr(demo_script, "read_pages", pages)
    monkeypatch.setattr(demo_script, "api_request", request)
    demo_script.seed_subjects(None)
    assert len({row["color"] for row in rows}) == 7
    assert len(writes) == 6
    demo_script.seed_subjects(None)
    assert len(writes) == 6


@pytest.mark.parametrize("incomplete", [False, True])
def test_existing_partitions_are_never_overwritten(
    demo_script: ModuleType, monkeypatch: pytest.MonkeyPatch, incomplete: bool
) -> None:
    """Reuse complete manual groups and report incomplete ones without replacing them."""
    pupils = list(range(1, 46))
    state = {
        "students": [{"id": identifier, "status": "pending_activation"} for identifier in pupils],
        "partitions": [
            {
                "kind": kind,
                "groups": [group.model_dump() for group in generate_groups(kind, pupils, 3)],
            }
            for kind in ("halves", "thirds", "kholles")
        ],
    }
    if incomplete:
        state["partitions"][0]["groups"][0]["student_ids"].pop()

    def request(opener: object, method: str, path: str) -> dict:
        """Permit reads only so any attempt to replace manual groups fails the test."""
        assert method == "GET"
        return deepcopy(state)

    monkeypatch.setattr(demo_script, "api_request", request)
    if incomplete:
        with pytest.raises(demo_script.SeedError, match="incomplets"):
            demo_script.seed_groups(None, {"PT": {"id": 1}})
    else:
        demo_script.seed_groups(None, {"PT": {"id": 1}})


@pytest.mark.parametrize("payload", [{}, [1], None])
def test_preview_rejects_malformed_list_responses(demo_script: ModuleType, payload: object) -> None:
    """Reject unexpected preview bodies rather than forwarding them to a group-save request."""
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.status = 200
    response.read.return_value = json.dumps(payload).encode()
    with pytest.raises(demo_script.SeedError, match="Format de liste"):
        demo_script.api_request(opener, "POST", "/preview", {}, list_key="groups")


def test_preview_accepts_the_api_group_list(demo_script: ModuleType) -> None:
    """Wrap the real preview endpoint's JSON list for the subsequent save request."""
    opener = MagicMock()
    response = opener.open.return_value.__enter__.return_value
    response.status = 200
    groups = [{"number": 1, "x": 20, "y": 20, "student_ids": [1, 2, 3]}]
    response.read.return_value = json.dumps(groups).encode()
    assert demo_script.api_request(opener, "POST", "/preview", {}, list_key="groups") == {
        "groups": groups
    }


def test_pagination_stops_on_a_stale_empty_page(
    demo_script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inconsistent catalogue must fail promptly instead of retrying an empty page forever."""
    monkeypatch.setattr(demo_script, "api_request", lambda *args: {"items": [], "total": 1})
    with pytest.raises(demo_script.SeedError, match="catalogue a changé"):
        demo_script.read_pages(None, "/admin/users")


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required")
@pytest.mark.asyncio
async def test_complete_seed_and_retry_through_real_apis(
    auth_case: Harness, demo_script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed pupils and staff, then retain their subjects, groups and versions on retry."""
    case = auth_case
    demo_script.YEAR = 2198
    demo_script.SUBJECTS = tuple(
        {**item, "name": f"{case.prefix} {item['name']}"} for item in demo_script.SUBJECTS
    )
    pupils = demo_script.build_students()
    for pupil in pupils:
        pupil["email"] = f"{case.prefix}.{pupil['email']}"
    monkeypatch.setattr(demo_script, "build_students", lambda: deepcopy(pupils))
    loop = asyncio.get_running_loop()
    calls: list[tuple[str, str]] = []
    promotion_ids = []
    subject_ids = []
    sent = len(case.mailer.messages)

    def request(
        opener: object,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        list_key: str | None = None,
    ) -> dict:
        """Bridge the synchronous script to the real ASGI API on its existing event loop."""
        response = asyncio.run_coroutine_threadsafe(
            case.client.request(method, f"/api/v1{path}", json=payload), loop
        ).result(timeout=30)
        assert response.is_success, f"{method} {path}: HTTP {response.status_code}"
        result = {} if response.status_code == 204 else response.json()
        if method == "POST" and path == "/admin/users":
            case.ids.append(result["id"])
        elif method == "POST" and path == "/admin/promotions":
            promotion_ids.append(result["id"])
        elif method == "POST" and path == "/admin/subjects":
            subject_ids.append(result["id"])
        calls.append((method, path))
        return {list_key: result} if list_key else result

    monkeypatch.setattr(demo_script, "api_request", request)
    try:
        await anyio.to_thread.run_sync(demo_script.seed, None)
        assert len(promotion_ids) == 2 and len(subject_ids) == 7
        accounts = []
        for offset in (0, 100):
            accounts.extend(
                (await case.client.get(
                    "/api/v1/admin/users", params={"limit": 100, "offset": offset}
                )).json()["items"]
            )
        teachers = [
            item
            for item in accounts
            if item["email"] in {
                teacher["email"] for teacher in [
                    *demo_script.build_teachers(), *demo_script.build_kholleurs()
                ]
            }
        ]
        assert len(teachers) == 17
        profiles = [
            (await case.client.get(f"/api/v1/admin/users/{teacher['id']}/profile")).json()
            for teacher in teachers
        ]
        assert all(
            len(profile["subject_ids"]) in {1, 2} and len(profile["promotions"]) == 2
            for profile in profiles
        )
        assert {identifier for profile in profiles for identifier in profile["subject_ids"]} == set(
            subject_ids
        )
        partitions = []
        for identifier in promotion_ids:
            metadata = (await case.client.get(f"/api/v1/admin/promotions/{identifier}")).json()
            assert metadata["student_count"] == 45 and metadata["teaching_count"] == 17
            groups = (await case.client.get(f"/api/v1/promotion-groups/{identifier}")).json()
            sizes = {
                partition["kind"]: sorted(
                    len(group["student_ids"]) for group in partition["groups"]
                )
                for partition in groups["partitions"]
            }
            assert sizes == {"halves": [22, 23], "thirds": [15, 15, 15], "kholles": [3] * 15}
            partitions.append(groups["partitions"])
        subjects = (await case.client.get("/api/v1/admin/subjects", params={"limit": 100})).json()[
            "items"
        ]
        assert len({subject["color"] for subject in subjects if subject["id"] in subject_ids}) == 7
        calls.clear()
        await anyio.to_thread.run_sync(demo_script.seed, None)
        assert not any(
            method in {"POST", "PATCH", "DELETE"}
            or (method == "PUT" and "/promotions/" not in path)
            for method, path in calls
        )
        assert len(case.mailer.messages) == sent
        for index, identifier in enumerate(promotion_ids):
            current = (await case.client.get(f"/api/v1/promotion-groups/{identifier}")).json()
            assert current["partitions"] == partitions[index]
        assert [
            (await case.client.get(f"/api/v1/admin/users/{teacher['id']}/profile")).json()[
                "profile_version"
            ]
            for teacher in teachers
        ] == [profile["profile_version"] for profile in profiles]
    finally:
        await clear_promotions(promotion_ids)
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id.in_(subject_ids))
            )
            await session.execute(delete(Subject).where(Subject.id.in_(subject_ids)))
