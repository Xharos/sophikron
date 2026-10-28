"""Effective weekly replacements preserve history, cycle phases and independent exceptions."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.timetable import (
    BlockFields,
    SessionFields,
    TemplateBlock,
    TemplateSave,
    YearDocument,
)
from app.services.timetable import TimetableService, student_receives
from app.services.timetable_engine import occurrences, series_dates
from app.services.timetable_templates import apply_template, template_blocks, template_series
from tests.test_timetable import series, settings


def pattern(**changes: object) -> TemplateBlock:
    """Build a weekly template for the original Monday teaching block."""
    source = series()
    return TemplateBlock.model_validate(
        {
            **{name: getattr(source, name) for name in SessionFields.model_fields},
            "key": source.lineage,
            "weekday": 0,
            "interval": 1,
            "phase": 1,
            **changes,
        }
    )


def change(on: str, blocks: list[TemplateBlock]) -> TemplateSave:
    """Represent an administrator's complete version with a known optimistic revision."""
    return TemplateSave(expected_revision="0" * 32, effective_on=on, blocks=blocks)


def test_replacement_versions_keep_old_teacher_and_stable_uids() -> None:
    """Apply V2/V3 only after their dates while preserving earlier teachers and occurrence IDs."""
    original = YearDocument(settings=settings(), series=[series()])
    v2 = apply_template(original, change("2026-10-05", [pattern(teacher_id=8)]), adopt_legacy=True)
    v3 = apply_template(v2, change("2026-10-26", [pattern(teacher_id=9)]), adopt_legacy=False)
    events = occurrences(v3)
    assert {event["teacher_id"] for event in events if event["source_date"] < "2026-10-05"} == {2}
    assert {
        event["teacher_id"]
        for event in events
        if "2026-10-05" <= event["source_date"] < "2026-10-26"
    } == {8}
    assert {event["teacher_id"] for event in events if event["source_date"] >= "2026-10-26"} == {9}
    assert [event["id"] for event in events] == [event["id"] for event in occurrences(original)]
    assert original.series[0].until is None


def test_replacement_keeps_exceptions_cancellations_and_one_off_events() -> None:
    """Retain a replacement teacher, a cancelled lesson and a dated addition across versions."""
    source = series()
    replacement = BlockFields.model_validate(
        {name: getattr(source, name) for name in BlockFields.model_fields}
    )
    replacement.teacher_id = 7
    replacement.starts_on = date(2026, 10, 13)
    source.exceptions = {date(2026, 10, 12): replacement, date(2026, 10, 19): None}
    dated = series(id="b" * 32, lineage="b" * 32, starts_on="2026-10-08", interval=0)
    original = YearDocument(settings=settings(), series=[source, dated])
    changed = apply_template(
        original, change("2026-10-05", [pattern(teacher_id=8)]), adopt_legacy=True
    )
    events = occurrences(changed)
    assert not any(event["source_date"] == "2026-10-19" for event in events)
    assert any(
        event["teacher_id"] == 7 and event["start"].startswith("2026-10-13") for event in events
    )
    assert any(event["series_id"] == dated.id for event in events)
    old = next(event for event in occurrences(original) if event["teacher_id"] == 7)
    assert old["id"] in {event["id"] for event in events}
    removed = apply_template(original, change("2026-10-05", []), adopt_legacy=True)
    assert old["id"] in {event["id"] for event in occurrences(removed)}
    assert not any(
        event["source_date"] >= "2026-10-05"
        and event["teacher_id"] == 2
        and event["series_id"] != dated.id
        for event in occurrences(removed)
    )


def test_weekly_cycle_keeps_global_phase_after_midyear_replacement() -> None:
    """A phase-B lesson remains phase B even when the effective version starts in phase A."""
    item = template_series(pattern(interval=2, phase=2), settings(), date(2026, 9, 21))
    assert item is not None
    assert series_dates(item, settings())[0] == date(2026, 9, 28)
    assert item.cycle_phase == 2


def test_legacy_splits_recover_the_current_organization_once() -> None:
    """Recover the latest active block of a shared lineage instead of duplicating old versions."""
    earlier = series(until="2026-10-04")
    later = series(id="b" * 32, starts_on="2026-10-05", teacher_id=8)
    blocks = template_blocks(
        YearDocument(settings=settings(), series=[earlier, later]), date(2026, 10, 19)
    )
    assert len(blocks) == 1 and blocks[0].teacher_id == 8


def test_group_exports_use_current_membership_and_do_not_leak_individual_events() -> None:
    """Separate whole-class, group and personal access independently of the web selection."""
    assert student_receives({}, 42, set())
    assert student_receives({"target_kind": "halves", "target_number": 1}, 42, {("halves", 1)})
    assert not student_receives({"target_kind": "halves", "target_number": 2}, 42, {("halves", 1)})
    assert student_receives({"target_kind": "student", "target_user_id": 42}, 42, set())
    assert not student_receives({"target_kind": "student", "target_user_id": 43}, 42, set())


