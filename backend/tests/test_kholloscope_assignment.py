"""Real calendar removal, dated rotation and deny-by-default kholloscope capabilities."""

from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.kholloscope_generation import GenerationRules
from app.schemas.timetable import YearDocument
from app.services.errors import AuthError
from app.services.kholle import KholleService
from app.services.kholloscope_assignment import remove_kholles, repair_rotation, rotated_sessions
from app.services.kholloscope_solver import GenerationError, overlaps
from app.services.timetable_engine import occurrences
from tests.test_timetable import series, settings


@pytest.mark.asyncio
async def test_generation_confirmation_persists_only_after_revision_and_rights_checks() -> None:
    """Save a proposal explicitly, retaining it unchanged when editable checks reject it."""
    from contextlib import asynccontextmanager

    from app.schemas.kholloscope_generation import DraftVersion
    from app.services.kholloscope_generation import KholloscopeGenerationService, generation_saved

    @asynccontextmanager
    async def transaction() -> AsyncIterator[None]:
        """Isolate confirmation persistence from database connectivity."""
        yield

    row = SimpleNamespace(result={"mappings": [], "sessions": []}, revision="a" * 32)
    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    service.db = SimpleNamespace(begin=transaction)
    service.auth = SimpleNamespace(_lifecycle_lock=AsyncMock())
    service.editable = AsyncMock(return_value=row)
    actor = SimpleNamespace(id=1)
    data = DraftVersion(expected_revision="a" * 32)
    assert not generation_saved(row.result)
    response = await service.save(actor, 2026, data)
    service.editable.assert_awaited_once_with(actor, 2026, data.expected_revision)
    assert row.result["saved"] and generation_saved(row.result)
    assert response["revision"] == row.revision != data.expected_revision
    for status in (403, 409):
        service.editable = AsyncMock(side_effect=AuthError(status, "Refus"))
        original = deepcopy(row.result)
        with pytest.raises(AuthError):
            await service.save(actor, 2026, data)
        assert row.result == original
    assert generation_saved({"mappings": [{"group": 7}]})
    assert generation_saved({"applied": True})


@pytest.mark.asyncio
async def test_publication_revalidates_the_saved_preview_without_recomputing_rotation() -> None:
    """A repaired assignment must be published exactly as previewed, not solved again."""
    from app.services.kholloscope_generation import KholloscopeGenerationService

    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    service.verify_memberships = AsyncMock()
    saved = [{"id": "one", "track": 1, "group": 7}]
    row = SimpleNamespace(
        options={},
        snapshot={},
        result={
            "sessions": [{"id": "one", "track": 1}],
            "assigned_sessions": saved,
        },
    )
    mapping = [{"calendar_id": 1, "track": 1, "group": 7}]
    with (
        patch("app.services.kholloscope_solver.validate_draft"),
        patch(
            "app.services.kholloscope_generation.rotated_sessions",
            side_effect=AssertionError("recomputed"),
        ),
    ):
        assigned = await service.resolve_assignment(
            row, 2026, mapping, "cycle", preserve_saved=True
        )
    assert assigned == saved and assigned is not saved
    service.verify_memberships.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_rotation_also_searches_for_annual_diversity() -> None:
    """Optimize rotating assignments even when the ideal diagonal has no resource conflict."""
    from app.services.kholloscope_generation import KholloscopeGenerationService

    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    service.verify_memberships = AsyncMock()
    service.assignment_context = AsyncMock(return_value={"pupils": {}})
    mapping = [{"calendar_id": 1, "track": 1, "group": 7}]
    source = [{"id": "one", "track": 1}]
    preferred = [{"id": "one", "track": 1, "group": 7}]
    row = SimpleNamespace(options={}, snapshot={}, result={"sessions": source})
    with (
        patch("app.services.kholloscope_solver.validate_draft") as validator,
        patch("app.services.kholloscope_generation.rotated_sessions", return_value=preferred),
        patch(
            "app.services.kholloscope_generation.repair_rotation", return_value=preferred
        ) as search,
    ):
        assigned = await service.resolve_assignment(row, 2026, mapping, "cycle")
    service.assignment_context.assert_awaited_once_with(2026, mapping)
    search.assert_called_once()
    validator.assert_called_once()
    assert assigned == preferred
    service.verify_memberships.assert_awaited_once()


