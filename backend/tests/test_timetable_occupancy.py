"""Complete roster coverage, simultaneous calendars and weekly projection of dated sources."""

from app.schemas.timetable import BlockFields, YearDocument
from app.services.teacher_availability import effective_ranges
from app.services.timetable_engine import occurrences
from app.services.timetable_occupancy import fully_occupied_ranges
from tests.test_timetable import series, settings


def event(
    day: str = "2026-09-07", start: str = "08:00:00", end: str = "09:00:00", **fields: object
) -> dict:
    """Build a minimal local teaching segment with an optional specific audience."""
    return {"start": f"{day}T{start}+02:00", "end": f"{day}T{end}+02:00", **fields}


def test_empty_calendars_never_prove_complete_occupancy() -> None:
    """Distinguish no calendars, an empty calendar and unknown pupil audiences."""
    assert fully_occupied_ranges({}, {}, {}) == []
    assert fully_occupied_ranges({1: []}, {}, {}) == []
    assert fully_occupied_ranges({1: [event()], 2: []}, {}, {}) == []
    assert fully_occupied_ranges({1: [event(target_kind="halves", target_number=1)]}, {}, {}) == []
    assert fully_occupied_ranges({1: [event()]}, {}, {}) == [
        {"weekday": 0, "start": 28800, "end": 32400}
    ]


def test_half_groups_require_every_actual_pupil_and_ignore_overlapping_duplicates() -> None:
    """Count pupils by identity instead of adding event counts or nominal group weights."""
    pupils = {1: {11, 12, 13, 14}}
    groups = {1: {("halves", 1): {11, 12}, ("halves", 2): {13, 14}}}
    first = event(target_kind="halves", target_number=1)
    second = event(start="08:30:00", end="09:30:00", target_kind="halves", target_number=2)
    assert fully_occupied_ranges({1: [first, first]}, pupils, groups) == []
    assert fully_occupied_ranges({1: [first, first, second]}, pupils, groups) == [
        {"weekday": 0, "start": 30600, "end": 32400}
    ]
    pupils[1].add(15)
    assert fully_occupied_ranges({1: [first, second]}, pupils, groups) == []


def test_cross_partition_groups_and_individual_lessons_use_the_union_of_recipients() -> None:
    """Overlapping halves/thirds cannot cover a pupil outside all their audiences."""
    pupils = {1: {1, 2, 3, 4, 5, 6}}
    groups = {1: {("halves", 1): {1, 2, 3}, ("thirds", 1): {1, 4}, ("kholles", 1): {2, 5}}}
    sessions = [
        event(target_kind=kind, target_number=1) for kind in ("halves", "thirds", "kholles")
    ]
    assert fully_occupied_ranges({1: sessions}, pupils, groups) == []
    sessions.append(event(target_kind="student", target_user_id=6))
    assert fully_occupied_ranges({1: sessions}, pupils, groups) == [
        {"weekday": 0, "start": 28800, "end": 32400}
    ]


def test_all_calendars_must_be_full_at_the_same_date_and_time() -> None:
    """A free half class or an occupation on another day/week leaves potential pupils free."""
    pupils = {1: {1, 2}, 2: {3, 4}}
    groups = {2: {("halves", 1): {3}, ("halves", 2): {4}}}
    first = event()
    second = event(start="08:30:00", end="10:00:00", target_kind="halves", target_number=1)
    assert fully_occupied_ranges({1: [first], 2: [second]}, pupils, groups) == []
    for day in ("2026-09-12", "2026-09-14"):
        assert fully_occupied_ranges({1: [first], 2: [event(day)]}, pupils, groups) == []
    assert fully_occupied_ranges(
        {1: [first], 2: [event(start="08:30:00", end="10:00:00")]}, pupils, groups
    ) == [{"weekday": 0, "start": 30600, "end": 32400}]


def test_alternating_weeks_and_dated_exceptions_project_to_anonymous_weekly_ranges() -> None:
    """One full occurrence suffices; cancellations and moved replacements stay effective."""
    source = series(interval=2, duration_slots=2)
    document = YearDocument(settings=settings(end="2026-09-18"), series=[source])
    assert fully_occupied_ranges({1: occurrences(document)}, {}, {}) == [
        {"weekday": 0, "start": 28800, "end": 32100}
    ]
    source.exceptions = {source.starts_on: None}
    assert fully_occupied_ranges({1: occurrences(document)}, {}, {}) == []
    replacement = BlockFields.model_validate(
        {**source.model_dump(include=set(BlockFields.model_fields)), "starts_on": "2026-09-08"}
    )
    source.exceptions = {source.starts_on: replacement}
    assert fully_occupied_ranges({1: occurrences(document)}, {}, {}) == [
        {"weekday": 1, "start": 28800, "end": 32100}
    ]


def test_split_sessions_preserve_breaks_seconds_and_union_overlapping_weekly_ranges() -> None:
    """Retain exact half sessions without hatching pauses, closed Saturdays or out-of-hours."""
    document = YearDocument(settings=settings(), series=[series(start_slot=1)])
    result = effective_ranges(
        fully_occupied_ranges({1: occurrences(document)}, {}, {}), document.settings
    )
    assert result[:2] == [
        {"weekday": 0, "start": 30450, "end": 35400},
        {"weekday": 0, "start": 36600, "end": 43200},
    ]
    raw = fully_occupied_ranges(
        {
            1: [
                event(start="08:00:00", end="10:30:00"),
                event("2026-09-14", start="09:00:00", end="11:00:00"),
                event("2026-09-12"),
            ]
        },
        {},
        {},
    )
    assert effective_ranges(raw, settings()) == [
        {"weekday": 0, "start": 28800, "end": 35400},
        {"weekday": 0, "start": 36600, "end": 39600},
    ]
