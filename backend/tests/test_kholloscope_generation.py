"""Real CP-SAT checks for anonymous rotations, exact service and dated recovery."""

import math
import threading
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.kholloscope_generation import GenerationRules, GenerationStart
from app.services.kholloscope_service import balanced_service, service_cycles
from app.services.kholloscope_solver import (
    GenerationError,
    annual_quota,
    candidates,
    free_lunch,
    generate,
    lunch_conflicts,
    solve_choices,
    validate_cycle_service,
    validate_draft,
)


def test_time_distribution_defaults_and_saved_compatibility() -> None:
    """Supply recommended shares for new jobs and saved jobs without these options."""
    assert GenerationRules().time_distribution() == (5, 15, 75, 5)
    assert GenerationRules.from_saved_options({"time_limit": 900}).time_distribution() == (
        5, 15, 75, 5
    )
    rules = GenerationRules(time_stability_percent=10, time_rotation_percent=70)
    assert GenerationRules.from_saved_options(rules.model_dump()) == rules


@pytest.mark.parametrize("value", [0, -1, 98, 5.5, True, "5", None])
def test_invalid_time_percentage_is_rejected(value: object) -> None:
    """Reject missing, noninteger and out-of-range individual percentages."""
    with pytest.raises(ValidationError):
        GenerationRules.model_validate({"time_stability_percent": value})


def test_time_distribution_must_total_one_hundred() -> None:
    """Reject totals above or below the total budget at the API boundary."""
    for value in (4, 6):
        with pytest.raises(ValidationError, match="100 %"):
            GenerationRules(time_stability_percent=value)


