"""Real repair solves and independent historical, volume and merge protections."""

import threading
from copy import deepcopy
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.kholloscope_generation import GenerationRules
from app.schemas.kholloscope_revision import RevisionCreate
from app.schemas.timetable import SeriesData, YearDocument, YearSettings
from app.services.errors import AuthError
from app.services.kholloscope_revision import (
    check_boundary,
    membership_conflicts,
    merge_document,
    revision_group_problems,
    room_replacement_changes,
)
from app.services.kholloscope_revision_solver import (
    GenerationError,
    entitlement,
    future_service,
    generate_revision,
    revised_entitlement,
    validate_revision,
)
from app.services.kholloscope_versions import effective_metadata, effective_sessions
from app.services.timetable_engine import PARIS, occurrences
from app.services.timetable_occupancy import replacement_room_problem
from tests.support.solver import solver_input  # noqa: F401


def test_export_schedule_switches_only_on_effective_dates() -> None:
    """Exclude pending revisions from the exported annual version without losing history."""
    first, second, third = [{"room_id": 1}], [{"room_id": 2}], [{"room_id": 3}]
    result = {
        "assigned_sessions": third,
        "revision_versions": [
            {"effective_on": "2026-11-16", "before": {"assigned_sessions": first}},
            {"effective_on": "2026-11-23", "before": {"assigned_sessions": second}},
        ],
    }
    original = deepcopy(result)
    assert effective_sessions(result, date(2026, 11, 15)) == first
    assert effective_sessions(result, date(2026, 11, 16)) == second
    assert effective_sessions(result, date(2026, 11, 23)) == third
    assert result == original


def test_revision_warns_of_dashboard_group_reduction_without_reassigning_pupils() -> None:
    """Compare live group numbers with the published assignment, not just saved counts."""
    calendars = [{"id": 1, "name": "PT", "group_count": 15}]
    mappings = [{"calendar_id": 1, "group": number} for number in range(1, 16)]
    current = {1: set(range(1, 15))}
    problems = revision_group_problems(calendars, mappings, current)
    assert len(problems) == 1
    assert problems[0]["expected_count"] == 15
    assert problems[0]["actual_count"] == 14
    assert "15 groupes" in problems[0]["message"]
    assert "14 groupes" in problems[0]["message"]
    assert current == {1: set(range(1, 15))}
    assert revision_group_problems(calendars, mappings, {1: set(range(1, 16))}) == []
    assert revision_group_problems(calendars, mappings, {1: set(range(2, 17))})


def test_room_change_today_preserves_started_sessions_and_other_subjects() -> None:
    """Apply immediate corrections to future starts, retaining history and ongoing sessions."""
    now = datetime(2026, 11, 9, 9, 0, tzinfo=PARIS)
    base = {
        "calendar_id": 1,
        "subject_id": 1,
        "teacher_id": 1,
        "room_id": 1,
        "day": "2026-11-09",
        "start": 28800,
        "end": 32400,
        "group": 1,
    }
    sessions = [
        {**base, "id": "past", "day": "2026-11-02"},
        {**base, "id": "ongoing", "start": 30600, "end": 34200},
        {**base, "id": "starting", "start": 32400, "end": 36000},
        {**base, "id": "later", "start": 36000, "end": 39600},
        {**base, "id": "other", "subject_id": 2, "day": "2026-11-16"},
    ]
    original = deepcopy(sessions)
    changes = room_replacement_changes(sessions, {1}, 1, 2, date(2026, 11, 9), now)
    assert [c["before"]["id"] for c in changes] == ["later"]
    assert changes[0]["after"] == {**sessions[3], "room_id": 2}
    assert sessions == original


def test_membership_collision_warning_is_grouped_and_private() -> None:
    """Detect real shared-pupil conflicts across promotions once per recurring group pair."""
    base = {
        "kind": "kholle",
        "target_kind": "kholles",
        "target_number": 1,
        "calendar_id": 1,
        "start": "2026-11-09T08:00:00+01:00",
        "end": "2026-11-09T09:00:00+01:00",
    }
    events = [
        base,
        {**base, "calendar_id": 2},
        {**base, "start": "2026-11-16T08:00:00+01:00", "end": "2026-11-16T09:00:00+01:00"},
        {
            **base,
            "calendar_id": 2,
            "start": "2026-11-16T08:00:00+01:00",
            "end": "2026-11-16T09:00:00+01:00",
        },
    ]
    problems = membership_conflicts(events, {(1, 1): {123456}, (2, 1): {123456}})
    assert len(problems) == 1
    assert "123456" not in str(problems)
    assert membership_conflicts(events, {(1, 1): {123456}, (2, 1): {789012}}) == []