@pytest.mark.parametrize("scope,remaining", [("future", 2), ("all", 0)])
def test_removal_keeps_courses_and_preserves_history(scope: str, remaining: int) -> None:
    """Remove recurring kholles by their actual date and leave the course series untouched."""
    cfg = settings(start="2026-09-07", end="2026-10-02", holidays=[])
    kholle = series(kind="kholle", starts_on="2026-09-07", interval=1, duration_slots=2)
    course = series(id="b" * 32, lineage="b" * 32, starts_on="2026-09-07", interval=1)
    document = YearDocument(settings=cfg, series=[kholle, course])
    original = document.model_dump()
    updated, removed = remove_kholles(document, date(2026, 9, 14), scope)
    assert document.model_dump() == original
    assert course in updated.series
    assert len([e for e in occurrences(updated) if e["kind"] == "kholle"]) == remaining
    assert removed == 4 - remaining
    before = {e["id"] for e in occurrences(document) if e["start"][:10] <= "2026-09-14"}
    after = {e["id"] for e in occurrences(updated)}
    if scope == "future":
        assert before <= after


def test_removal_uses_moved_dates_and_preserves_non_kholle_exceptions() -> None:
    """A future source moved to the past survives; a past source moved forward is removed."""
    from app.schemas.timetable import BlockFields

    cfg = settings(start="2026-09-07", end="2026-10-02", holidays=[])
    kholle = series(kind="kholle", starts_on="2026-09-07", interval=1, duration_slots=2)
    fields = kholle.model_dump(
        exclude={"id", "lineage", "exceptions", "uid_lineage", "uid_date", "interval", "until"}
    )
    kholle.exceptions = {
        date(2026, 9, 7): BlockFields(**{**fields, "starts_on": "2026-09-25"}),
        date(2026, 9, 21): BlockFields(**{**fields, "starts_on": "2026-09-10"}),
        date(2026, 9, 28): BlockFields(**{**fields, "kind": "course", "starts_on": "2026-09-28"}),
    }
    updated, removed = remove_kholles(
        YearDocument(settings=cfg, series=[kholle]), date(2026, 9, 14), "future"
    )
    events = occurrences(updated)
    assert removed == 1
    assert {e["start"][:10] for e in events} == {"2026-09-10", "2026-09-14", "2026-09-28"}
    assert next(e for e in events if e["start"][:10] == "2026-09-28")["kind"] == "course"


@pytest.mark.parametrize(
    "mode,expected", [("fixed", [2, 2, 2, 2]), ("weekly", [2, 5, 2, 5]), ("cycle", [2, 2, 5, 5])]
)
def test_rotations_use_eligible_weeks_and_original_recovery_dates(
    mode: str, expected: list[int]
) -> None:
    """Rotate sparse actual group numbers without advancing during vacation weeks."""
    weeks = ["2026-09-07", "2026-09-14", "2026-09-28", "2026-10-05"]
    snapshot = {"calendars": [{"id": 1, "weeks": [{"start": w} for w in weeks]}]}
    sessions = [
        {
            "id": f"{track}-{i}",
            "calendar_id": 1,
            "track": track,
            "subject_id": 1,
            "original_day": w,
            "day": "2026-09-15" if i == 0 else w,
        }
        for track in (1, 2)
        for i, w in enumerate(weeks)
    ]
    original = deepcopy(sessions)
    mapping = [{"calendar_id": 1, "track": i + 1, "group": g} for i, g in enumerate([2, 5])]
    assigned = rotated_sessions(snapshot, {"sessions": sessions}, mapping, mode)
    assert [s["group"] for s in assigned if s["id"].startswith("1-")] == expected
    assert sessions == original


