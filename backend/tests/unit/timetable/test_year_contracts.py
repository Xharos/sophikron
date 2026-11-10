"""Academic-label validation and immutable year catalogue contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.errors import AuthError
from app.services.timetable import TimetableService
from tests.support.calendar import settings


@pytest.mark.parametrize("year", [2025, 2027])
def test_year_label_rejects_outside_dates(year: int) -> None:
    """A valid document cannot be assigned to another academic year."""
    with pytest.raises(AuthError):
        TimetableService.validate_year_bounds(year, settings())


def test_year_label_accepts_matching_dates() -> None:
    """The selected academic year accepts a valid daily grid within its bounds."""
    assert TimetableService.validate_year_bounds(2026, settings()) is None


@pytest.mark.asyncio
async def test_common_years_preserves_usage_and_revision() -> None:
    """Do not discard permanent usage markers when exposing the year catalogue."""
    service = object.__new__(TimetableService)
    service.db = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[SimpleNamespace(school_year=2026, used=True, revision="r1")]
        )
    )
    assert await service.common_years() == [{"school_year": 2026, "used": True, "revision": "r1"}]