def test_room_replacement_checks_affected_windows_and_other_agendas() -> None:
    """Reject target-window capacity/course conflicts without blocking on unrelated dates."""
    now = datetime(2026, 11, 9, 7, 0, tzinfo=PARIS)
    first, last = datetime(2026, 11, 9, 8, tzinfo=PARIS), datetime(2026, 11, 9, 9, tzinfo=PARIS)
    event = {
        "kind": "kholle",
        "calendar_id": 1,
        "room_id": 2,
        "start": first.isoformat(),
        "end": last.isoformat(),
    }
    shared = {**event, "calendar_id": 2}
    assert replacement_room_problem([event, shared], 2, 2, [(first, last)], now) is None
    assert replacement_room_problem([event, shared], 2, 1, [(first, last)], now)
    assert "cours" in replacement_room_problem(
        [event, {**shared, "kind": "course"}], 2, 10, [(first, last)], now
    )
    unrelated = [
        {**shared, "start": "2026-11-16T08:00:00+01:00", "end": "2026-11-16T09:00:00+01:00"}
    ] * 5
    assert replacement_room_problem([event, *unrelated], 2, 1, [(first, last)], now) is None


@pytest.fixture
def revision_input(solver_input: dict) -> dict:  # noqa: F811
    """Model unequal acquired counts, a frozen second subject and a replacement teacher."""
    snapshot = deepcopy(solver_input)
    sessions = []
    for group in (1, 2):
        for day in ("2026-09-07", "2026-09-21"):
            sessions.append(
                {
                    "id": f"{group}:{day}",
                    "calendar_id": 1,
                    "subject_id": 1,
                    "teacher_id": 1,
                    "room_id": 1,
                    "day": day,
                    "original_day": day,
                    "start": 28800 + (group - 1) * 3300,
                    "end": 32100 + (group - 1) * 3300,
                    "group": group,
                    "track": group,
                }
            )
    sessions.append(
        {
            **sessions[2],
            "id": "fixed",
            "subject_id": 2,
            "teacher_id": 2,
            "day": "2026-09-22",
            "original_day": "2026-09-22",
        }
    )
    snapshot.update(
        revision_branch=True,
        effective_on="2026-09-14",
        subject_id=1,
        live_sessions=sessions,
        entitlement=deepcopy(sessions),
        group_pupils={"1:1": [11], "1:2": [12]},
        future_service={"1": {"1": 0, "3": 2}},
        allow_moves=False,
    )
    return snapshot


def test_replacement_preserves_slots_history_other_subjects_and_quotas(
    revision_input: dict,
) -> None:
    """Replace only future staff and preserve all actual groups, dates and annual totals."""
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert len(result["changes"]) == 2
    for change in result["changes"]:
        assert change["before"]["teacher_id"] == 1
        assert change["after"]["teacher_id"] == 3
        assert all(
            change["before"][k] == change["after"][k]
            for k in ("day", "start", "end", "room_id", "group")
        )
    annual = validate_revision(revision_input, result["sessions"], GenerationRules())
    assert entitlement(annual) == entitlement(revision_input["entitlement"])
    assert [s for s in annual if s["day"] < "2026-09-14"] == revision_input["live_sessions"][
        :1
    ] + revision_input["live_sessions"][2:3]
    assert next(s for s in annual if s["id"] == "fixed")["teacher_id"] == 2


def test_multi_subject_repair_and_retirement_preserve_all_history(revision_input: dict) -> None:
    """Repair shared resources jointly and remove only inactive-group future occurrences."""
    snapshot = revision_input
    snapshot["subject_ids"] = [1, 2]
    snapshot["retired_groups"] = ["1:2"]
    snapshot["entitlement"] = [
        s for s in snapshot["entitlement"] if s["day"] < snapshot["effective_on"] or s["group"] != 2
    ]
    snapshot["future_service"] = {"1": {"3": 1}, "2": {"2": 0}}
    result = generate_revision(snapshot, {"time_limit": 5}, lambda _: None, threading.Event())
    annual = validate_revision(snapshot, result["sessions"], GenerationRules())
    assert [s for s in annual if s["day"] < snapshot["effective_on"]] == [
        s for s in snapshot["live_sessions"] if s["day"] < snapshot["effective_on"]
    ]
    assert not any(s["group"] == 2 for s in result["sessions"])
    removed = [c for c in result["changes"] if c["after"] is None]
    assert len(removed) == 2
    assert all(c["before"]["day"] >= snapshot["effective_on"] for c in removed)