def test_rotation_rejects_a_broken_subject_alternation() -> None:
    """A weekly permutation must not give one group the same subject twice per fortnight."""
    snapshot = {
        "calendars": [{"id": 1, "weeks": [{"start": "2026-09-07"}, {"start": "2026-09-14"}]}]
    }
    sessions = [
        {"calendar_id": 1, "track": track, "subject_id": 1 + ((track + week) % 2), "day": day}
        for week, day in enumerate(["2026-09-07", "2026-09-14"])
        for track in (1, 2)
    ]
    mapping = [{"calendar_id": 1, "track": n, "group": n} for n in (1, 2)]
    assigned = rotated_sessions(snapshot, {"sessions": sessions}, mapping, "weekly")
    assert [s["track"] for s in assigned] == [s["track"] for s in sessions]


def test_natural_partial_cycle_does_not_allow_broken_complete_cycles() -> None:
    """Allow final A-week redistribution while preserving every full A/B cycle."""
    weeks = ["2026-09-07", "2026-09-14", "2026-09-21"]
    snapshot = {"calendars": [{"id": 1, "weeks": [{"start": w} for w in weeks]}]}
    sessions = [
        {"calendar_id": 1, "track": track, "subject_id": 1 + ((track + week) % 2), "day": day}
        for week, day in enumerate(weeks)
        for track in (1, 2)
    ]
    mapping = [{"calendar_id": 1, "track": n, "group": n} for n in (1, 2)]
    result = {
        "sessions": sessions,
        "quotas": [{"calendar_id": 1, "subject_id": s, "cycle_based": True} for s in (1, 2)],
    }
    assigned = rotated_sessions(snapshot, result, mapping, "cycle")
    assert [s["group"] for s in assigned if s["day"] == weeks[-1]] == [1, 2]
    assert [s["track"] for s in rotated_sessions(snapshot, result, mapping, "weekly")] == [
        s["track"] for s in sessions
    ]


def test_cycle_rotation_exchanges_only_identical_week_phases() -> None:
    """Keep group one's maths on weeks 1/3/5 while allowing compatible teachers to rotate."""
    weeks = ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
    snapshot = {"calendars": [{"id": 1, "weeks": [{"start": w} for w in weeks]}]}
    sessions = [
        {"calendar_id": 1, "track": track, "subject_id": 1, "day": day, "teacher_id": track}
        for index, day in enumerate(weeks)
        for track in (1, 2, 3, 4)
        if index % 2 == (track - 1) % 2
    ]
    mapping = [{"calendar_id": 1, "track": t, "group": t} for t in (1, 2, 3, 4)]
    assigned = rotated_sessions(snapshot, {"sessions": sessions}, mapping, "cycle")
    assert [s["day"] for s in assigned if s["group"] == 1] == [weeks[0], weeks[2]]
    assert [s["teacher_id"] for s in assigned if s["group"] == 1] == [1, 3]


def test_rotation_interleaves_pairs_before_repeating_an_examiner() -> None:
    """Visit three teacher/room pairs before another time of the first pair."""
    from datetime import timedelta

    first = date(2026, 9, 7)
    weeks = [(first + timedelta(weeks=w)).isoformat() for w in range(8)]
    snapshot = {"calendars": [{"id": 1, "weeks": [{"start": w} for w in weeks]}]}
    sessions = [
        {
            "id": f"{w}-{t}",
            "calendar_id": 1,
            "subject_id": 1,
            "track": t,
            "teacher_id": teacher,
            "room_id": teacher,
            "day": w,
            "start": (7 + t) * 3600,
        }
        for w in weeks[::2]
        for t, teacher in enumerate((1, 1, 2, 3), 1)
    ]
    mapping = [{"calendar_id": 1, "track": t, "group": t} for t in range(1, 5)]
    assigned = rotated_sessions(snapshot, {"sessions": sessions}, mapping, "cycle")
    assert [s["teacher_id"] for s in assigned if s["group"] == 1] == [1, 2, 3, 1]


def test_anonymous_verification_observes_cancellation() -> None:
    """Cancellation of generation must also stop its final anonymous assignment check."""
    import threading

    from ortools.sat.python import cp_model

    from app.services.kholloscope_assignment import solve_assignment

    stop = threading.Event()
    stop.set()
    with pytest.raises(GenerationError) as error:
        solve_assignment(cp_model.CpSolver(), cp_model.CpModel(), stop)
    assert error.value.status == "cancelled"


