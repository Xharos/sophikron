"""Available kholle weeks and exact per-group requirements."""

import pytest
from pydantic import ValidationError

from app.schemas.kholle import (
    KholleSettings,
    KholleSubjectRooms,
    KholleTeacherPreference,
    KholleWishEntry,
    KholleWishesSave,
)
from app.schemas.timetable import RoomSave, YearSettings
from app.services.kholle import kholle_weeks
from app.services.kholloscope_workflow import promotion_preference_effective


def test_balanced_service_is_stable_and_preserves_every_exact_commitment() -> None:
    """Reordering or renaming staff cannot change the fixed split shown to administrators."""
    from copy import deepcopy

    from app.services.kholloscope_service import balanced_service

    source = [{"id": 4, "staff": [{"id": i, "sessions": n} for i, n in enumerate([10, 5, 5], 1)]}]
    original = deepcopy(source)
    result = balanced_service(source)
    assert source == original
    reverse = balanced_service([{**source[0], "staff": list(reversed(source[0]["staff"]))}])
    assert {p["id"]: p for p in result[0]["staff"]} == {p["id"]: p for p in reverse[0]["staff"]}
    for p in result[0]["staff"]:
        assert p["sessions_a"] + p["sessions_b"] == p["sessions"]
        assert abs(p["sessions_a"] - p["sessions_b"]) <= 1
    incomplete = balanced_service([{"id": 1, "staff": [{"id": 1, "sessions": None}]}])
    assert incomplete[0]["staff"][0]["sessions_a"] is None


@pytest.mark.parametrize("changed", ["volumes", "wishes", "service"])
def test_preparation_requires_a_current_saved_prefix(changed: str) -> None:
    """A stale confirmation invalidates and locks all subsequent steps until reconfirmed."""
    from app.services.kholloscope_workflow import preparation_states

    steps = ["volumes", "wishes", "service"]
    stored = dict.fromkeys(steps, "saved")
    keys = {s: "changed" if s == changed else "saved" for s in steps}
    validated, review, available = preparation_states(stored, keys, dict.fromkeys(steps, []))
    index = steps.index(changed)
    assert validated == {s: i < index for i, s in enumerate(steps)}
    assert review == {s: i >= index for i, s in enumerate(steps)}
    assert available == {s: i <= index for i, s in enumerate(steps)}