@pytest.mark.parametrize(
    "changes",
    [
        {"target_kind": "student"},
        {"target_kind": "halves"},
        {"target_kind": "promotion", "target_number": 1},
        {"interval": 2, "phase": 3},
    ],
)
def test_invalid_template_targets_and_phases_rejected(changes: dict) -> None:
    """Reject ambiguous targets and cycle phases outside the selected repetition."""
    with pytest.raises(ValidationError):
        pattern(**changes)


def test_precise_activation_replaces_ongoing_sessions_and_keeps_completed_uids() -> None:
    """At Tuesday 15:00 preserve the morning and replace the entire 14:00–16:00 session."""
    grid = settings(session_minutes=60, breaks=[], day_end=64800)
    sources = [
        series(
            id=letter * 32,
            lineage=letter * 32,
            starts_on="2026-09-08",
            start_slot=slot,
            duration_slots=4,
            template_key=letter * 32,
        )
        for letter, slot in (("a", 0), ("b", 12), ("c", 16))
    ]
    original = YearDocument(settings=grid, series=sources)
    blocks = [
        pattern(
            key=item.lineage, weekday=1, start_slot=item.start_slot, duration_slots=4, teacher_id=8
        )
        for item in sources
    ]
    updated = apply_template(
        original,
        TemplateSave(
            expected_revision="0" * 32, effective_at="2026-10-06T15:00:00+02:00", blocks=blocks
        ),
        adopt_legacy=False,
    )
    before, after = occurrences(original), occurrences(updated)
    historical = [event for event in before if event["end"] <= "2026-10-06T15:00:00+02:00"]
    assert {(event["id"], event["teacher_id"]) for event in historical}.issubset(
        {(event["id"], event["teacher_id"]) for event in after}
    )
    today = [event for event in after if event["source_date"] == "2026-10-06"]
    assert [(event["start"][11:16], event["teacher_id"]) for event in today] == [
        ("08:00", 2),
        ("14:00", 8),
        ("16:00", 8),
    ]
    again = apply_template(
        updated,
        TemplateSave(
            expected_revision="0" * 32,
            effective_at="2026-10-06T16:30:00+02:00",
            blocks=[block.model_copy(update={"teacher_id": 9}) for block in blocks],
        ),
        adopt_legacy=False,
    )
    events = occurrences(again)
    assert len({event["id"] for event in events}) == len(events)
    assert [
        (event["start"][11:16], event["teacher_id"])
        for event in events
        if event["source_date"] == "2026-10-06"
    ] == [("08:00", 2), ("14:00", 8), ("16:00", 9)]


def test_transition_moves_keep_both_completed_and_new_events_with_unique_uids() -> None:
    """Moving a completed lesson into the afternoon retains its morning history exactly once."""
    grid = settings(session_minutes=60, breaks=[], day_end=64800)
    original = YearDocument(
        settings=grid,
        series=[series(starts_on="2026-09-08", duration_slots=2, template_key="a" * 32)],
    )
    data = TemplateSave(
        expected_revision="0" * 32,
        effective_at="2026-10-06T15:00:00+02:00",
        blocks=[pattern(weekday=1, start_slot=16, duration_slots=2, teacher_id=8)],
    )
    updated = apply_template(original, data, adopt_legacy=False)
    events = [event for event in occurrences(updated) if event["source_date"] == "2026-10-06"]
    assert [event["start"][11:16] for event in events] == ["08:00", "16:00"]
    assert len({event["id"] for event in events}) == 2
    revised = apply_template(
        updated,
        data.model_copy(
            update={
                "effective_at": datetime.fromisoformat("2026-10-06T16:30:00+02:00"),
                "blocks": [data.blocks[0].model_copy(update={"teacher_id": 9})],
            }
        ),
        adopt_legacy=False,
    )
    assert [
        event["id"] for event in occurrences(revised) if event["source_date"] == "2026-10-06"
    ] == [event["id"] for event in events]


def test_new_version_wins_when_an_ongoing_lesson_overlaps_old_completed_work() -> None:
    """A newly extended session supersedes conflicting old sessions on its activation day."""
    grid = settings(session_minutes=60, breaks=[], day_end=64800)
    original = YearDocument(
        settings=grid,
        series=[
            series(duration_slots=4, template_key="a" * 32),
            series(
                id="b" * 32,
                lineage="b" * 32,
                start_slot=12,
                duration_slots=4,
                template_key="b" * 32,
            ),
        ],
    )
    updated = apply_template(
        original,
        TemplateSave(
            expected_revision="0" * 32,
            effective_at="2026-10-05T15:00:00+02:00",
            blocks=[pattern(key="b" * 32, start_slot=2, duration_slots=14, teacher_id=8)],
        ),
        adopt_legacy=False,
    )
    today = [event for event in occurrences(updated) if event["source_date"] == "2026-10-05"]
    assert len(today) == 1 and today[0]["teacher_id"] == 8
    assert today[0]["start"][11:16] == "09:00"


