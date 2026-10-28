"""Exact half-sessions, bounded school-week cycles and stable occurrence identities."""

import logging
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.core.http import SearchAccessLogFilter
from app.schemas.timetable import BlockFields, SeriesData, YearDocument, YearSettings
from app.services.errors import AuthError
from app.services.timetable_engine import (
    current_school_year,
    daily_slots,
    occurrences,
    segments,
    series_dates,
    teaching_weeks,
    validate_series,
)


def test_school_year_changes_at_september_first() -> None:
    """Use the academic boundary rather than a calendar's custom course dates."""
    assert current_school_year(date(2026, 8, 31)) == 2025
    assert current_school_year(date(2026, 9, 1)) == 2026
    assert current_school_year(date(2027, 1, 1)) == 2026


def settings(**changes: object) -> YearSettings:
    """Build a known Monday-to-Friday school term with realistic recess and lunch breaks."""
    return YearSettings.model_validate(
        {
            "start": "2026-09-07",
            "end": "2026-11-06",
            "day_start": 28800,
            "day_end": 61200,
            "session_minutes": 55,
            "breaks": [
                {"start": 35400, "end": 36600},
                {"start": 43200, "end": 46800},
                {"start": 53400, "end": 54600},
            ],
            **changes,
        }
    )


def series(**changes: object) -> SeriesData:
    """Build one whole-class Monday block spanning four teaching sessions."""
    return SeriesData.model_validate(
        {
            "id": "a" * 32,
            "lineage": "a" * 32,
            "starts_on": "2026-09-07",
            "start_slot": 0,
            "duration_slots": 8,
            "subject_id": 1,
            "teacher_id": 2,
            "room_id": 3,
            "interval": 1,
            **changes,
        }
    )


def test_exact_half_sessions_and_pause_splitting() -> None:
    """Keep 27m30s boundaries and render an 8h-to-noon logical block in two segments."""
    grid = settings()
    slots = daily_slots(grid)
    assert slots[0] == (28800, 30450)
    assert slots[1] == (30450, 32100)
    assert slots[4] == (36600, 38250)
    assert segments(series(), grid) == [(28800, 35400), (36600, 43200)]
    assert segments(series(start_slot=1, duration_slots=1), grid) == [(30450, 32100)]
    assert segments(series(duration_slots=10), grid)[-1] == (46800, 50100)
    with pytest.raises(AuthError):
        segments(series(start_slot=len(slots) - 1), grid)


def test_default_grid_restarts_at_self_closing_and_keeps_noon_sessions() -> None:
    """Anchor afternoon slots at 14:00 while allowing normal sessions during the self window."""
    grid = YearSettings(start=date(2026, 9, 1), end=date(2027, 6, 30))
    assert grid.day_start == 28800 and grid.day_end == 68100 and grid.session_minutes == 55
    assert [(pause.start, pause.end) for pause in grid.breaks] == [(35400, 36600), (57000, 58200)]
    slots = daily_slots(grid)
    afternoon = next(index for index, (start, _) in enumerate(slots) if start == 50400)
    noon = next(index for index, (start, _) in enumerate(slots) if start == 43200)
    assert segments(series(start_slot=afternoon, duration_slots=2), grid) == [(50400, 53700)]
    assert segments(series(start_slot=noon, duration_slots=2), grid) == [(43200, 46500)]
    parts = segments(series(start_slot=afternoon - 1, duration_slots=2), grid)
    assert sum(end - start for start, end in parts) == 3300
    assert len(parts) == 2


def test_free_times_preserve_seconds_and_do_not_skip_recess() -> None:
    """Expand exact custom hours independently of half-slots, including through a fixed pause."""
    grid = settings()
    custom = series(start_time=35113, end_time=37847, start_slot=0, duration_slots=2)
    assert segments(custom, grid) == [(35113, 37847)]
    events = occurrences(YearDocument(settings=grid, series=[custom]))
    assert events[0]["start"].startswith("2026-09-07T09:45:13")
    assert events[0]["end"].startswith("2026-09-07T10:30:47")
    assert events[0]["start_time"] == 35113 and events[0]["end_time"] == 37847


@pytest.mark.parametrize(
    "changes",
    [
        {"start_time": 30000},
        {"end_time": 33000},
        {"start_time": 33000, "end_time": 30000},
        {"start_time": True, "end_time": 33000},
    ],
)
def test_free_times_require_two_strict_ordered_boundaries(changes: dict) -> None:
    """Reject partial, reversed and non-integer custom schedules at the API boundary."""
    with pytest.raises(ValidationError):
        series(**changes)


@pytest.mark.parametrize("start,end", [(28000, 33000), (60000, 62000)])
def test_free_times_remain_inside_establishment_opening(start: int, end: int) -> None:
    """Keep exact placement subject to the same school opening and closing bounds."""
    with pytest.raises(AuthError):
        segments(series(start_time=start, end_time=end), settings())


def test_a_pause_inside_a_half_session_never_discards_teaching_minutes() -> None:
    """Carry unfinished half-sessions across arbitrary recess with exact teaching duration."""
    grid = settings(breaks=[{"start": 35100, "end": 36300}])
    slots = daily_slots(grid)
    assert slots[3] == (33750, 36600)
    parts = segments(series(duration_slots=4), grid)
    assert parts == [(28800, 35100), (36300, 36600)]
    assert sum(end - start for start, end in parts) == 4 * 1650


