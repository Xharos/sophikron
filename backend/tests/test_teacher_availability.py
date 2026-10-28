"""Availability defaults, pause clipping and recurring future conflict diagnostics."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.teacher_availability import AvailabilitySave
from app.services.teacher_availability import (
    availability_warnings,
    effective_ranges,
    open_ranges,
    teaching_audience_label,
)
from app.services.timetable import TimetableService
from tests.test_timetable import settings


@pytest.mark.parametrize(
    "event, expected",
    [
        ({}, "Classe entière"),
        ({"target_kind": "halves", "target_number": 1}, "Demi-groupe A"),
        ({"target_kind": "thirds", "target_number": 3}, "Tiers de groupe Z"),
        ({"target_kind": "kholles", "target_number": 12}, "Groupe de khôlle 012"),
        ({"target_kind": "student", "target_user_id": 123}, "Séance individuelle"),
    ],
)
def test_teaching_audience_labels_omit_pupil_identities(event: dict, expected: str) -> None:
    """Expose group names consistently while leaving private recipient IDs out of labels."""
    assert teaching_audience_label(event) == expected


def test_default_availability_ignores_calendar_breaks_and_always_opens_saturday() -> None:
    """Use 8–19 Monday–Friday and 8–12 Saturday, with no recess or lunch exclusions."""
    rules = settings(day_end=61500)
    ranges = open_ranges(rules)
    assert ranges == [
        {"weekday": day, "start": 28800, "end": 43200 if day == 5 else 68400} for day in range(6)
    ]
    assert effective_ranges(None, rules) == ranges
    assert effective_ranges([], rules) == []


def test_explicit_ranges_merge_and_clip_to_the_fixed_staff_grid() -> None:
    """Keep noon and Saturday morning even if the calendar has pauses or closes Saturday."""
    result = effective_ranges(
        [
            {"weekday": 0, "start": 28000, "end": 45000},
            {"weekday": 0, "start": 30000, "end": 50000},
            {"weekday": 5, "start": 28800, "end": 50000},
        ],
        settings(),
    )
    assert result == [
        {"weekday": 0, "start": 28800, "end": 50000},
        {"weekday": 5, "start": 28800, "end": 43200},
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"weekday": 6},
        {"weekday": -1},
        {"start": 35000, "end": 30000},
        {"start": 28800, "end": 28800},
        {"start": True},
    ],
)
def test_availability_rejects_invalid_input(changes: dict) -> None:
    """Enforce strict numeric weekday and positive ordered interval bounds."""
    with pytest.raises(ValidationError):
        AvailabilitySave.model_validate(
            {"ranges": [{"weekday": 0, "start": 28800, "end": 35400, **changes}]}
        )


def event(day: str, *, series: str = "a", teacher: int = 1, **changes: object) -> dict:
    """Build an assigned session with stable recurrence identity and a Paris offset."""
    return {
        "id": f"{series}-{day}",
        "series_id": series,
        "conflict_key": series,
        "start": f"{day}T08:00:00+02:00",
        "end": f"{day}T08:55:00+02:00",
        "teacher_id": teacher,
        "teacher": "Professeur",
        "school_year": 2026,
        "title": "Mathématiques",
        "promotion_id": None,
        "room_id": None,
        **changes,
    }


def test_availability_warns_once_for_future_recurrence_and_checks_all_segments() -> None:
    """Ignore history and available segments, but detect any uncovered future teaching interval."""
    events = [event(day) for day in ("2026-09-07", "2026-09-14", "2026-09-21")]
    patterns = {(1, 2026): []}
    warnings = availability_warnings(events, patterns, date(2026, 9, 10))
    assert len(warnings) == 1 and "2026-09-14" in warnings[0]
    assert not availability_warnings(events[:1], patterns, date(2026, 9, 10))
    assert not availability_warnings(events, {}, date(2026, 9, 10))
    patterns[(1, 2026)] = [{"weekday": 0, "start": 28800, "end": 32100}]
    assert not availability_warnings(events, patterns, date(2026, 9, 10))
    later = event("2026-09-14", start="2026-09-14T10:10:00+02:00", end="2026-09-14T11:05:00+02:00")
    assert len(availability_warnings([events[1], later], patterns, date(2026, 9, 10))) == 1


def test_conflicts_group_recurring_pairs_and_keep_unrelated_problems() -> None:
    """Keep one diagnostic per conflicting resource and recurring pair after today's cutoff."""
    events = [
        event(day, series=series)
        for day in ("2026-09-07", "2026-09-14", "2026-09-21")
        for series in ("a", "b")
    ]
    warnings = TimetableService._conflicts(events, today=date(2026, 9, 10))
    assert len(warnings) == 1 and "2026-09-14" in warnings[0]
    assert not TimetableService._conflicts(events[:2], today=date(2026, 9, 10))
    assert (
        len(
            TimetableService._conflicts(
                events + [event("2026-09-21", series="c")], today=date(2026, 9, 10)
            )
        )
        == 3
    )


def test_class_conflicts_include_kholles_and_unassigned_agendas_but_not_disjoint_groups() -> None:
    """Use actual audiences and calendar identity even before assigning a promotion."""
    first = event("2026-09-07", calendar_id=1, teacher_id=None)
    second = event(
        "2026-09-07",
        series="b",
        calendar_id=1,
        teacher_id=None,
        kind="kholle",
        target_kind="kholles",
        target_number=2,
    )
    assert any("classe" in text for text in TimetableService._conflicts([first, second]))
    for kind in ("halves", "thirds", "kholles"):
        assert (
            TimetableService._conflicts(
                [
                    {**first, "target_kind": kind, "target_number": 1},
                    {**second, "target_kind": kind, "target_number": 2},
                ]
            )
            == []
        )
