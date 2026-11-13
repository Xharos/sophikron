"""Measured performance regression budgets with correctness assertions."""

from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter

import pytest

from app.services.statistics import statistics_window

pytestmark = pytest.mark.perf


def test_calendar_window_budget(record_property: Callable[[str, object], None]) -> None:
    """Keep repeated timezone-aware window calculations bounded and correct."""
    instant = datetime(2026, 10, 25, 23, 59, tzinfo=UTC)
    start = perf_counter()
    for _ in range(1000):
        _, bins = statistics_window(instant, "month")
        assert len(bins) == 30
    elapsed = perf_counter() - start
    record_property("elapsed_seconds", elapsed)
    assert elapsed < 5