@pytest.mark.parametrize("length", [1, 2, 3])
@pytest.mark.parametrize("interval", [2, 3])
def test_vacations_suspend_teaching_cycles(length: int, interval: int) -> None:
    """Never advance an alternation during fully closed weeks, regardless of their count."""
    beginning = date(2026, 9, 14)
    resume = beginning + timedelta(weeks=length)
    grid = settings(holidays=[{"start": beginning, "end": resume - timedelta(days=1)}])
    weeks = teaching_weeks(grid)
    assert weeks[date(2026, 9, 7)] == 1
    assert weeks[resume] == 2
    dates = series_dates(series(interval=interval), grid)
    assert dates[0] == date(2026, 9, 7)
    assert dates[1] == resume + timedelta(weeks=interval - 1)


def test_partial_weeks_count_once_and_saturday_is_configurable() -> None:
    """Use teaching-week numbering rather than ISO parity, retaining partial school weeks."""
    grid = settings(start="2026-09-09")
    assert teaching_weeks(grid)[date(2026, 9, 7)] == 1
    saturday = series(starts_on="2026-09-12", interval=0)
    assert series_dates(saturday, grid) == []
    assert series_dates(saturday, grid.model_copy(update={"saturday": True})) == [date(2026, 9, 12)]


def test_exception_moves_only_one_occurrence_and_cancellation_preserves_others() -> None:
    """Preserve source UIDs across a move and cancel only the selected week's block."""
    original = series(duration_slots=2)
    document = YearDocument(settings=settings(), series=[original])
    before = occurrences(document)
    moved = BlockFields.model_validate(
        {
            key: value
            for key, value in {**original.model_dump(), "starts_on": date(2026, 9, 8)}.items()
            if key in BlockFields.model_fields
        }
    )
    original.exceptions = {date(2026, 9, 7): moved, date(2026, 9, 14): None}
    validate_series(original, document.settings)
    after = occurrences(document)
    assert after[0]["id"] == before[0]["id"]
    assert after[0]["start"].startswith("2026-09-08T08:00:00")
    assert len(after) == len(before) - 1
    assert not any(item["source_date"] == "2026-09-14" for item in after)


def test_local_times_survive_daylight_saving_change() -> None:
    """Keep an 8am school start when Europe's offset changes in late October."""
    events = occurrences(YearDocument(settings=settings(), series=[series(duration_slots=2)]))
    before = next(item for item in events if item["source_date"] == "2026-10-19")
    after = next(item for item in events if item["source_date"] == "2026-10-26")
    assert before["start"] == "2026-10-19T08:00:00+02:00"
    assert after["start"] == "2026-10-26T08:00:00+01:00"


@pytest.mark.parametrize(
    "changes",
    [
        {"day_end": 20000},
        {"end": "2028-12-31"},
        {"breaks": [{"start": 53400, "end": 47400}]},
        {"breaks": [{"start": 35400, "end": 37000}, {"start": 36000, "end": 38000}]},
        {"holidays": [{"start": "2026-10-20", "end": "2026-10-19"}]},
    ],
)
def test_invalid_settings_rejected(changes: dict) -> None:
    """Reject invalid annual periods and reversed/overlapping daily or holiday intervals."""
    with pytest.raises(ValidationError):
        settings(**changes)


def test_feed_tokens_redacted_from_access_logs() -> None:
    """Never retain a personal subscription capability in Uvicorn access-log arguments."""
    token = "sensitive" * 5
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("127.0.0.1", "GET", f"/api/v1/timetable/feed/{token}.ics?x=secret", "1.1", 200),
        None,
    )
    assert SearchAccessLogFilter().filter(record)
    assert token not in record.getMessage()
    assert "secret" not in record.getMessage()


@pytest.mark.parametrize("title", ["", " ", "\t\n"])
def test_subjectless_sessions_require_a_nonblank_title(title: str) -> None:
    """Reject empty labels even when whitespace would pass an ordinary required input."""
    with pytest.raises(ValidationError, match="intitulé personnalisé"):
        series(subject_id=None, title=title)


@pytest.mark.parametrize(
    "missing",
    [
        ("subject_id",),
        ("teacher_id",),
        ("room_id",),
        ("subject_id", "teacher_id"),
        ("subject_id", "room_id"),
        ("teacher_id", "room_id"),
        ("subject_id", "teacher_id", "room_id"),
    ],
)
def test_optional_references_are_retained_during_expansion(missing: tuple[str, ...]) -> None:
    """Allow every partial assignment without inventing a subject, room or teacher identity."""
    event = series(title="Réunion", **dict.fromkeys(missing))
    expanded = occurrences(YearDocument(settings=settings(), series=[event]))
    assert expanded
    assert all(item[field] is None for item in expanded for field in missing)


@pytest.mark.parametrize("field", ["subject_id", "teacher_id", "room_id"])
def test_optional_references_still_reject_zero_and_negative_ids(field: str) -> None:
    """Represent absence with null rather than an invalid foreign key sentinel."""
    for value in [0, -1]:
        with pytest.raises(ValidationError):
            series(title="Réunion", **{field: value})
