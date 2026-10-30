"""Annual totals, genuine pupil lunch intervals and retained vacation exceptions."""

from datetime import date

import pytest

from app.schemas.timetable import BlockFields, SeriesFields, YearDocument, YearSettings
from app.services.timetable_diagnostics import annual_diagnostics, largest_gap
from app.services.timetable_engine import apply_event_change, occurrences, series_dates
from tests.test_timetable import series, settings


def grid(**changes: object) -> YearSettings:
    """Build a four-week calendar with a two-hour self window and sixty-minute sessions."""
    return settings(
        **{
            "start": "2026-09-07",
            "end": "2026-10-02",
            "session_minutes": 60,
            "breaks": [],
            **changes,
        }
    )


def event(day: str, start: str, end: str, **changes: object) -> dict:
    """Build a real teaching segment with an optional group, subject or teaching type."""
    return {
        "start": f"{day}T{start}+02:00",
        "end": f"{day}T{end}+02:00",
        "subject_id": 1,
        "kind": "course",
        "target_kind": "promotion",
        **changes,
    }


def roster() -> list[dict]:
    """Return two pupils in one promotion with separate symbolic halves."""
    return [{"id": identifier, "roles": ["user"], "promotion_ids": [10]} for identifier in (1, 2)]


def groups() -> list[dict]:
    """Return opposite half-group memberships for the synthetic pupil roster."""
    return [
        {"promotion_id": 10, "kind": "halves", "number": number, "student_ids": [number]}
        for number in (1, 2)
    ]


def test_annual_replacement_and_later_makeup_preserve_the_weekly_average() -> None:
    """Use the full teaching year instead of extrapolating the selected week or a template."""
    sessions = [
        event("2026-09-07", "08:00:00", "09:00:00"),
        event("2026-09-14", "08:00:00", "09:00:00", subject_id=2),
        event("2026-09-21", "08:00:00", "09:00:00"),
        event("2026-09-28", "08:00:00", "10:00:00"),
    ]
    totals, _ = annual_diagnostics(sessions, grid(), roster(), groups(), 10, date(2026, 9, 1))
    maths = next(row for row in totals if row["subject_id"] == 1)
    assert maths["course"] == 4 and maths["weekly"]["course"] == 1
    other = next(row for row in totals if row["subject_id"] == 2)
    assert other["course"] == 1 and other["weekly"]["course"] == 0.25


def test_groups_can_eat_at_different_times_inside_the_same_self_window() -> None:
    """Keep one full free hour for each pupil even with opposite half-group noon classes."""
    sessions = [
        event("2026-09-07", "12:00:00", "13:00:00", target_kind="halves", target_number=1),
        event("2026-09-07", "13:00:00", "14:00:00", target_kind="halves", target_number=2),
    ]
    totals, issues = annual_diagnostics(sessions, grid(), roster(), groups(), 10, date(2026, 9, 1))
    assert totals[0]["course"] == 1
    assert not issues


def test_fragmented_lunch_is_critical_only_for_the_affected_actual_pupils() -> None:
    """Two free half-hours cannot replace a continuous hour; individual kholles count too."""
    sessions = [
        event(
            "2026-09-07",
            "12:30:00",
            "13:30:00",
            kind="kholle",
            target_kind="student",
            target_user_id=1,
        )
    ]
    _, issues = annual_diagnostics(sessions, grid(), roster(), groups(), 10, date(2026, 9, 1))
    assert len(issues) == 1 and issues[0]["severity"] == "critical"
    assert "1 élève(s)" in issues[0]["message"]
    assert largest_gap([(43200, 45000), (44000, 46800)], 43200, 50400) == 3600


def test_no_promotion_suppresses_lunch_checks_but_retains_symbolic_group_totals() -> None:
    """Prepare half-group events without inventing pupils or losing partition diagnostics."""
    sessions = [event("2026-09-07", "12:00:00", "14:00:00", target_kind="halves", target_number=1)]
    totals, issues = annual_diagnostics(sessions, grid(), [], [], None, date(2026, 9, 1))
    assert totals[0]["course"] == 1
    assert len(issues) == 1 and issues[0]["code"].startswith("balance-")


def test_holidays_can_hide_the_anchor_without_disabling_the_rest_of_a_series() -> None:
    """Resume an alternating series even after a vacation covers its original first week."""
    calendar = grid(holidays=[{"start": "2026-09-07", "end": "2026-09-13"}])
    dates = series_dates(series(interval=2), calendar)
    assert dates == [date(2026, 9, 14), date(2026, 9, 28)]


def test_hidden_dated_exception_reappears_when_vacations_are_removed() -> None:
    """Keep stored replacements unchanged while holiday edits hide and restore actual events."""
    source = series(duration_slots=2)
    replacement = BlockFields(
        starts_on=date(2026, 9, 8), start_slot=2, title="Moved", subject_id=None
    )
    source.exceptions = {date(2026, 9, 7): replacement}
    document = YearDocument(settings=grid(), series=[source])
    before = occurrences(document)
    document.settings = grid(holidays=[{"start": "2026-09-08", "end": "2026-09-08"}])
    assert len(occurrences(document)) == len(before) - 1
    document.settings = grid()
    assert occurrences(document) == before


