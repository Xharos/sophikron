"""Statistics windows contracts."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.statistics import statistics_window


@pytest.mark.parametrize("day,hours", [("2027-03-28", 23), ("2026-10-25", 25), ("2026-10-26", 24)])
def test_statistics_paris_calendar_hours(day: str, hours: int) -> None:
    """Keep both repeated hours and omit the nonexistent spring hour without shifting days."""
    now = datetime.fromisoformat(day + "T23:59:59").replace(tzinfo=ZoneInfo("Europe/Paris"))
    start, bins = statistics_window(now, "day")
    assert len(bins) == hours and start == bins[0]
    assert len(set(bins)) == hours
    assert all(item.astimezone(ZoneInfo("Europe/Paris")).date().isoformat() == day for item in bins)


def test_today_does_not_fabricate_zero_activity_in_future_hours() -> None:
    """Stop at the current partial hour rather than drawing a drop to zero in the future."""
    now = datetime(2026, 10, 26, 2, 30, tzinfo=ZoneInfo("Europe/Paris"))
    _, bins = statistics_window(now, "day")
    assert len(bins) == 3 and all(item <= now for item in bins)


@pytest.mark.parametrize("period,days", [("week", 7), ("month", 30)])
def test_statistics_calendar_days(period: str, days: int) -> None:
    """Include today and preceding calendar days across daylight-saving transitions."""
    now = datetime(2026, 10, 26, 0, 10, tzinfo=UTC)
    start, bins = statistics_window(now, period)
    assert start == bins[0] and len(bins) == days
    assert bins[-1].astimezone(ZoneInfo("Europe/Paris")).date() == now.date()
    assert all(item.astimezone(ZoneInfo("Europe/Paris")).hour == 0 for item in bins)