def test_invalidating_saved_volumes_does_not_mark_untouched_steps_for_review() -> None:
    """Never-confirmed descendants stay locked/not done instead of claiming reconfirmation."""
    from app.services.kholloscope_workflow import preparation_states

    steps = ["volumes", "wishes", "service"]
    validated, review, available = preparation_states(
        {"volumes": "old"}, dict.fromkeys(steps, "new"), dict.fromkeys(steps, [])
    )
    assert validated == dict.fromkeys(steps, False)
    assert review == {"volumes": True, "wishes": False, "service": False}
    assert available == {"volumes": True, "wishes": False, "service": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_volume_save_preserves_or_invalidates_downstream_validation(changed: bool) -> None:
    """Ignore equivalent subject order but invalidate later milestones after a real edit."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.schemas.kholle import KholleSave
    from app.services.kholle import KholleService

    settings = {
        "start": "2026-09-07",
        "end": "2026-09-11",
        "subjects": [{"subject_id": 2, "minutes": 60}, {"subject_id": 1, "minutes": 90}],
    }
    calendar = SimpleNamespace(promotion_id=1, revision="a" * 32, kholle_settings=settings)
    year = SimpleNamespace(
        revision="b" * 32,
        school_year=2026,
        settings={
            "start": "2026-09-07",
            "end": "2026-09-11",
            "day_start": 28800,
            "day_end": 68400,
            "session_minutes": 55,
            "saturday": False,
            "breaks": [],
            "holidays": [],
        },
    )
    stored = {
        "volumes": "v",
        "wishes": "w",
        "service": "s",
        "rooms": [1],
        "teacher_preferences": [2],
    }
    workflow = SimpleNamespace(data=stored.copy(), revision="c" * 32)
    db = MagicMock()
    db.scalar = AsyncMock(return_value=calendar)
    db.scalars = AsyncMock(return_value=[1, 2])
    db.get = AsyncMock(return_value=workflow)
    auth = SimpleNamespace(db=db, _lifecycle_lock=AsyncMock())
    service = KholleService(auth)
    service._calendar = AsyncMock()
    service.repo.years = AsyncMock(return_value=[year])
    service.repo.published_kholloscope = AsyncMock(return_value=None)
    proposed = {
        **settings,
        "subjects": [
            {"subject_id": 1, "minutes": 120 if changed else 90},
            {"subject_id": 2, "minutes": 60},
        ],
    }
    result = await service.save(
        None,
        1,
        KholleSave(
            expected_revision=calendar.revision,
            expected_year_revision=year.revision,
            settings=proposed,
        ),
    )
    assert (result["revision"] != "a" * 32) is changed
    assert settings["subjects"][0]["subject_id"] == 2
    if changed:
        assert workflow.data == stored  # Keep stale confirmations for orange review states.
        assert workflow.revision != "c" * 32
    else:
        assert workflow.data == stored and workflow.revision == "c" * 32
        db.get.assert_not_awaited()


@pytest.mark.parametrize(
    "assigned,total,expected",
    [(3, 4, True), (2, 4, True), (1, 4, True), (4, 4, False), (0, 4, False), (0, 0, False)],
)
def test_preference_favors_any_nonempty_subset(assigned: int, total: int, expected: bool) -> None:
    """Support multiple assigned promotions while ignoring universal or absent assignments."""
    assert promotion_preference_effective(assigned, total) is expected


@pytest.mark.parametrize("capacity", [-1, 101, 1.5, True, "2"])
def test_room_kholle_capacity_requires_a_bounded_integer(capacity: object) -> None:
    """Reject invalid simultaneous-kholle limits at the API boundary."""
    with pytest.raises(ValidationError):
        RoomSave(name="C105", kholle_capacity=capacity)


def test_room_and_teacher_preference_defaults() -> None:
    """Default rooms to one kholle and teachers to their own promotion."""
    assert RoomSave(name="C105").kholle_capacity == 1
    assert RoomSave(name="C105", kholle_capacity=0).kholle_capacity == 0
    assert KholleTeacherPreference(user_id=1).prefer_own_promotion
    with pytest.raises(ValidationError):
        KholleTeacherPreference(user_id=1, prefer_own_promotion="false")


@pytest.mark.parametrize("rooms", [[], [1, 1], [0], [-1], [True], ["1"], [1.5]])
def test_service_rooms_require_unique_strict_positive_ids(rooms: list) -> None:
    """Reject ambiguous or empty room selections before service validation."""
    with pytest.raises(ValidationError):
        KholleSubjectRooms(subject_id=1, room_ids=rooms)


@pytest.mark.parametrize("sessions", [-1, 1.5, True, "15", 1001])
def test_wishes_reject_invalid_session_counts(sessions: object) -> None:
    """Require bounded whole pedagogical sessions per two-week cycle."""
    with pytest.raises(ValidationError):
        KholleWishEntry(user_id=1, subject_id=2, sessions=sessions)


def test_wishes_distinguish_unfilled_zero_and_odd_counts() -> None:
    """Keep absence, explicit nonparticipation and half-hour weekly averages distinct."""
    for count in (None, 0, 15):
        assert KholleWishEntry(user_id=1, subject_id=2, sessions=count).sessions == count
    with pytest.raises(ValidationError):
        KholleWishesSave(
            expected_revision="a" * 64,
            entries=[KholleWishEntry(user_id=1, subject_id=2, sessions=0)] * 2,
        )


def test_three_weekdays_threshold_and_overlapping_holidays() -> None:
    """Count three available weekdays, exclude two, and ignore Saturday opening."""
    settings = YearSettings.model_validate(
        {
            "start": "2026-09-07",
            "end": "2026-10-02",
            "saturday": True,
            "holidays": [
                {"start": "2026-09-07", "end": "2026-09-08"},
                {"start": "2026-09-08", "end": "2026-09-08"},
                {"start": "2026-09-14", "end": "2026-09-16"},
                {"start": "2026-09-21", "end": "2026-09-26"},
            ],
        }
    )
    weeks = kholle_weeks(settings, 2026)
    assert [(w["number"], w["days"], w["eligible"]) for w in weeks] == [
        (1, 3, True),
        (2, 2, False),
        (3, 5, True),
    ]


def test_boundary_weeks_and_new_year() -> None:
    """Keep the first partial rentrée week and continue dates across January."""
    settings = YearSettings(start="2026-09-01", end="2027-01-08")
    weeks = kholle_weeks(settings, 2026)
    assert weeks[0]["start"] == "2026-08-31"
    assert weeks[0]["days"] == 4
    assert weeks[-1]["end"] == "2027-01-08"


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-09-08"},
        {"end": "2026-09-10"},
        {"end": "2026-09-04"},
        {"subjects": [{"subject_id": 1, "minutes": -1}]},
        {"subjects": [{"subject_id": 1, "minutes": 1.5}]},
        {"subjects": [{"subject_id": 1, "minutes": 60}] * 2},
        {"subjects": []},
    ],
)
def test_invalid_requirements(changes: dict) -> None:
    """Reject invalid dates, fractional minutes, negatives and duplicate subjects."""
    with pytest.raises(ValidationError):
        KholleSettings.model_validate(
            {
                "start": "2026-09-07",
                "end": "2026-09-11",
                "subjects": [{"subject_id": 1, "minutes": 1290}],
                **changes,
            }
        )
