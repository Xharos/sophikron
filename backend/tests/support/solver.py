"""Shared synthetic scenario fixtures."""

from datetime import date, timedelta

import pytest


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