def test_group_descends_all_five_subject_slots_despite_other_subject_patterns() -> None:
    """G10 must visit all five odd-week maths slots, not a whole-program subset of two."""
    from datetime import timedelta

    first = date(2026, 9, 7)
    weeks = [(first + timedelta(weeks=w)).isoformat() for w in range(10)]
    snapshot = {"calendars": [{"id": 1, "weeks": [{"start": w} for w in weeks]}]}
    mapping = [
        {"calendar_id": 1, "track": t, "group": g} for t, g in enumerate([10, 1, 3, 5, 8], 1)
    ]
    sessions = [
        {
            "calendar_id": 1,
            "subject_id": 1,
            "track": t,
            "day": (first + timedelta(weeks=w, days=t - 1)).isoformat(),
            "start": 43200,
            "teacher_id": 100 + t,
            "room_id": t,
        }
        for w in range(0, 10, 2)
        for t in range(1, 6)
    ]
    # Each group has a different other-subject signature: this used to prevent maths rotation.
    sessions += [
        {"calendar_id": 1, "subject_id": 10 + t, "track": t, "day": weeks[1], "start": 43200}
        for t in range(1, 6)
    ]
    assigned = rotated_sessions(snapshot, {"sessions": sessions}, mapping, "cycle")
    maths = [s for s in assigned if s["subject_id"] == 1 and s["group"] == 10]
    assert [s["teacher_id"] for s in maths] == [101, 102, 103, 104, 105]
    assert [(date.fromisoformat(s["day"]) - first).days // 7 for s in maths] == [0, 2, 4, 6, 8]


def test_subject_rotation_repairs_conflicts_and_foreign_pupil_courses() -> None:
    """Prefer the +1 diagonal but change the minimum assignments needed for safe groups."""
    from datetime import timedelta

    first = date(2026, 9, 7)
    days = [(first + timedelta(weeks=w)).isoformat() for w in range(4)]
    snapshot = {
        "calendars": [
            {
                "id": 1,
                "weeks": [{"start": d} for d in days],
                "settings": {"session_minutes": 60, "lunch_start": 43200, "lunch_end": 50400},
            }
        ],
        "bookings": {},
    }
    mapping = [{"calendar_id": 1, "track": t, "group": t} for t in range(1, 5)]
    sessions = []
    for track in range(1, 5):
        for w in range(4):
            if w % 2 == 0:
                sessions.append(
                    {
                        "id": f"math-{track}-{w}",
                        "calendar_id": 1,
                        "subject_id": 1,
                        "track": track,
                        "day": days[w],
                        "start": (track + 7) * 3600,
                        "end": (track + 8) * 3600,
                    }
                )
            if w % 2 == (0 if track in (1, 3) else 1):
                start = (10 if track in (1, 2) else 9) * 3600
                sessions.append(
                    {
                        "id": f"physics-{track}-{w}",
                        "calendar_id": 1,
                        "subject_id": 2,
                        "track": track,
                        "day": days[w],
                        "start": start,
                        "end": start + 3600,
                    }
                )
    result = {"sessions": sessions}
    desired = rotated_sessions(snapshot, result, mapping, "cycle")
    conflicting = [s for s in desired if s["group"] == 1 and s["day"] == days[2]]
    assert len(conflicting) == 2 and conflicting[0]["start"] == conflicting[1]["start"]
    snapshot["bookings"][days[2]] = [{"calendar_id": 99, "start": 32400, "end": 36000}]
    context = {"pupils": {(1, 1): {42}}, "pupil_calendars": {42: {99}}}
    assigned = repair_rotation(snapshot, result, mapping, "cycle", GenerationRules(), context)
    for group in range(1, 5):
        for day in days:
            values = [s for s in assigned if s["group"] == group and s["day"] == day]
            assert len(values) <= 2
            for i, left in enumerate(values):
                for right in values[i + 1 :]:
                    assert not overlaps(left["start"], left["end"], right["start"], right["end"])
    assert not any(
        s["group"] == 1 and s["day"] == days[2] and s["start"] == 32400 for s in assigned
    )
    assert [s["id"] for s in assigned] == [s["id"] for s in sessions]
    for subject in (1, 2):
        for group in range(1, 5):
            assert sorted(
                s["day"] for s in assigned if s["subject_id"] == subject and s["group"] == group
            ) == sorted(
                s["day"] for s in sessions if s["subject_id"] == subject and s["track"] == group
            )
    with pytest.raises(GenerationError):
        repair_rotation(snapshot, result, mapping, "cycle", GenerationRules(max_per_day=1), context)


def test_annual_diversity_and_exposures_take_priority_over_the_ideal_diagonal() -> None:
    """Distribute every accessible teacher/room fairly despite a pupil's foreign course."""
    from collections import Counter
    from datetime import timedelta

    first = date(2026, 9, 7)
    weeks = [(first + timedelta(weeks=w)).isoformat() for w in range(12)]
    snapshot = {
        "calendars": [
            {"id": 1, "weeks": [{"start": w} for w in weeks], "settings": {"session_minutes": 60}}
        ],
        "bookings": {w: [{"calendar_id": 99, "start": 32400, "end": 36000}] for w in weeks[::2]},
    }
    sessions = [
        {
            "id": f"math-{w}-{track}",
            "calendar_id": 1,
            "subject_id": 1,
            "track": track,
            "teacher_id": track,
            "room_id": track,
            "day": w,
            "start": (track + 7) * 3600,
            "end": (track + 8) * 3600,
        }
        for w in weeks[::2]
        for track in range(1, 4)
    ]
    mapping = [{"calendar_id": 1, "track": t, "group": t} for t in range(1, 4)]
    assigned = repair_rotation(
        snapshot,
        {"sessions": sessions},
        mapping,
        "cycle",
        GenerationRules(),
        {"pupils": {(1, 1): {42}}, "pupil_calendars": {42: {99}}},
    )
    for group in range(1, 4):
        counts = Counter((s["teacher_id"], s["room_id"]) for s in assigned if s["group"] == group)
        assert len(counts) == (2 if group == 1 else 3)
        if group == 1:
            assert sorted(counts.values()) == [3, 3]
        assert sorted(s["day"] for s in assigned if s["group"] == group) == weeks[::2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles,permissions,write,allowed",
    [
        ({"admin"}, {"kholloscope.read"}, False, True),
        ({"admin"}, {"kholloscope.read"}, True, False),
        ({"admin"}, {"kholloscope.read", "kholloscope.write"}, True, True),
        ({"admin"}, {"users.manage"}, False, False),
        ({"teacher"}, {"kholloscope.read", "kholloscope.write"}, False, False),
    ],
)
async def test_explicit_permissions_still_require_admin(
    roles: set[str], permissions: set[str], write: bool, allowed: bool
) -> None:
    """Keep future read capability separate from today's administrator role gate."""
    auth = SimpleNamespace(
        db=None,
        _actor=AsyncMock(return_value=SimpleNamespace(is_bootstrap=False)),
        repo=SimpleNamespace(
            permissions=AsyncMock(return_value=tuple(permissions)),
            roles=AsyncMock(return_value=tuple(roles)),
        ),
    )
    service = KholleService(auth)
    with patch("app.services.timetable.TimetableService.authorize", AsyncMock(return_value=True)):
        if allowed:
            assert await service.authorize(SimpleNamespace(id=1), write=write)
        else:
            with pytest.raises(AuthError):
                await service.authorize(SimpleNamespace(id=1), write=write)


@pytest.mark.asyncio
async def test_only_active_promotions_enter_kholloscope_preparation() -> None:
    """Exclude inactive promotion agendas while keeping unassigned prerequisites visible."""
    auth = SimpleNamespace(db=SimpleNamespace(scalars=AsyncMock(return_value=[1])))
    service = KholleService(auth)
    active = SimpleNamespace(id=1, promotion_id=1)
    inactive = SimpleNamespace(id=2, promotion_id=2)
    unassigned = SimpleNamespace(id=3, promotion_id=None)
    service.repo.calendars = AsyncMock(return_value=[active, inactive, unassigned])
    assert await service.active_calendars(2026) == [active, unassigned]