def test_multiple_subjects_are_reassigned_in_one_real_solve(revision_input: dict) -> None:
    """Enforce separate future service totals in a jointly solved proposal."""
    revision_input["subject_ids"] = [1, 2]
    revision_input["future_service"]["2"] = {"2": 1}
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert len(result["sessions"]) == 3
    assert {s["subject_id"] for s in result["sessions"]} == {1, 2}


def test_new_group_receives_only_remaining_cadence(revision_input: dict) -> None:
    """Create future entitlements without retroactively adding acquired sessions."""
    snapshot = revision_input
    snapshot["added_groups"] = [{"calendar_id": 1, "group": 3}]
    snapshot["subject_ids"] = [1, 2]
    snapshot["group_pupils"]["1:3"] = [13]
    snapshot["entitlement"] = revised_entitlement(
        snapshot, snapshot["entitlement"], snapshot["effective_on"]
    )
    added = [s for s in snapshot["entitlement"] if s["group"] == 3]
    assert len(added) == 2
    assert added[0]["day"] >= snapshot["effective_on"]
    snapshot["future_service"] = {"1": {"3": 3}, "2": {"2": 2}}
    result = generate_revision(snapshot, {"time_limit": 5}, lambda _: None, threading.Event())
    annual = validate_revision(snapshot, result["sessions"], GenerationRules())
    assert entitlement(annual) == entitlement(snapshot["entitlement"])
    assert not any(s["group"] == 3 and s["day"] < snapshot["effective_on"] for s in annual)


def test_effective_metadata_switches_on_boundary_and_restores_temporary_service() -> None:
    """Project current tabs independently of already-materialized future occurrences."""
    original = {"revision_wishes": {"1": {"1": 2}}, "revision_rooms": {"1": [1]}}
    result = {
        "revision_wishes": {"1": {"2": 2}},
        "revision_rooms": {"1": [2]},
        "assigned_sessions": [{"day": "2026-11-16", "room_id": 2}],
        "revision_versions": [
            {"id": "a", "effective_on": "2026-11-16", "return_on": "2026-11-30", "before": original}
        ],
    }
    unchanged = deepcopy(result)
    assert (
        effective_metadata(result, date(2026, 11, 15))["revision_wishes"]
        == original["revision_wishes"]
    )
    assert effective_metadata(result, date(2026, 11, 16))["revision_wishes"] == {"1": {"2": 2}}
    assert (
        effective_metadata(result, date(2026, 11, 30))["revision_wishes"]
        == original["revision_wishes"]
    )
    assert (
        effective_metadata(result, date(2026, 11, 15))["assigned_sessions"]
        == result["assigned_sessions"]
    )
    assert result == unchanged


def test_immediate_room_change_does_not_activate_future_service() -> None:
    """Resolve fields separately when an immediate room correction follows a future revision."""
    result = {
        "revision_wishes": {"1": {"2": 2}},
        "revision_rooms": {"1": [3]},
        "revision_versions": [
            {
                "id": "future",
                "effective_on": "2026-11-23",
                "before": {"revision_wishes": {"1": {"1": 2}}, "revision_rooms": {"1": [1]}},
            },
            {
                "id": "room",
                "effective_on": "2026-11-10",
                "fields": ["revision_rooms"],
                "before": {"revision_wishes": {"1": {"2": 2}}, "revision_rooms": {"1": [2]}},
            },
        ],
    }
    current = effective_metadata(result, date(2026, 11, 10))
    assert current["revision_wishes"] == {"1": {"1": 2}}
    assert current["revision_rooms"] == {"1": [3]}


def test_retired_group_removal_preserves_recurring_history() -> None:
    """Cancel only a future occurrence while keeping earlier ICS identities and statistics."""
    from tests.support.calendar import series, settings

    document = YearDocument(settings=settings(), series=[series(kind="kholle")])
    before = occurrences(document)
    target = next(e for e in before if e["source_date"] == "2026-09-21")
    updated = merge_document(document, [{"before": target, "after": None}])
    after = occurrences(updated)
    assert [e for e in after if e["source_date"] < "2026-09-21"] == [
        e for e in before if e["source_date"] < "2026-09-21"
    ]
    assert not any(e["source_date"] == "2026-09-21" for e in after)


