"""Local demo authentication without network calls or persistent credentials."""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def demo_seed(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the repository's demo entry point with isolated authentication inputs."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "script"))
    monkeypatch.delenv("SOPHIKRON_SEED_EMAIL", raising=False)
    monkeypatch.delenv("SOPHIKRON_SEED_PASSWORD", raising=False)
    module = import_module("seed_demo_data")
    monkeypatch.setattr(module, "describe", Mock())
    monkeypatch.setattr(module, "seed", Mock())
    monkeypatch.setattr(module, "getpass", Mock(return_value="synthetic-test-password"))
    client = Mock()
    client.request.return_value = {
        "roles": ["admin"],
        "permissions": [
            "users.read",
            "users.manage",
            "promotions.read",
            "promotions.manage",
            "profiles.manage",
        ],
    }
    monkeypatch.setattr(module, "Client", Mock(return_value=client))
    return module


def test_demo_dry_run_needs_no_credentials_or_connection(demo_seed: ModuleType) -> None:
    """Validate scenario overrides without asking for credentials or contacting the API."""
    assert demo_seed.main(["--dry-run", "--classes", "4", "--namespace", "release"]) == 0
    scenario = demo_seed.describe.call_args.args[0]
    assert scenario.class_count == 4 and scenario.namespace == "release"
    assert demo_seed.CONFIG.class_count == 1 and demo_seed.CONFIG.namespace == "demo"
    demo_seed.Client.assert_not_called()
    demo_seed.getpass.assert_not_called()
    demo_seed.seed.assert_not_called()


@pytest.mark.parametrize("classes", [1, 2])
def test_complete_demo_calendars(demo_seed: ModuleType, classes: int) -> None:
    """Verify both cohorts, exact volumes, double blocks and collision-free specialist scope."""
    from collections import Counter
    from copy import deepcopy

    from demo_data.runner import prepare
    from demo_data.timetables import blocks_for_year

    from app.schemas.timetable import SeriesData, YearDocument, YearSettings
    from app.services.timetable_diagnostics import annual_diagnostics
    from app.services.timetable_engine import daily_slots, occurrences

    settings = deepcopy(demo_seed.CONFIG)
    settings.class_count = classes
    settings.filled_calendar_indexes = None
    pupils, staff, plan = prepare(settings)
    names = [c.identifier for c in settings.classes()]
    assert names == (["PTSI", "PT"] if classes == 1 else ["PTSI1", "PT1", "PTSI2", "PT2"])
    assert len(pupils) == classes * 2 * settings.pupils_per_class
    for subject in ("maths", "si", "physics"):
        teachers = [p for p in staff if p.role == "teacher" and p.subjects[0] == subject]
        assert len(teachers) == classes * 2
        assert {p.promotion for p in teachers} == set(names)
    for subject in ("english", "french", "german"):
        teachers = [p for p in staff if p.role == "teacher" and subject in p.subjects]
        assert len(teachers) == 1 and teachers[0].promotion is None
    people = {p.email: p for p in staff}
    for lesson in plan:
        assert people[lesson.teacher].promotion in (None, names[lesson.calendar_index])
    for index in range(classes * 2):
        totals = Counter()
        for lesson in plan:
            if lesson.calendar_index == index:
                totals[(lesson.subject, lesson.kind)] += (
                    0.5 if lesson.target_kind == "halves" else 1
                )
        for subject, kinds in settings.weekly_hours.items():
            for kind, hours in kinds.items():
                assert totals[subject, kind] == hours
    for position, lesson in enumerate(plan):
        for other in plan[position + 1 :]:
            if (lesson.weekday, lesson.period) == (other.weekday, other.period):
                assert lesson.teacher != other.teacher
                assert lesson.room != other.room
                if lesson.calendar_index == other.calendar_index:
                    assert lesson.target_kind == other.target_kind == "halves"
                    assert lesson.target_number != other.target_number
    year_settings = YearSettings.model_validate(settings.calendar_settings())
    year = {"settings": settings.calendar_settings(), "slots": daily_slots(year_settings)}
    subjects = import_module("demo_data.configuration").SUBJECTS
    catalogue = {
        "subjects": {s: {"id": i + 1} for i, s in enumerate(subjects)},
        "users": {p.email: {"id": i + 1} for i, p in enumerate(staff)},
    }
    rooms = {name: {"id": i + 1} for i, name in enumerate(settings.rooms)}
    for index in range(classes * 2):
        blocks = blocks_for_year(
            [lesson for lesson in plan if lesson.calendar_index == index],
            year,
            catalogue,
            rooms,
            {"id": 1},
        )
        assert sum(b["duration_slots"] == 4 for b in blocks) > len(blocks) / 2
        document = YearDocument(
            settings=year_settings,
            series=[
                SeriesData.model_validate({**b, "id": f"{i + 1:032x}", "lineage": f"{i + 1:032x}"})
                for i, b in enumerate(blocks)
            ],
        )
        events = occurrences(document)
        assert events
        members = [{"id": i, "roles": ["user"], "promotion_ids": [1]} for i in range(1, 5)]
        groups = [
            {"promotion_id": 1, "kind": "halves", "number": i, "student_ids": [i * 2 - 1, i * 2]}
            for i in (1, 2)
        ]
        groups.append(
            {"promotion_id": 1, "kind": "custom", "number": 1, "student_ids": [1, 2, 3, 4]}
        )
        _, issues = annual_diagnostics(
            events, year_settings, members, groups, 1, year_settings.start, document.series
        )
        assert issues == []


@pytest.mark.parametrize("email_argument", [False, True], ids=["environment", "command-line"])
def test_demo_uses_supplied_credentials_and_logs_out(
    demo_seed: ModuleType, monkeypatch: pytest.MonkeyPatch, email_argument: bool
) -> None:
    """Respect the email override and process password, then revoke the session."""
    monkeypatch.setenv("SOPHIKRON_SEED_EMAIL", "environment@example.org")
    monkeypatch.setenv("SOPHIKRON_SEED_PASSWORD", "synthetic-environment-password")
    arguments = ["--email", "override@example.org"] if email_argument else []
    assert demo_seed.main(arguments) == 0
    client = demo_seed.Client.return_value
    assert client.request.call_args_list[0].args == (
        "POST",
        "/auth/login",
        {
            "identifier": "override@example.org" if email_argument else "environment@example.org",
            "password": "synthetic-environment-password",
        },
    )
    client.request.assert_called_with("POST", "/auth/logout")
    demo_seed.seed.assert_called_once()
    demo_seed.getpass.assert_not_called()


@pytest.mark.parametrize(
    "index,count,minutes", [(0, 30, 900), (1, 25, 750), (2, 30, 900), (3, 25, 750)]
)
def test_seed_kholle_requirements_and_safe_reruns(
    demo_seed: ModuleType, index: int, count: int, minutes: int
) -> None:
    """Use numbered API weeks, four exact volumes and skip matching existing settings."""
    from datetime import date, timedelta

    from demo_data.configuration import SeedError
    from demo_data.timetables import seed_kholle_requirements

    first = date(2026, 9, 7)
    weeks = [
        {
            "number": n + 1,
            "start": (first + timedelta(weeks=n)).isoformat(),
            "end": (first + timedelta(weeks=n, days=4)).isoformat(),
            "eligible": n != 2,
        }
        for n in range(32)
    ]
    state = {"weeks": weeks, "settings": None, "revision": "a" * 32, "year_revision": "b" * 32}
    client = Mock()
    client.request.return_value = state
    catalogue = {
        "subjects": {
            key: {"id": i + 1} for i, key in enumerate(("maths", "si", "physics", "english"))
        }
    }
    seed_kholle_requirements(client, 10, index, catalogue)
    payload = client.request.call_args.args[2]
    assert payload["settings"]["start"] == weeks[0]["start"]
    assert payload["settings"]["end"] == weeks[count - 1]["end"]
    assert payload["settings"]["subjects"] == [
        {"subject_id": i, "minutes": minutes} for i in range(1, 5)
    ]
    state["settings"] = payload["settings"]
    client.request.reset_mock()
    seed_kholle_requirements(client, 10, index, catalogue)
    client.request.assert_called_once_with("POST", "/timetable/calendars/10/kholle/preview")
    state["settings"] = {**payload["settings"], "start": weeks[1]["start"]}
    with pytest.raises(SeedError, match="diffèrent"):
        seed_kholle_requirements(client, 10, index, catalogue)
    state["weeks"] = weeks[:10]
    with pytest.raises(SeedError, match="semaines"):
        seed_kholle_requirements(client, 10, index, catalogue)


def test_seed_validates_only_complete_volumes(demo_seed: ModuleType) -> None:
    """Validate volumes once and reject incomplete annual prerequisites without later edits."""
    from demo_data.configuration import SeedError
    from demo_data.runner import validate_volumes

    client = Mock()
    state = {"errors": [], "validated": {"volumes": False}, "revision": "a" * 64}
    client.request.return_value = state
    validate_volumes(client, 2026)
    client.request.assert_called_with(
        "PUT",
        "/timetable/kholloscope/2026/workflow",
        {"step": "volumes", "expected_revision": "a" * 64},
    )
    client.request.reset_mock()
    state["validated"]["volumes"] = True
    validate_volumes(client, 2026)
    client.request.assert_called_once_with("GET", "/timetable/kholloscope/2026/workflow")
    state["errors"] = ["Promotion manquante"]
    with pytest.raises(SeedError, match="Promotion manquante"):
        validate_volumes(client, 2026)


def test_demo_fills_all_requested_calendars(demo_seed: ModuleType) -> None:
    """Fill additional requested PTSI/PT calendars without editing index settings."""
    from copy import deepcopy

    settings = deepcopy(demo_seed.CONFIG)
    settings.class_count = 2
    assert settings.calendar_indexes() == (0, 1, 2, 3)


def test_demo_prompts_for_credentials(
    demo_seed: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prompt for a missing email and hide the password using getpass."""
    monkeypatch.setattr("builtins.input", Mock(return_value="  local@example.org  "))
    assert demo_seed.main([]) == 0
    demo_seed.getpass.assert_called_once()
    assert demo_seed.Client.return_value.request.call_args_list[0].args[2] == {
        "identifier": "local@example.org",
        "password": "synthetic-test-password",
    }


@pytest.mark.parametrize("failure", ["login", "permissions", "seed"])
def test_demo_failures_revoke_only_authenticated_sessions(
    demo_seed: ModuleType, failure: str
) -> None:
    """Skip seeding on denied access and log out even when later operations fail."""
    client = demo_seed.Client.return_value
    if failure == "login":
        client.request.side_effect = demo_seed.SeedError("Synthetic login failure")
    elif failure == "permissions":
        client.request.return_value = {"roles": ["teacher"], "permissions": []}
    else:
        demo_seed.seed.side_effect = demo_seed.SeedError("Synthetic scenario failure")
    assert demo_seed.main(["--email", "local@example.org"]) == 1
    if failure == "login":
        assert client.request.call_count == 1
    else:
        client.request.assert_called_with("POST", "/auth/logout")
    if failure != "seed":
        demo_seed.seed.assert_not_called()
