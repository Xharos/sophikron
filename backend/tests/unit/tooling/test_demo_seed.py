"""Local demo authentication without network calls or persistent credentials."""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def demo_seed(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the repository's demo entry point with isolated authentication inputs."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "script"))
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
            "curricula.read",
            "curricula.manage",
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


def test_demo_curriculum_override(demo_seed: ModuleType) -> None:
    """Allow a CLI subject selection without changing the configured default."""
    assert demo_seed.main(["--dry-run", "--curriculum-subjects", "si", "english"]) == 0
    assert demo_seed.describe.call_args.args[0].curriculum_subjects == ("si", "english")
    assert demo_seed.CONFIG.curriculum_subjects == ("computer_science", "maths", "physics", "si")


def test_demo_curriculum_import_and_rerun(demo_seed: ModuleType) -> None:
    """Validate the portable graph and preserve it on a second run."""
    from demo_data.curricula import seed_curriculum

    from app.schemas.curricula import CompetencyImport
    from app.services.competency_codes import competency_codes

    client = Mock()
    curriculum = {
        "id": 5,
        "title": "Référentiel PTSI/PT · demo",
        "subject_ids": [1, 2, 3, 4],
        "is_active": True,
    }
    graph_path = "/curricula/5/subjects/4"
    client.request.side_effect = [
        {"curricula": []},
        curriculum,
        {"version": 0, "nodes": []},
        {},
        {"curricula": [curriculum]},
        {"version": 1, "nodes": [{"id": 9}]},
    ]
    keys = demo_seed.CONFIG.curriculum_subjects
    subjects = {key: {"id": index, "name": key} for index, key in enumerate(keys, 1)}
    seed_curriculum(client, demo_seed.CONFIG, subjects)
    seed_curriculum(client, demo_seed.CONFIG, subjects)

    calls = [call.args for call in client.request.call_args_list]
    assert [(method, path) for method, path, *_ in calls] == [
        ("GET", "/curricula/catalog"),
        ("POST", "/curricula"),
        ("GET", graph_path),
        ("POST", graph_path + "/import"),
        ("GET", "/curricula/catalog"),
        ("GET", graph_path),
    ]
    assert calls[1][2]["subject_ids"] == [1, 2, 3, 4]
    nodes = CompetencyImport.model_validate(calls[3][2]).document.nodes
    codes, ordered = competency_codes(
        nodes, [(parent, node.id) for node in nodes for parent in node.parent_ids]
    )
    assert len(nodes) == 28
    assert [codes[key] for key in ordered] == [
        code
        for root, count in zip("ABCDEFG", (5, 3, 3, 3, 2, 3, 2), strict=True)
        for code in [root, *(f"{root}.{index}" for index in range(1, count + 1))]
    ]


def test_demo_quiz_seeds_linked_questions_once(demo_seed: ModuleType) -> None:
    """Exercise all 20 payloads using the real Quiz schema and a resumable API read."""
    from collections import Counter

    from demo_data.curricula import si_document
    from demo_data.quiz import seed_si_quiz

    from app.schemas.quiz import QuestionFields

    client = Mock()
    client.request.return_value = {"questions": []}
    graph = si_document("SI")
    seed_si_quiz(client, "demo", 4, graph)
    calls = [call.args for call in client.request.call_args_list]
    assert calls[0] == ("GET", "/quiz/subjects/4")
    assert all(call[:2] == ("POST", "/quiz/subjects/4/questions") for call in calls[1:])
    questions = [QuestionFields.model_validate(call[2]) for call in calls[1:]]
    assert Counter(question.rule.kind for question in questions) == {
        "number": 8,
        "choice": 8,
        "text": 4,
    }
    assert len({question.title for question in questions}) == 20
    child_ids = {node["id"] for node in graph["nodes"] if node["parent_ids"]}
    assert all(
        question.statement
        and question.prompt
        and not question.image
        and question.competency_ids
        and set(question.competency_ids) <= child_ids
        for question in questions
    )

    client.reset_mock()
    client.request.return_value = {"questions": [{"title": item.title} for item in questions]}
    seed_si_quiz(client, "demo", 4, graph)
    client.request.assert_called_once_with("GET", "/quiz/subjects/4")


def test_demo_quiz_missing_competency_stops_before_creating(demo_seed: ModuleType) -> None:
    """Prevent partial fallback imports when a required competency was removed."""
    from demo_data.quiz import seed_si_quiz

    client = Mock()
    client.request.return_value = {"questions": []}
    with pytest.raises(demo_seed.SeedError, match=r"Compétence SI B\.2"):
        seed_si_quiz(client, "demo", 4, {"nodes": []})
    client.request.assert_called_once_with("GET", "/quiz/subjects/4")