def test_revision_can_retire_all_groups_without_losing_their_history(revision_input: dict) -> None:
    """An empty future plan remains a valid revision when all pupils have departed."""
    snapshot = revision_input
    snapshot["subject_ids"] = [1, 2]
    snapshot["retired_groups"] = ["1:1", "1:2"]
    snapshot["entitlement"] = [
        s for s in snapshot["entitlement"] if s["day"] < snapshot["effective_on"]
    ]
    snapshot["future_service"] = {"1": {"1": 0}, "2": {"2": 0}}
    result = generate_revision(snapshot, {"time_limit": 5}, lambda _: None, threading.Event())
    assert result["sessions"] == []
    assert len(result["changes"]) == 3
    assert validate_revision(snapshot, [], GenerationRules()) == snapshot["entitlement"]


def test_unequal_history_adds_only_the_missing_group_session(revision_input: dict) -> None:
    """A removed past occurrence requires an extra future session for that group alone."""
    revision_input["live_sessions"].pop(0)
    revision_input["future_service"]["1"]["3"] = 3
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    added = [c for c in result["changes"] if c["before"] is None]
    assert len(added) == 1 and added[0]["after"]["group"] == 1
    assert added[0]["after"]["day"] >= "2026-09-14"
    quotas = [q for q in result["quotas"] if q["subject_id"] == 1]
    assert [(q["group"], q["acquired"], q["remaining"], q["total"]) for q in quotas] == [
        (1, 0, 2, 2),
        (2, 1, 1, 2),
    ]


def test_movement_requires_explicit_permission(revision_input: dict) -> None:
    """A teacher unavailable on Monday cannot move sessions unless moves were authorized."""
    revision_input["availability"]["3"] = [{"weekday": 2, "start": 28800, "end": 64800}]
    with pytest.raises(GenerationError):
        generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    revision_input["allow_moves"] = True
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert all(c["after"]["day"] == "2026-09-23" for c in result["changes"])
    revision_input["allow_moves"] = False
    with pytest.raises(GenerationError, match="figé"):
        validate_revision(revision_input, result["sessions"], GenerationRules())


def test_move_permission_still_tries_frozen_slots_first(revision_input: dict) -> None:
    """Permission to move does not open the calendar when replacements fit existing slots."""
    revision_input["allow_moves"] = True
    logs = []
    result = generate_revision(revision_input, {"time_limit": 5}, logs.append, threading.Event())
    assert not any("ouverture des déplacements" in line for line in logs)
    assert all(c["before"]["start"] == c["after"]["start"] for c in result["changes"])


def test_shared_pupil_conflict_requires_repair_with_other_promotion_fixed(
    revision_input: dict,
) -> None:
    """Shared pupils cannot have simultaneous kholles in two promotions, even with free staff."""
    calendar = {**deepcopy(revision_input["calendars"][0]), "id": 2, "group_count": 1}
    revision_input["calendars"].append(calendar)
    revision_input["group_pupils"]["2:1"] = [11]
    frozen = {
        **deepcopy(revision_input["live_sessions"][1]),
        "id": "other-promotion",
        "calendar_id": 2,
        "subject_id": 2,
        "teacher_id": 4,
        "room_id": 2,
    }
    revision_input["capacities"]["2"] = 1
    revision_input["live_sessions"].append(frozen)
    revision_input["entitlement"].append(deepcopy(frozen))
    with pytest.raises(GenerationError):
        generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    revision_input["allow_moves"] = True
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert next(s for s in result["sessions"] if s["id"] == frozen["id"]) == frozen
    assert all(c["after"]["subject_id"] == 1 for c in result["changes"])
    validate_revision(revision_input, result["sessions"], GenerationRules())


def test_no_repair_can_sacrifice_a_group_or_another_subject(revision_input: dict) -> None:
    """Equal global totals cannot hide a missing session or changed real group."""
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    altered = deepcopy(result["sessions"])
    altered[0]["group"] = 2
    with pytest.raises(GenerationError, match="groupes"):
        validate_revision(revision_input, altered, GenerationRules())
    with pytest.raises(GenerationError, match="exactement"):
        validate_revision(revision_input, result["sessions"][:-1], GenerationRules())
    frozen = next(s for s in altered if s["id"] == "fixed")
    frozen["teacher_id"] = 4
    with pytest.raises(GenerationError):
        validate_revision(revision_input, altered, GenerationRules())