@pytest.mark.parametrize("field", ["lunch_start", "lunch_end"])
def test_invalid_self_window_is_rejected(field: str) -> None:
    """Refuse a self window outside the day or too short for one session."""
    with pytest.raises(ValueError):
        grid(**{field: 47000 if field == "lunch_start" else 45000})


def test_future_edit_preserves_history_and_maps_exceptions_to_the_new_weekday() -> None:
    """Move following Mondays to Tuesdays while retaining a later independent replacement."""
    original = series(duration_slots=2)
    original.exceptions = {
        date(2026, 9, 21): BlockFields(
            starts_on=date(2026, 9, 23), start_slot=0, title="Independent replacement"
        )
    }
    document = YearDocument(settings=grid(), series=[original])
    block = SeriesFields(starts_on=date(2026, 9, 15), start_slot=2, title="Tuesday")
    changed = apply_event_change(document, original.id, date(2026, 9, 14), "future", block)
    events = occurrences(changed)
    assert events[0]["start"].startswith("2026-09-07T08:00")
    assert events[1]["start"].startswith("2026-09-15T09:00")
    assert any(
        event["start"].startswith("2026-09-23") and event["is_exception"] for event in events
    )
    assert original.until is None and len(document.series) == 1


def test_one_occurrence_edit_keeps_recurrence_and_round_trips_the_compact_document() -> None:
    """Change only a selected session and serialize no recurrence fields into its exception."""
    original = series(duration_slots=2)
    document = YearDocument(settings=grid(), series=[original])
    block = SeriesFields(starts_on=date(2026, 9, 15), start_slot=4, interval=2, title="Moved once")
    changed = apply_event_change(document, original.id, date(2026, 9, 14), "one", block)
    restored = YearDocument.model_validate(changed.model_dump(mode="json"))
    assert restored.series[0].interval == 1
    assert len(occurrences(restored)) == len(occurrences(document))
    assert set(restored.series[0].exceptions) == {date(2026, 9, 14)}


def test_future_cancellation_retains_only_earlier_occurrences() -> None:
    """Cancel from a chosen occurrence without deleting its earlier history."""
    original = series(duration_slots=2)
    document = YearDocument(settings=grid(), series=[original])
    changed = apply_event_change(document, original.id, date(2026, 9, 21), "future", None)
    assert [event["source_date"] for event in occurrences(changed)] == ["2026-09-07", "2026-09-14"]


def test_single_event_can_become_a_yearly_recurring_chain() -> None:
    """Apply newly selected recurrence fields when editing a previously unique event."""
    original = series(interval=0, duration_slots=2)
    document = YearDocument(settings=grid(), series=[original])
    before = occurrences(document)[0]
    repeated = apply_event_change(
        document,
        original.id,
        original.starts_on,
        "one",
        SeriesFields(
            starts_on=original.starts_on,
            title="Weekly",
            interval=1,
        ),
    )
    events = occurrences(repeated)
    assert len(events) == 4 and events[0]["id"] == before["id"]
    assert len(document.series) == 1 and document.series[0].interval == 0


@pytest.mark.parametrize("scope", ["one", "future"])
def test_detached_occurrence_is_immune_to_later_chain_changes(scope: str) -> None:
    """Changing week nine must preserve an independently edited week ten and its ICS identity."""
    original = series(duration_slots=2)
    document = YearDocument(settings=grid(end="2026-11-27"), series=[original])
    source_date = date(2026, 11, 9)
    original_event = next(
        event for event in occurrences(document) if event["source_date"] == source_date.isoformat()
    )
    detached = apply_event_change(
        document,
        original.id,
        source_date,
        "one",
        SeriesFields(
            starts_on=source_date,
            title="Independent German option",
            start_slot=4,
        ),
    )
    independent = next(
        event for event in occurrences(detached) if event["title"] == "Independent German option"
    )
    assert independent["id"] == original_event["id"]
    assert independent["series_id"] != original.id
    changed = apply_event_change(
        detached,
        original.id,
        date(2026, 11, 2),
        scope,
        SeriesFields(
            starts_on=date(2026, 11, 2),
            title="New future chain",
            start_slot=6,
        ),
    )
    week_ten = [event for event in occurrences(changed) if event["source_date"] == "2026-11-09"]
    assert week_ten == [independent]
    cancelled = apply_event_change(detached, original.id, date(2026, 11, 2), "future", None)
    assert independent in occurrences(cancelled)


def test_custom_audiences_affect_meals_and_hours_without_partition_imbalance() -> None:
    """An option can overlap standard partitions without being checked as a half or third."""
    custom = [{"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": [1]}]
    sessions = [event("2026-09-07", "12:00:00", "14:00:00", target_kind="custom", target_number=50)]
    totals, issues = annual_diagnostics(sessions, grid(), roster(), custom, 10, date(2026, 9, 1))
    assert totals[0]["course"] == 2
    assert totals[0]["weekly"]["course"] == 0.5
    assert [issue["code"] for issue in issues] == ["lunch-2026-09-07"]
    assert "1 élève" in issues[0]["message"]