def test_saved_time_is_redistributed_proportionally(
    solver_input: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measure stage budgets with a controlled clock while using actual feasible solves."""
    from types import SimpleNamespace

    from app.services import kholloscope_solver as module

    elapsed = [0.0]
    budgets = []
    original = module.cp_model.CpSolver.solve

    def solve(solver: object, model: object) -> object:
        """Solve the small real model and simulate time spent by each template criterion."""
        budgets.append(solver.parameters.max_time_in_seconds)
        status = original(solver, model)
        elapsed[0] += (27, 135, 600)[len(budgets) - 1] if len(budgets) <= 3 else 1
        return status

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    monkeypatch.setattr(module.cp_model.CpSolver, "solve", solve)
    generate(solver_input, {"time_limit": 900, "optimize": True}, lambda _: None, threading.Event())
    assert budgets[:3] == pytest.approx([45, 873 * 15 / 95, 738 * 75 / 80])


@pytest.fixture
def solver_input() -> dict:
    """Build four teaching weeks and four subjects without any real group or pupil data."""
    weeks = [
        {
            "start": (date(2026, 9, 7) + timedelta(weeks=n)).isoformat(),
            "end": (date(2026, 9, 11) + timedelta(weeks=n)).isoformat(),
            "days": 5,
            "eligible": True,
            "number": n + 1,
        }
        for n in range(4)
    ]
    return {
        "base_date": "2026-09-01",
        "calendars": [
            {
                "id": 1,
                "name": "PTSI",
                "group_count": 2,
                "period_start": "2026-09-07",
                "period_end": "2026-10-02",
                "weeks": weeks,
                "settings": {
                    "start": "2026-09-07",
                    "end": "2026-10-02",
                    "day_start": 28800,
                    "day_end": 64800,
                    "session_minutes": 55,
                    "saturday": False,
                    "lunch_start": 43200,
                    "lunch_end": 50400,
                    "breaks": [],
                    "holidays": [],
                },
                "requirements": [{"subject_id": s, "minutes": 120} for s in range(1, 5)],
            }
        ],
        "bookings": {},
        "availability": {
            str(t): [{"weekday": d, "start": 28800, "end": 64800} for d in range(5)]
            for t in range(1, 5)
        },
        "subjects": [{"id": s, "staff": [{"id": s, "sessions": 2}]} for s in range(1, 5)],
        "selected_rooms": {str(s): [1] for s in range(1, 5)},
        "capacities": {"1": 2},
        "preferences": {},
    }


def test_exact_template_and_annual_anonymous_volumes(solver_input: dict) -> None:
    """Cover every abstract group annually and every subject per fortnight, two each week."""
    logs = []
    result = generate(solver_input, {"time_limit": 15}, logs.append, threading.Event())
    assert len(result["template"]) == 8 and len(result["sessions"]) == 16
    assert set(solver_input) >= {"calendars", "subjects"}
    assert "groups" not in solver_input and "pupils" not in solver_input
    assert Counter((s["track"], s["subject_id"]) for s in result["sessions"]) == Counter(
        {(g, s): 2 for g in (1, 2) for s in range(1, 5)}
    )
    assert Counter((s["track"], s["phase"]) for s in result["template"]) == Counter(
        {(g, phase): 2 for g in (1, 2) for phase in (0, 1)}
    )
    assert Counter((s["teacher_id"], s["phase"]) for s in result["template"]) == Counter(
        {(t, phase): 1 for t in range(1, 5) for phase in (0, 1)}
    )
    assert any("Recherche annuelle" in line for line in logs)
    assert not result["mappings"] and not result["applied"]
    assert all(q["cycle_based"] and q["sessions"] == 2 for q in result["quotas"])


def test_generation_default_budget_and_log_millisecond_boundaries() -> None:
    """Expose a five-minute default and stamp every physical line since submission."""
    from app.services.kholloscope_worker import run_log_lines

    assert GenerationRules().time_limit == 900
    assert GenerationRules(time_limit=43200).time_limit == 43200
    assert GenerationRules(time_limit=1800).time_limit == 1800
    submitted = datetime(2026, 11, 6, tzinfo=timezone.utc)
    assert run_log_lines(
        "Première ligne\n  Deuxième ligne\n\n",
        submitted,
        at=submitted + timedelta(minutes=2, seconds=3, milliseconds=45),
    ) == ["[02:03:045] Première ligne", "[02:03:045]   Deuxième ligne"]
    assert run_log_lines("Avant", submitted, at=submitted - timedelta(seconds=1)) == [
        "[00:00:000] Avant"
    ]
    assert run_log_lines("Fin", submitted, at=submitted + timedelta(seconds=300)) == [
        "[05:00:000] Fin"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "timeout"])
async def test_worker_persists_timestamps_on_progress_and_failure(outcome: str) -> None:
    """Flush multiline progress and terminal errors as individually timestamped durable lines."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.services.kholloscope_worker import execute_run, run_log_lines

    submitted = datetime.now(timezone.utc)
    row = SimpleNamespace(
        snapshot={},
        options={},
        created_at=submitted,
        status="running",
        result=None,
        logs=run_log_lines("En attente", submitted, at=submitted),
    )

    @asynccontextmanager
    async def transaction():
        """Keep the worker's short transaction lifecycle without requiring PostgreSQL."""
        yield

    db = SimpleNamespace(begin=transaction, get=AsyncMock(return_value=row))

    @asynccontextmanager
    async def sessions():
        """Return the same test row across heartbeat and finalization sessions."""
        yield db

    def generation(_snapshot: dict, _rules: dict, log, _stop) -> dict:
        """Produce native-like multiline output and optionally a terminal diagnostic."""
        log("Une étape\nUne autre étape")
        if outcome == "timeout":
            raise GenerationError("Délai atteint.", "timeout")
        return {"sessions": []}

    with patch("app.services.kholloscope_worker.generate", generation):
        await execute_run(SimpleNamespace(sessions=sessions), "run")
    assert row.status == outcome
    assert all(
        line.startswith("[") and line[3] == ":" and line[6] == ":" and line[10] == "]"
        for line in row.logs
    )
    assert any(line.endswith("Une étape") for line in row.logs)
    assert any(line.endswith("Une autre étape") for line in row.logs)
    assert any(line.endswith("Délai atteint.") for line in row.logs) == (outcome == "timeout")


def test_reference_timeout_preserves_budgets_of_later_stages(solver_input: dict) -> None:
    """Do not restart the whole reference search using reserved downstream time."""
    from unittest.mock import patch

    deadlines = []

    def search(*args, **kwargs):
        """Fail the first reference stage, then delegate to the actual placement solver."""
        if kwargs.get("template"):
            deadlines.append(args[6])
            if len(deadlines) == 1:
                raise GenerationError("Budget initial atteint.", "timeout")
        return solve_choices(*args, **kwargs)

    logs = []
    with patch("app.services.kholloscope_solver.solve_choices", search):
        with pytest.raises(GenerationError) as error:
            generate(solver_input, {"time_limit": 15}, logs.append, threading.Event())
    assert error.value.status == "timeout"
    assert len(deadlines) == 1


def test_reference_receives_global_deadline(solver_input: dict) -> None:
    """Let each criterion allocate its own share against the same global deadline."""
    import time
    from unittest.mock import patch

    deadlines = []

    def search(*args, **kwargs):
        """Observe the actual deadline while keeping the real coverage solver."""
        if kwargs.get("template"):
            deadlines.append(args[6] - time.monotonic())
        return solve_choices(*args, **kwargs)

    with patch("app.services.kholloscope_solver.solve_choices", search):
        generate(solver_input, {"time_limit": 1800}, lambda _: None, threading.Event())
    assert 1799 < deadlines[0] <= 1800


def test_ab_stability_wins_over_earlier_hours(solver_input: dict) -> None:
    """Prefer a shared nine o'clock room over an unmatched eight o'clock A session."""
    import time

    solver_input["subjects"] = [{"id": 1, "staff": [{"id": 1, "sessions": 2}]}]
    tasks = [{"id": str(t), "calendar_id": 1, "track": t, "subject_id": 1} for t in (1, 2)]
    shared = {"start": 32400, "end": 35700, "teacher_id": 1, "room_id": 1}
    choices = [
        [
            {**shared, "phase": 0, "day": "2026-09-07"},
            {**shared, "phase": 0, "day": "2026-09-07", "start": 28800, "end": 32100},
        ],
        [{**shared, "phase": 1, "day": "2026-09-14"}],
    ]
    result = solve_choices(
        solver_input,
        tasks,
        choices,
        GenerationRules(optimize=True),
        lambda _: None,
        threading.Event(),
        time.monotonic() + 5,
        template=True,
    )
    assert {s["start"] for s in result} == {32400}


@pytest.mark.parametrize("outcome", ["unknown", "optimal"])
def test_cancelled_native_search_never_retries_or_starts_another_stage(
    solver_input: dict, outcome: str
) -> None:
    """Release the worker instead of restarting CP-SAT after a stop request."""
    import time
    from unittest.mock import patch

    from ortools.sat.python import cp_model

    stop = threading.Event()
    solver_input["subjects"] = [{"id": 1, "staff": [{"id": 1, "sessions": 2}]}]
    tasks = [{"id": str(t), "calendar_id": 1, "track": t, "subject_id": 1} for t in (1, 2)]
    choices = [
        [{"day": day, "phase": phase, "start": 28800, "end": 32100, "teacher_id": 1, "room_id": 1}]
        for phase, day in enumerate(("2026-09-07", "2026-09-14"))
    ]

    def cancelled_solve(*args, **kwargs):
        """Emulate a stop arriving during a native solve, including a solution race."""
        stop.set()
        return cp_model.UNKNOWN if outcome == "unknown" else cp_model.OPTIMAL

    with patch.object(cp_model.CpSolver, "solve", side_effect=cancelled_solve) as search:
        with pytest.raises(GenerationError) as error:
            solve_choices(
                solver_input,
                tasks,
                choices,
                GenerationRules(optimize=True),
                lambda _: None,
                stop,
                time.monotonic() + 1800,
                template=True,
            )
    assert error.value.status == "cancelled"
    assert search.call_count == 1


@pytest.mark.asyncio
async def test_worker_releases_cancelled_generation_before_executing_next() -> None:
    """Observe persisted cancellation, join the solver thread, then run the next job."""
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.services.kholloscope_worker import execute_run

    rows = {
        name: SimpleNamespace(
            snapshot={"name": name},
            options={},
            created_at=datetime.now(timezone.utc),
            status="running",
            logs=[],
            result=None,
        )
        for name in ("old", "new")
    }
    started, stopped = threading.Event(), threading.Event()

    @asynccontextmanager
    async def transaction():
        """Model short worker transactions without PostgreSQL."""
        yield

    db = SimpleNamespace(
        begin=transaction, get=AsyncMock(side_effect=lambda _, key, **kw: rows[key])
    )

    @asynccontextmanager
    async def sessions():
        """Look up each run by identity, preserving the cancelled predecessor."""
        yield db

    def generation(snapshot, rules, log, stop):
        """Keep the first thread active until its persisted cancellation is observed."""
        if snapshot["name"] == "old":
            started.set()
            if not stop.wait(4):
                raise AssertionError("Cancellation was not delivered")
            stopped.set()
            raise GenerationError("Calcul annulé.", "cancelled")
        assert stopped.is_set()
        return {"sessions": []}

    with patch("app.services.kholloscope_worker.generate", generation):
        database = SimpleNamespace(sessions=sessions)
        active = asyncio.create_task(execute_run(database, "old"))
        while not started.is_set():
            await asyncio.sleep(0.01)
        rows["old"].status = "cancelled"
        await asyncio.wait_for(active, timeout=5)
        await asyncio.wait_for(execute_run(database, "new"), timeout=5)
    assert rows["old"].status == "cancelled"
    assert rows["old"].result is None
    assert rows["new"].status == "completed"


def test_early_hours_and_rotation_footprints_have_equal_weight() -> None:
    """One full relative hour-range gain trades equally with one shared subject slot."""
    from ortools.sat.python import cp_model

    from app.services.kholloscope_solver import template_preferences

    values = []
    for use_early in (0, 1):
        model = cp_model.CpModel()
        tasks = [{"calendar_id": 1, "subject_id": 1} for _ in range(2)]
        base = {"day": "2026-09-07", "phase": 0, "room_id": 1}
        choices = [
            [{**base, "teacher_id": 1, "start": h * 3600, "end": (h + 1) * 3600} for h in (8, 9)],
            [{**base, "teacher_id": 2, "start": 32400, "end": 36000}],
        ]
        xs = [
            [model.new_bool_var(f"x{i}_{j}") for j in range(len(opts))]
            for i, opts in enumerate(choices)
        ]
        for row in xs:
            model.add_exactly_one(row)
        model.add(xs[0][0] == use_early)
        model.minimize(template_preferences(model, tasks, choices, xs)[-1])
        solver = cp_model.CpSolver()
        assert solver.solve(model) == cp_model.OPTIMAL
        values.append(solver.objective_value)
    assert values == [2000, 2000]


def test_full_ten_group_rotation_repair_preserves_all_subject_phases(solver_input: dict) -> None:
    """Exercise real placement and constrained per-subject assignment at demo group size."""
    from app.services.kholloscope_assignment import repair_rotation

    solver_input["calendars"][0]["group_count"] = 10
    for subject in solver_input["subjects"]:
        subject["staff"][0]["sessions"] = 10
    result = generate(solver_input, {"time_limit": 15}, lambda _: None, threading.Event())
    mapping = [{"calendar_id": 1, "track": g, "group": g} for g in range(1, 11)]
    pupils = {(1, g): {g * 10 + n for n in range(3)} for g in range(1, 11)}
    assigned = repair_rotation(
        solver_input,
        result,
        mapping,
        "cycle",
        GenerationRules(),
        {
            "pupils": pupils,
            "pupil_calendars": {p: {1} for values in pupils.values() for p in values},
        },
    )
    validate_draft(
        solver_input,
        {**result, "sessions": assigned},
        GenerationRules(),
        coverage_tracks={s["id"]: s["track"] for s in result["sessions"]},
    )
    assert Counter((s["group"], s["subject_id"]) for s in assigned) == Counter(
        {(g, s): 2 for g in range(1, 11) for s in range(1, 5)}
    )


def test_optimized_reference_spreads_days_and_reuses_staff_slots_across_a_b(
    solver_input: dict,
) -> None:
    """Use four separate weekdays and matching staff weekday/time/room in both phases."""
    solver_input["selected_rooms"] = {str(s): [1, 2] for s in range(1, 5)}
    solver_input["capacities"]["2"] = 2
    solver_input["availability"] = {
        str(t): [{"weekday": d, "start": 28800, "end": 32400} for d in range(5)]
        for t in range(1, 5)
    }
    result = generate(
        solver_input, {"time_limit": 15, "optimize": True}, lambda _: None, threading.Event()
    )
    template = result["template"]
    for phase in (0, 1):
        sessions = [s for s in template if s["phase"] == phase]
        counts = Counter(date.fromisoformat(s["day"]).weekday() for s in sessions)
        assert sorted(counts.values()) == [1, 1, 1, 1]
    for teacher in range(1, 5):
        slots = {
            (date.fromisoformat(s["day"]).weekday(), s["start"], s["room_id"])
            for s in template
            if s["teacher_id"] == teacher
        }
        assert len(slots) == 1


def test_distribution_preferences_never_require_an_unavailable_weekday(solver_input: dict) -> None:
    """Optimization remains feasible when all staff can only work on Monday."""
    solver_input["availability"] = {
        str(t): [{"weekday": 0, "start": 28800, "end": 64800}] for t in range(1, 5)
    }
    result = generate(
        solver_input, {"time_limit": 10, "optimize": True}, lambda _: None, threading.Event()
    )
    assert result["sessions"]
    assert {date.fromisoformat(s["day"]).weekday() for s in result["sessions"]} == {0}


def test_optimized_ten_group_proposal_checks_anonymous_cycle_rotation(solver_input: dict) -> None:
    """Exercise the demo group count with the actual hierarchical objectives and witness."""
    solver_input["calendars"][0]["group_count"] = 10
    for subject in solver_input["subjects"]:
        subject["staff"][0]["sessions"] = 10
    logs = []
    result = generate(
        solver_input,
        {
            "time_limit": 30,
            "optimize": True,
            "time_stability_percent": 30,
            "time_rotation_percent": 50,
        },
        logs.append,
        threading.Event(),
    )
    assert len(result["template"]) == 40
    assert len(result["sessions"]) == 80
    assert any("Rotation abstraite réalisable" in line for line in logs)
    assert logs[-1].startswith("Terminé")
    assert result["mappings"] == []


def test_candidates_check_both_availability_and_existing_classes(solver_input: dict) -> None:
    """A declared free range never overrides a teacher course in another promotion."""
    c = {**solver_input["calendars"][0], "subject_id": 1}
    day = date(2026, 9, 7)
    solver_input["bookings"][day.isoformat()] = [
        {
            "start": 28800,
            "end": 64800,
            "teachers": [1],
            "room_id": 99,
            "calendar_id": 99,
            "kind": "course",
        }
    ]
    assert candidates(solver_input, c, 1, day) == []
    solver_input["bookings"] = {}
    solver_input["availability"]["1"] = []
    assert candidates(solver_input, c, 1, day) == []


def test_holiday_recovery_preserves_service_and_annual_volumes(solver_input: dict) -> None:
    """Close a later whole weekday, recover locally and never reduce annual group needs."""
    initial = generate(solver_input, {"time_limit": 15}, lambda _: None, threading.Event())
    target = next(s for s in initial["sessions"] if s["day"] >= "2026-09-21")
    snapshot = deepcopy(solver_input)
    snapshot["calendars"][0]["settings"]["holidays"] = [
        {"name": "Fermeture", "start": target["day"], "end": target["day"]}
    ]
    snapshot["pins"] = {s["id"]: s for s in initial["sessions"] if s["day"] != target["day"]}
    result = generate(snapshot, {"time_limit": 15}, lambda _: None, threading.Event())
    assert len(result["sessions"]) == len(initial["sessions"])
    assert not any(s["day"] == target["day"] for s in result["sessions"])
    assert Counter(s["teacher_id"] for s in result["sessions"]) == Counter(
        s["teacher_id"] for s in initial["sessions"]
    )


def test_staff_lunch_switch_never_disables_pupil_lunch(solver_input: dict) -> None:
    """Only the staff meal rule is optional; manual moves retain all pupil protections."""
    assert not free_lunch([(43200, 45000), (46800, 48600)], 43200, 50400, 3300)
    result = generate(solver_input, {"time_limit": 15}, lambda _: None, threading.Event())
    first = result["sessions"][0]
    other = result["sessions"][1]
    other.update(
        day=first["day"], start=first["start"], end=first["end"], teacher_id=first["teacher_id"]
    )
    with pytest.raises(GenerationError):
        validate_draft(solver_input, result, GenerationRules(teacher_lunch=False))


def test_impossible_service_and_cancellation_are_not_success(solver_input: dict) -> None:
    """Reject unbalanced commitments and honor cancellation before model construction."""
    solver_input["subjects"][0]["staff"][0]["sessions"] = 3
    with pytest.raises(GenerationError) as error:
        generate(solver_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert error.value.status == "infeasible"
    stop = threading.Event()
    stop.set()
    with pytest.raises(GenerationError) as error:
        generate(solver_input, {"time_limit": 5}, lambda _: None, stop)
    assert error.value.status == "cancelled"


def test_rounding_and_rule_validation() -> None:
    """Keep unrounded nominal means and reject unbounded solver requests."""
    assert annual_quota(750, "none") == 12.5
    assert annual_quota(750, "ceil") == 13
    assert annual_quota(750, "floor") == 12
    assert annual_quota(900, "none") == 15
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GenerationStart(expected_revision="a" * 64, rules={"time_limit": 43201})


@pytest.mark.parametrize("weeks_count", [3, 25])
def test_unrounded_odd_year_keeps_only_actual_ab_occurrences(
    solver_input: dict, weeks_count: int
) -> None:
    """Keep 12/13 sessions on 25 weeks without inventing a final B week.

    Parameters
    ----------
    solver_input, weeks_count
        Anonymous fixture and odd teaching-week count, including the PT demo period.

    Returns
    -------
    None
        Verifies exact phase-based coverage, rotation, and missing-session rejection.
    """
    from app.services.kholloscope_assignment import rotated_sessions

    calendar = solver_input["calendars"][0]
    first = date(2026, 9, 7)
    calendar["weeks"] = [
        {"start": (first + timedelta(weeks=n)).isoformat(), "days": 5} for n in range(weeks_count)
    ]
    calendar["period_end"] = (first + timedelta(weeks=weeks_count - 1, days=4)).isoformat()
    calendar["settings"]["end"] = calendar["period_end"]
    for subject in calendar["requirements"]:
        subject["minutes"] = weeks_count * 30
    result = generate(solver_input, {"time_limit": 15}, lambda _: None, threading.Event())
    counts = Counter((s["track"], s["subject_id"]) for s in result["sessions"])
    for session in result["template"]:
        expected = weeks_count // 2 + (session["phase"] == 0)
        assert counts[session["track"], session["subject_id"]] == expected
    assert len(result["sessions"]) == 4 * weeks_count
    assert all(q["cycle_based"] and not q["rounded"] for q in result["quotas"])
    assert all(q["min_sessions"] == weeks_count // 2 for q in result["quotas"])
    assert all(q["max_sessions"] == weeks_count // 2 + 1 for q in result["quotas"])
    last_week = calendar["weeks"][-1]["start"]
    assert sum(s["original_day"] >= last_week for s in result["sessions"]) == 4
    mapping = [{"calendar_id": 1, "track": t, "group": g} for t, g in [(1, 7), (2, 2)]]
    for mode in ("fixed", "cycle"):
        assigned = rotated_sessions(solver_input, result, mapping, mode)
        validate_draft(
            solver_input,
            {**result, "sessions": assigned},
            GenerationRules(),
            coverage_tracks={s["id"]: s["track"] for s in result["sessions"]},
        )
    invalid = deepcopy(result)
    invalid["sessions"].pop()
    with pytest.raises(GenerationError, match="volume annuel"):
        validate_draft(solver_input, invalid, GenerationRules())


def test_excessive_common_period_is_a_technical_limit(solver_input: dict) -> None:
    """An unsupported supercycle is not incorrectly reported as mathematical infeasibility."""
    solver_input["calendars"][0]["requirements"][0]["minutes"] = 1
    with pytest.raises(GenerationError, match="limite technique") as error:
        generate(solver_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert error.value.status == "failed"


def test_commitment_reference_periods_are_subject_specific() -> None:
    """Keep existing fortnight commitments while representing six-, ten- and annual waves."""
    calendars = [
        {
            "weeks": 30,
            "settings": {
                "subjects": [
                    {"subject_id": 1, "minutes": 900},
                    {"subject_id": 2, "minutes": 300},
                    {"subject_id": 3, "minutes": 180},
                ]
            },
        },
        {
            "weeks": 25,
            "settings": {
                "subjects": [
                    {"subject_id": 1, "minutes": 750},
                    {"subject_id": 4, "minutes": 180},
                ]
            },
        },
    ]
    assert service_cycles(calendars) == {1: 2, 2: 6, 3: 10, 4: 25}


@pytest.mark.parametrize("weeks_count,annual,period,commitment", [(30, 5, 6, 2), (25, 3, 25, 6)])
def test_sparse_subjects_use_evenly_spaced_group_waves(
    solver_input: dict, weeks_count: int, annual: int, period: int, commitment: int
) -> None:
    """Support five sessions every six weeks and three evenly distributed annual sessions."""
    calendar = solver_input["calendars"][0]
    first = date(2026, 9, 7)
    calendar["weeks"] = [
        {"start": (first + timedelta(weeks=n)).isoformat(), "days": 5} for n in range(weeks_count)
    ]
    calendar["period_end"] = (first + timedelta(weeks=weeks_count - 1, days=4)).isoformat()
    calendar["settings"]["end"] = calendar["period_end"]
    calendar["requirements"] = [{"subject_id": 1, "minutes": annual * 60}]
    solver_input["subjects"] = [{"id": 1, "staff": [{"id": 1, "sessions": commitment}]}]
    result = generate(solver_input, {"time_limit": 15}, lambda _: None, threading.Event())
    assert result["cycle_length"] == period
    assert len(result["sessions"]) == annual * 2
    for track in (1, 2):
        indices = sorted(
            (date.fromisoformat(s["original_day"]) - first).days // 7
            for s in result["sessions"]
            if s["track"] == track
        )
        assert indices[0] >= weeks_count // annual - 3
        assert all(
            b - a in {weeks_count // annual, math.ceil(weeks_count / annual)}
            for a, b in zip(indices, indices[1:], strict=False)
        )


def test_public_generation_hides_per_track_cycle_quotas() -> None:
    """Expose 12/13 bounds without exposing or mutating the internal proof tracks."""
    from types import SimpleNamespace

    from app.services.kholloscope_generation import KholloscopeGenerationService

    result = {
        "sessions": [{"id": "one", "track": 1}],
        "template": [{"id": "template", "track": 1}],
        "quotas": [{"sessions": 12.5, "track_sessions": {"1": 13, "2": 12}}],
        "assigned_sessions": [{"track": 1, "group": 7}],
    }
    row = SimpleNamespace(
        result=result,
        snapshot=None,
        id="run",
        status="completed",
        revision="draft",
        source_revision="source",
        options={},
        logs=[],
    )
    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    public = service.serialize(row, "source")
    assert "track_sessions" not in public["result"]["quotas"][0]
    assert "track" not in public["result"]["sessions"][0]
    assert "assigned_sessions" not in public["result"]
    assert result["quotas"][0]["track_sessions"] == {"1": 13, "2": 12}


def test_odd_subjects_use_the_balanced_service_without_breaking_weekly_load(
    solver_input: dict,
) -> None:
    """Four odd subject commitments produce two sessions each week, as shown in Service."""
    solver_input["calendars"][0]["group_count"] = 1
    for subject in solver_input["subjects"]:
        subject["staff"][0]["sessions"] = 1
    result = generate(solver_input, {"time_limit": 10}, lambda _: None, threading.Event())
    assert Counter(s["phase"] for s in result["template"]) == {0: 2, 1: 2}
    expected = {
        s["id"]: s["staff"][0]["sessions_a"] for s in balanced_service(solver_input["subjects"])
    }
    assert all(s["phase"] == (0 if expected[s["subject_id"]] else 1) for s in result["template"])


def test_demo_39_41_service_becomes_40_40_without_changing_wishes() -> None:
    """Keep the English commitments 10/5/5 while fixing the demonstrated 39/41 regression."""
    snapshot = {
        "subjects": [
            {
                "id": subject,
                "staff": [{"id": i, "sessions": count} for i, count in enumerate(counts, 1)],
            }
            for subject, counts in enumerate(([8, 4, 8], [4, 8, 8], [8, 4, 8], [10, 5, 5]), 1)
        ]
    }
    tasks = [
        {"calendar_id": 1, "track": group, "subject_id": subject}
        for group in range(1, 21)
        for subject in range(1, 5)
    ]
    validate_cycle_service(snapshot, tasks)
    staff = [p for s in balanced_service(snapshot["subjects"]) for p in s["staff"]]
    assert sum(p["sessions_a"] for p in staff) == 40
    assert sum(p["sessions_b"] for p in staff) == 40
    english = balanced_service(snapshot["subjects"])[3]["staff"]
    assert [(p["sessions_a"], p["sessions_b"]) for p in english] == [(5, 5), (2, 3), (3, 2)]


def test_cycle_service_accepts_odd_group_load_bounds() -> None:
    """A three-session group may use one/two sessions while service remains fixed."""
    snapshot = {"subjects": [{"id": 1, "staff": [{"id": 1, "sessions": 3}]}]}
    tasks = [{"calendar_id": 1, "track": 1, "subject_id": 1} for _ in range(3)]
    validate_cycle_service(snapshot, tasks)


@pytest.mark.parametrize("count", [3, 9])
def test_odd_service_matches_the_service_table(solver_input: dict, count: int) -> None:
    """A single odd commitment retains its displayed floor/ceil split."""
    solver_input["calendars"][0]["group_count"] = count // 3
    solver_input["calendars"][0]["requirements"] = [{"subject_id": 1, "minutes": 360}]
    solver_input["subjects"] = [{"id": 1, "staff": [{"id": 1, "sessions": count}]}]
    result = generate(
        solver_input,
        {"time_limit": 10, "balance_odd_cycles": True},
        lambda _: None,
        threading.Event(),
    )
    assert Counter(s["phase"] for s in result["template"]) == {0: count // 2, 1: (count + 1) // 2}
    assert len(result["sessions"]) == count * 2


def test_ab_inversion_is_not_a_launch_option() -> None:
    """Reject the removed API option while keeping persisted jobs readable."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GenerationRules.model_validate({"balance_odd_cycles": True})
    assert (
        "balance_odd_cycles"
        not in GenerationRules.from_saved_options({"balance_odd_cycles": True}).model_dump()
    )


def test_lunch_opt_out_is_limited_to_staff(solver_input: dict) -> None:
    """A teacher's fully occupied meal window is allowed only with explicit opt-out."""
    import time

    solver_input["bookings"]["2026-09-07"] = [
        {
            "calendar_id": 99,
            "teachers": [1],
            "start": 43200,
            "end": 46800,
            "room_id": 99,
            "kind": "course",
        }
    ]
    tasks = [{"id": "test", "calendar_id": 1, "track": 1, "subject_id": 1}]
    choices = [[{"day": "2026-09-07", "start": 46800, "end": 50100, "teacher_id": 1, "room_id": 1}]]
    with pytest.raises(GenerationError):
        solve_choices(
            solver_input,
            tasks,
            choices,
            GenerationRules(),
            lambda _: None,
            threading.Event(),
            time.monotonic() + 5,
            template=False,
        )
    assert solve_choices(
        solver_input,
        tasks,
        choices,
        GenerationRules(teacher_lunch=False),
        lambda _: None,
        threading.Event(),
        time.monotonic() + 5,
        template=False,
    )


def test_valid_noon_kholles_do_not_expand_local_repair_to_every_week(solver_input: dict) -> None:
    """Only an actual continuous-meal violation can make otherwise regular noon slots mobile."""
    sessions = [
        {
            "calendar_id": 1,
            "track": 1,
            "teacher_id": 1,
            "day": "2026-09-07",
            "start": 43200,
            "end": 46500,
        },
        {
            "calendar_id": 1,
            "track": 2,
            "teacher_id": 1,
            "day": "2026-09-07",
            "start": 46800,
            "end": 50100,
        },
    ]
    assert lunch_conflicts(solver_input, sessions[:1], GenerationRules()) == set()
    assert lunch_conflicts(solver_input, sessions, GenerationRules()) == {0, 1}
    assert lunch_conflicts(solver_input, sessions, GenerationRules(teacher_lunch=False)) == set()
    sessions[1].update(track=1, teacher_id=2)
    assert lunch_conflicts(solver_input, sessions, GenerationRules(teacher_lunch=False)) == {0, 1}


def test_model_size_limit_is_not_reported_as_infeasible() -> None:
    """A safety cap cannot be presented as a proof that no timetable exists."""
    import time

    with pytest.raises(GenerationError, match="ne prouve pas") as error:
        solve_choices(
            {},
            [],
            [[{}] * 250001],
            GenerationRules(),
            lambda _: None,
            threading.Event(),
            time.monotonic() + 5,
            template=False,
        )
    assert error.value.status == "failed"


def test_cross_promotion_room_capacity_is_not_a_teacher_override(solver_input: dict) -> None:
    """Shared rooms permit capacity-limited simultaneous kholles, never double-booked staff."""
    import time

    solver_input["calendars"].append({**solver_input["calendars"][0], "id": 2})
    tasks = [{"id": str(c), "calendar_id": c, "track": 1, "subject_id": 1} for c in (1, 2)]
    choices = [
        [{"day": "2026-09-07", "start": 28800, "end": 32100, "teacher_id": c, "room_id": 1}]
        for c in (1, 2)
    ]
    solver_input["capacities"]["1"] = 1
    with pytest.raises(GenerationError):
        solve_choices(
            solver_input,
            tasks,
            choices,
            GenerationRules(),
            lambda _: None,
            threading.Event(),
            time.monotonic() + 5,
            template=False,
        )
    solver_input["capacities"]["1"] = 2
    assert (
        len(
            solve_choices(
                solver_input,
                tasks,
                choices,
                GenerationRules(),
                lambda _: None,
                threading.Event(),
                time.monotonic() + 5,
                template=False,
            )
        )
        == 2
    )
    choices[1][0]["teacher_id"] = 1
    with pytest.raises(GenerationError):
        solve_choices(
            solver_input,
            tasks,
            choices,
            GenerationRules(),
            lambda _: None,
            threading.Event(),
            time.monotonic() + 5,
            template=False,
        )