def test_cancel_and_missing_service_never_return_partial_proposals(revision_input: dict) -> None:
    """Cancellation and insufficient availability remain explicit failures."""
    stop = threading.Event()
    stop.set()
    with pytest.raises(GenerationError) as error:
        generate_revision(revision_input, {"time_limit": 5}, lambda _: None, stop)
    assert error.value.status == "cancelled"
    revision_input["availability"]["3"] = []
    with pytest.raises(GenerationError):
        generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    with pytest.raises(GenerationError):
        future_service(2, [{"user_id": 1, "sessions": 0}])
    assert future_service(5, [{"user_id": 1, "sessions": 1}, {"user_id": 2, "sessions": 1}]) == {
        "1": 3,
        "2": 2,
    }


def test_boundary_requires_an_unelapsed_paris_monday() -> None:
    """A branch cannot change an already started week, including DST boundaries."""
    check_boundary(date(2026, 10, 26), datetime(2026, 10, 25, 23, 59, tzinfo=PARIS))
    with pytest.raises(AuthError):
        check_boundary(date(2026, 10, 26), datetime(2026, 10, 26, 0, 0, tzinfo=PARIS))
    with pytest.raises(ValidationError):
        RevisionCreate(expected_source_revision="a" * 64, subject_id=1, effective_on="2026-09-15")


def test_temporary_leave_preserves_every_session_from_return(revision_input: dict) -> None:
    """Change only the leave period, including when the original teacher has no leave service."""
    revision_input["return_on"] = "2026-09-28"
    restored = {**revision_input["live_sessions"][1], "id": "return-session", "day": "2026-09-28"}
    revision_input["live_sessions"].append(restored)
    revision_input["entitlement"].append(deepcopy(restored))
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    assert next(s for s in result["sessions"] if s["id"] == restored["id"]) == restored
    assert len(result["changes"]) == 2
    assert all(c["after"]["day"] < "2026-09-28" for c in result["changes"])
    altered = deepcopy(result["sessions"])
    next(s for s in altered if s["id"] == restored["id"])["teacher_id"] = 3
    with pytest.raises(GenerationError, match="figé"):
        validate_revision(revision_input, altered, GenerationRules())


@pytest.mark.parametrize("return_on", ["2026-09-14", "2026-09-07", "2026-09-29"])
def test_invalid_return_dates_are_rejected(return_on: str) -> None:
    """Reject returns before departure, on departure, or on a partial week."""
    with pytest.raises(ValidationError):
        RevisionCreate(
            expected_source_revision="a" * 64,
            subject_id=1,
            effective_on="2026-09-14",
            return_on=return_on,
        )


def test_temporary_recovery_cannot_be_scheduled_after_return(revision_input: dict) -> None:
    """A missing quota must fit inside the absence rather than rewriting the return period."""
    revision_input["return_on"] = "2026-09-21"
    revision_input["live_sessions"].pop(0)
    revision_input["future_service"] = {"1": {"1": 0, "3": 1}}
    result = generate_revision(revision_input, {"time_limit": 5}, lambda _: None, threading.Event())
    added = [c["after"] for c in result["changes"] if c["before"] is None]
    assert len(added) == 1 and "2026-09-14" <= added[0]["day"] < "2026-09-21"


def test_merge_preserves_recurrence_history_and_ics_uid(revision_input: dict) -> None:
    """A future recurring occurrence is detached without rewriting past or unaffected sessions."""
    document = YearDocument(
        settings=YearSettings.model_validate(revision_input["calendars"][0]["settings"]),
        series=[
            SeriesData(
                id="a" * 32,
                lineage="a" * 32,
                starts_on="2026-09-07",
                start_slot=0,
                duration_slots=2,
                start_time=28800,
                end_time=32100,
                interval=1,
                subject_id=1,
                teacher_id=1,
                teacher_ids=[1],
                room_id=1,
                kind="kholle",
                target_kind="kholles",
                target_number=1,
            )
        ],
    )
    before = occurrences(document)
    source = next(s for s in before if s["source_date"] == "2026-09-21")
    after = {**revision_input["live_sessions"][1], "teacher_id": 3}
    updated = merge_document(document, [{"before": source, "after": after}])
    events = occurrences(updated)
    assert len(events) == len(before)
    assert next(e for e in events if e["source_date"] == "2026-09-07") == before[0]
    changed = next(e for e in events if e["teacher_id"] == 3)
    assert changed["id"] == source["id"]
    assert document.series[0].exceptions == {}
