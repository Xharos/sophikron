"""Commune lookup authorization before outbound reference-data requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.profiles import communes
from app.services.errors import AuthError


@pytest.mark.asyncio
@pytest.mark.parametrize("denied", [False, True])
async def test_commune_lookup_revalidates_permission_before_network(denied: bool) -> None:
    """Strip the public query and avoid any outbound request when the grant is denied."""
    actor = SimpleNamespace(id=7)
    auth = SimpleNamespace(db=MagicMock(), _actor=AsyncMock())
    if denied:
        auth._actor.side_effect = AuthError(403, "Forbidden")
    with patch("app.api.v1.profiles.search_communes", new_callable=AsyncMock) as search:
        search.return_value = []
        if denied:
            with pytest.raises(AuthError):
                await communes(actor, auth, "  Paris  ")
            search.assert_not_awaited()
        else:
            assert await communes(actor, auth, "  Paris  ") == []
            search.assert_awaited_once_with("Paris")
    auth._actor.assert_awaited_once_with(actor, permission="profiles.manage")
