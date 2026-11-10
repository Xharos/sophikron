"""Empty source calendars cannot claim common pupil occupancy."""

from unittest.mock import AsyncMock

import pytest

from app.services.teacher_availability import TeacherAvailabilityService
from tests.support.calendar import settings


@pytest.mark.asyncio
@pytest.mark.parametrize("events", [{}, {1: []}, {1: [], 2: [{"id": "event"}]}])
async def test_empty_source_has_no_common_occupied_range(events: dict) -> None:
    """An empty participating calendar yields no intersection and performs no roster query."""
    service = object.__new__(TeacherAvailabilityService)
    service.db = AsyncMock()
    assert await service._occupied_ranges(events, {1: 1, 2: 2}, settings()) == []
    service.db.execute.assert_not_awaited()
