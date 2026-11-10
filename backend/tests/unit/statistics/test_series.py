"""Independent bucket counts and period-wide distinct totals."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.statistics import StatisticsService


def test_missing_buckets_are_zero_without_summing_distinct_users() -> None:
    """Period-wide unique users must not be inferred by summing daily uniques."""
    start = datetime(2026, 9, 1, tzinfo=UTC)
    response = SimpleNamespace(
        timestamps=[start + timedelta(days=i) for i in range(3)], series={}, totals={}
    )
    service = object.__new__(StatisticsService)
    service.fill_series(
        response,
        "downloads",
        "users",
        [(start, 3, 2), (start + timedelta(days=2), 4, 2)],
        7,
        2,
    )
    assert response.series == {"downloads": [3, 0, 4], "users": [2, 0, 2]}
    assert response.totals == {"downloads": 7, "users": 2}


def test_empty_series_has_zero_totals() -> None:
    """An empty data source produces zeros for every requested time bucket."""
    response = SimpleNamespace(timestamps=[datetime(2026, 9, 1, tzinfo=UTC)], series={}, totals={})
    object.__new__(StatisticsService).fill_series(response, "downloads", "users", [], 0, 0)
    assert response.series == {"downloads": [0], "users": [0]}
    assert response.totals == {"downloads": 0, "users": 0}
