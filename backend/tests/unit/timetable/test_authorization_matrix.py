"""Live calendar scope and academic revision rejection matrices."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.errors import AuthError
from app.services.timetable import TimetableService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "permissions,bootstrap,write,allowed",
    [
        ({"users.manage"}, False, True, True),
        ({"teaching.read"}, False, False, True),
        ({"kholleur.access"}, False, False, True),
        ({"teaching.read"}, False, True, False),
        (set(), False, False, False),
        ({"users.manage"}, True, False, False),
    ],
)
async def test_calendar_access_matrix(
    permissions: set, bootstrap: bool, write: bool, allowed: bool
) -> None:
    """Students and bootstrap accounts never gain calendar access from frontend visibility."""
    service = object.__new__(TimetableService)
    service.db = MagicMock()
    service.today = MagicMock(return_value="today")
    service.auth = SimpleNamespace(
        _actor=AsyncMock(return_value=SimpleNamespace(is_bootstrap=bootstrap)),
        repo=SimpleNamespace(permissions=AsyncMock(return_value=permissions)),
    )
    with patch("app.services.timetable_lifecycle.rollover", new_callable=AsyncMock) as rollover:
        if allowed:
            assert await service.authorize(SimpleNamespace(id=1), write=write) == (
                "users.manage" in permissions
            )
            rollover.assert_awaited_once()
        else:
            with pytest.raises(AuthError) as error:
                await service.authorize(SimpleNamespace(id=1), write=write)
            assert error.value.status == 403
            rollover.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["year_missing", "calendar_missing", "archived", "live", "stale", "valid"]
)
async def test_year_lock_rejects_invalid_mutations(scenario: str) -> None:
    """Only current revisions on editable, acknowledged calendars may proceed."""
    service = object.__new__(TimetableService)
    service.auth = SimpleNamespace(_lifecycle_lock=AsyncMock())
    service.authorize = AsyncMock(return_value=True)
    row = SimpleNamespace(calendar_id=3, revision="current")
    calendar = SimpleNamespace(
        is_archived=scenario == "archived", is_paused=scenario != "live", promotion_id=1
    )
    service.db = SimpleNamespace(
        scalar=AsyncMock(return_value=None if scenario == "year_missing" else row),
        get=AsyncMock(return_value=None if scenario == "calendar_missing" else calendar),
    )
    version = SimpleNamespace(
        confirmed_live=False, expected_revision="old" if scenario == "stale" else "current"
    )
    if scenario == "valid":
        assert await service._year(2, SimpleNamespace(id=1), version) is row
    else:
        with pytest.raises(AuthError) as error:
            await service._year(2, SimpleNamespace(id=1), version)
        assert error.value.status == (404 if scenario.endswith("missing") else 409)
    service.auth._lifecycle_lock.assert_awaited_once()
