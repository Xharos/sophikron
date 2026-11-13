"""Pupil assignment contexts retain exact promotion and group boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.kholloscope_generation import KholloscopeGenerationService


@pytest.mark.asyncio
async def test_assignment_context_maps_only_matching_groups() -> None:
    """A pupil in another promotion or group cannot enter the selected audience."""
    service = object.__new__(KholloscopeGenerationService)
    service.repo = SimpleNamespace(
        calendars=AsyncMock(
            return_value=[
                SimpleNamespace(id=10, promotion_id=1),
                SimpleNamespace(id=20, promotion_id=2),
            ]
        )
    )
    service.db = SimpleNamespace(
        scalars=AsyncMock(
            return_value=[
                SimpleNamespace(promotion_id=1, group_number=1, user_id=100),
                SimpleNamespace(promotion_id=1, group_number=2, user_id=101),
                SimpleNamespace(promotion_id=2, group_number=1, user_id=102),
            ]
        )
    )
    result = await service.assignment_context(2026, [{"calendar_id": 10, "group": 1}])
    assert result["pupils"] == {(10, 1): {100}}
    assert result["pupil_calendars"] == {100: {10}, 101: {10}, 102: {20}}