def test_legacy_kholles_remain_independent_of_new_weekly_versions() -> None:
    """Stop offering old khôlles in weekly editing without deleting their dated occurrences."""
    source = series(kind="kholle", template_key="a" * 32)
    original = YearDocument(settings=settings(), series=[source])
    assert template_blocks(original, date(2026, 10, 5)) == []
    updated = apply_template(original, change("2026-10-05", []), adopt_legacy=True)
    original_events, updated_events = occurrences(original), occurrences(updated)
    assert all(event["template_key"] == "a" * 32 for event in original_events)
    assert all(event["template_key"] is None for event in updated_events)
    assert [
        {key: value for key, value in event.items() if key != "template_key"}
        for event in updated_events
    ] == [
        {key: value for key, value in event.items() if key != "template_key"}
        for event in original_events
    ]
    assert updated.series[0].template_key is None


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "kholle"},
        {"target_kind": "student", "target_user_id": 42},
        {"target_kind": "kholles", "target_number": 1},
        {"target_kind": "halves", "target_number": 3},
        {"target_kind": "thirds", "target_number": 4},
    ],
)
def test_weekly_saves_reject_kholles_and_non_generic_audiences(changes: dict) -> None:
    """Enforce generic class/half/third recipients and forbid khôlles on the server."""
    with pytest.raises(ValidationError):
        change("2026-10-05", [pattern(**changes)])


def test_immediate_activation_retains_a_cancellation_and_a_move_to_another_day() -> None:
    """Preserve independent exceptions while giving the new pattern priority over an ongoing one."""
    grid = settings(session_minutes=60, breaks=[], day_end=64800)
    source = series(start_slot=12, duration_slots=4, template_key="a" * 32)
    moved = BlockFields(
        **{field: getattr(source, field) for field in SessionFields.model_fields},
        starts_on="2026-10-06",
    )
    source.exceptions = {date(2026, 10, 5): moved, date(2026, 10, 12): None}
    updated = apply_template(
        YearDocument(settings=grid, series=[source]),
        TemplateSave(
            expected_revision="0" * 32,
            effective_at="2026-10-05T15:00:00+02:00",
            blocks=[pattern(start_slot=12, duration_slots=4, teacher_id=8)],
        ),
        adopt_legacy=False,
    )
    events = occurrences(updated)
    assert any(
        event["start"].startswith("2026-10-06") and event["teacher_id"] == 2 for event in events
    )
    assert not any(event["source_date"] == "2026-10-12" for event in events)
    source.exceptions = {date(2026, 10, 5): None}
    updated = apply_template(
        YearDocument(settings=grid, series=[source]),
        TemplateSave(
            expected_revision="0" * 32,
            effective_at="2026-10-05T15:00:00+02:00",
            blocks=[pattern(start_slot=12, duration_slots=4, teacher_id=8)],
        ),
        adopt_legacy=False,
    )
    assert not any(event["source_date"] == "2026-10-05" for event in occurrences(updated))


def test_conflict_warnings_distinguish_disjoint_group_audiences() -> None:
    """Parallel halves can share a room; shared teaching staff still produce a conflict."""
    first = {
        "start": "2026-10-05T08:00:00+02:00",
        "end": "2026-10-05T10:00:00+02:00",
        "title": "A",
        "teacher_id": 1,
        "room_id": 1,
        "promotion_id": 1,
        "target_kind": "halves",
        "target_number": 1,
    }
    second = {**first, "title": "B", "teacher_id": 2, "room_id": 2, "target_number": 2}
    assert TimetableService._conflicts([first, second]) == []
    warnings = TimetableService._conflicts([first, {**second, "teacher_id": 1, "room_id": 1}])
    assert len(warnings) == 1 and "enseignant" in warnings[0]
    third = {**second, "target_kind": "thirds", "target_number": 1}
    groups = [
        {"promotion_id": 1, "kind": "halves", "number": 1, "student_ids": [1]},
        {"promotion_id": 1, "kind": "thirds", "number": 1, "student_ids": [2]},
    ]
    assert TimetableService._conflicts([first, third], groups) == []
    groups[1]["student_ids"] = [1]
    assert len(TimetableService._conflicts([first, third], groups)) == 1


def test_rooms_allow_two_halves_but_reject_whole_class_or_excess_capacity() -> None:
    """A room split in two supports two halves, but not a whole class or three halves."""
    first = {
        "start": "2026-10-05T08:00:00+02:00",
        "end": "2026-10-05T10:00:00+02:00",
        "title": "A",
        "teacher_id": 1,
        "room_id": 1,
        "promotion_id": 1,
        "target_kind": "halves",
        "target_number": 1,
    }
    second = {**first, "title": "B", "teacher_id": 2, "target_number": 2}
    assert TimetableService._conflicts([first, second]) == []
    whole = {**second, "target_kind": "promotion", "target_number": None}
    assert any("salle" in warning for warning in TimetableService._conflicts([first, whole]))
    assert any(
        "salle" in warning
        for warning in TimetableService._conflicts(
            [{**first, "target_kind": "promotion", "target_number": None}, whole]
        )
    )
    third = {**second, "title": "Autre promotion", "teacher_id": 3, "promotion_id": 2}
    assert any(
        "salle" in warning for warning in TimetableService._conflicts([first, second, third])
    )
