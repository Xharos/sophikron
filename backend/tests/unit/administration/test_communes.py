"""Public commune adapter validation and failure handling without external network access."""

import io
import json

import pytest

from app.services import communes
from app.services.errors import AuthError


@pytest.mark.asyncio
async def test_public_commune_cache_and_pair_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache public references and validate postcode membership against canonical names."""
    calls: list[str] = []
    communes._cache.clear()

    def response(request: object, timeout: int) -> io.BytesIO:
        """Return only a synthetic public commune record."""
        calls.append(request.full_url)
        assert timeout == 3
        return io.BytesIO(
            json.dumps([{"code": "75056", "nom": "Paris", "codesPostaux": ["75001"]}]).encode()
        )

    monkeypatch.setattr(communes, "urlopen", response)
    assert (await communes.search_communes("75001"))[0].nom == "Paris"
    assert (await communes.search_communes("75001"))[0].code == "75056"
    assert len(calls) == 1 and "codePostal=75001" in calls[0]
    assert await communes.validate_commune("75056", "75001") == "Paris"
    with pytest.raises(AuthError) as error:
        await communes.validate_commune("75056", "69001")
    assert error.value.status == 422
    assert await communes.search_communes("750") == []
    communes._cache.clear()


@pytest.mark.asyncio
async def test_unavailable_communes_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report upstream transport failures without request data or raw network exceptions."""
    communes._cache.clear()

    def unavailable(request: object, timeout: int) -> io.BytesIO:
        """Simulate an unreachable public service."""
        raise OSError("private network diagnostics")

    monkeypatch.setattr(communes, "urlopen", unavailable)
    with pytest.raises(AuthError) as error:
        await communes.search_communes("Paris")
    assert error.value.status == 503 and "diagnostics" not in error.value.message
