"""Measured performance regression budgets with correctness assertions."""

from collections.abc import Callable
from time import perf_counter

import pytest

from app.schemas.timetable import YearDocument
from app.services.timetable_engine import occurrences
from tests.support.calendar import series, settings

pytestmark = pytest.mark.perf


def test_annual_occurrences_budget(record_property: Callable[[str, object], None]) -> None:
    """Expand an annual calendar with many recurring blocks within a broad time budget."""
    document = YearDocument(
        settings=settings(end="2027-07-01"),
        series=[series(id=f"{i + 1:032x}", lineage=f"{i + 1:032x}") for i in range(100)],
    )
    start = perf_counter()
    events = occurrences(document)
    elapsed = perf_counter() - start
    assert len(events) >= 3000
    record_property("elapsed_seconds", elapsed)
    record_property("occurrences", len(events))
    assert elapsed < 5