@pytest.mark.parametrize("subject_id", [1, 99])
def test_custom_only_subject_counts_hours_for_its_option_pupils(subject_id: int) -> None:
    """Count a weekly option for its participants, independently of the full class size or name."""
    pupils = [
        {"id": identifier, "roles": ["user"], "promotion_ids": [10]} for identifier in range(1, 46)
    ]
    custom = [
        {"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": list(range(1, 11))}
    ]
    sessions = [
        event(
            day,
            "08:00:00",
            "09:00:00",
            subject_id=subject_id,
            target_kind="custom",
            target_number=50,
        )
        for day in ("2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28")
    ]
    totals, _ = annual_diagnostics(sessions, grid(), pupils, custom, 10, date(2026, 9, 1))
    assert totals[0]["course"] == totals[0]["total"] == 4
    assert totals[0]["weekly"]["course"] == totals[0]["weekly"]["total"] == 1


def test_option_pupils_are_the_union_of_referenced_custom_groups() -> None:
    """Count overlapping pupils once and exclude unrelated or out-of-roster memberships."""
    custom = [
        {"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": [1, 999]},
        {"promotion_id": 10, "kind": "custom", "number": 51, "student_ids": [1, 2]},
        {"promotion_id": 10, "kind": "custom", "number": 52, "student_ids": [3]},
    ]
    pupils = [*roster(), {"id": 3, "roles": ["user"], "promotion_ids": [10]}]
    sessions = [
        event("2026-09-07", "08:00:00", "09:00:00", target_kind="custom", target_number=50),
        event("2026-09-14", "08:00:00", "09:00:00", target_kind="custom", target_number=51),
    ]
    totals, _ = annual_diagnostics(sessions, grid(), pupils, custom, 10, date(2026, 9, 1))
    assert totals[0]["total"] == 1.5
    assert totals[0]["weekly"]["total"] == 0.375


@pytest.mark.parametrize(
    "kind,number,user", [("promotion", None, None), ("halves", 1, None), ("student", None, 2)]
)
def test_mixed_subjects_keep_class_weighting(
    kind: str, number: int | None, user: int | None
) -> None:
    """Treat an extra custom-group session as a supplement when the subject has other audiences."""
    custom = [{"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": [1]}]
    sessions = [
        event("2026-09-07", "08:00:00", "09:00:00", target_kind="custom", target_number=50),
        event(
            "2026-09-14",
            "08:00:00",
            "09:00:00",
            target_kind=kind,
            target_number=number,
            target_user_id=user,
        ),
    ]
    totals, _ = annual_diagnostics(
        sessions, grid(), roster(), [*groups(), *custom], 10, date(2026, 9, 1)
    )
    assert totals[0]["total"] == (1.5 if kind == "promotion" else 1)


def test_hidden_common_blocks_prevent_option_classification() -> None:
    """Keep the full-class scope when a retained common session is hidden."""
    custom = [{"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": [1]}]
    blocks = [
        series(interval=0, target_kind="custom", target_number=50, duration_slots=2),
        series(starts_on=date(2026, 9, 8), interval=0, duration_slots=2),
    ]
    calendar = grid(holidays=[{"start": "2026-09-08", "end": "2026-09-08"}])
    events = occurrences(YearDocument(settings=calendar, series=blocks))
    assert len(events) == 1
    totals, _ = annual_diagnostics(events, calendar, roster(), custom, 10, date(2026, 9, 1), blocks)
    assert totals[0]["total"] == 0.5
    assert totals[0]["weekly"]["total"] == 0.125


def test_missing_option_pupils_keep_zero_hours_and_a_warning() -> None:
    """Do not invent optional teaching hours when its custom audience is no longer in the roster."""
    custom = [{"promotion_id": 10, "kind": "custom", "number": 50, "student_ids": [999]}]
    sessions = [event("2026-09-07", "08:00:00", "09:00:00", target_kind="custom", target_number=50)]
    totals, issues = annual_diagnostics(sessions, grid(), roster(), custom, 10, date(2026, 9, 1))
    assert totals[0]["total"] == totals[0]["weekly"]["total"] == 0
    assert [issue["code"] for issue in issues] == ["missing-custom-50"]


def test_cycle_information_is_attached_to_the_related_balance_issue() -> None:
    """Show incomplete alternation alongside its actual annual imbalance only once."""
    original = series(target_kind="thirds", target_number=1, interval=3, duration_slots=2)
    document = YearDocument(settings=grid(), series=[original])
    _, issues = annual_diagnostics(
        occurrences(document), grid(), roster(), [], None, date(2026, 9, 1), [original]
    )
    assert len(issues) == 1 and issues[0]["cycles"] == [3]
    assert [group["label"] for group in issues[0]["groups"]] == ["X", "Y", "Z"]
