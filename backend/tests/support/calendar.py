"""Shared synthetic fixtures and helpers; never collected as tests."""

from app.schemas.timetable import (
    SeriesData,
    YearSettings,
)


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
