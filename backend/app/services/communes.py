"""Bounded, cached access to the public French commune reference without student identities."""

import json
import threading
import time
from collections import OrderedDict
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import anyio
from pydantic import BaseModel, Field, ValidationError

from app.services.errors import AuthError


class Commune(BaseModel):
    """Validate only the public fields needed to select a coherent commune/postcode pair."""

    code: str = Field(pattern=r"^[0-9A-Z]{5}$")
    nom: str = Field(min_length=1, max_length=200)
    codesPostaux: list[str] = Field(max_length=100)


_cache: OrderedDict[str, tuple[float, list[Commune]]] = OrderedDict()
_lock = threading.Lock()
_capacity = threading.BoundedSemaphore(4)


def fetch_communes(parameters: dict[str, str]) -> list[Commune]:
    """Fetch a bounded public response over HTTPS, caching at most 256 queries for six hours."""
    query = urlencode({**parameters, "fields": "nom,code,codesPostaux", "limit": "10"})
    now = time.monotonic()
    with _lock:
        cached = _cache.get(query)
        if cached and cached[0] > now:
            _cache.move_to_end(query)
            return cached[1]
        _cache.pop(query, None)
    if not _capacity.acquire(blocking=False):
        raise AuthError(503, "La recherche des communes est occupée. Réessayez.")
    try:
        request = Request(
            "https://geo.api.gouv.fr/communes?" + query,
            headers={"Accept": "application/json", "User-Agent": "Sophikron/1.0"},
        )
        with urlopen(request, timeout=3) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("Oversized public response")
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("Invalid public response")
        result = [Commune.model_validate(row) for row in rows]
    except (OSError, URLError, ValueError, ValidationError):
        raise AuthError(
            503, "Le service des communes est indisponible. Réessayez plus tard."
        ) from None
    finally:
        _capacity.release()
    with _lock:
        _cache[query] = (now + 21600, result)
        while len(_cache) > 256:
            _cache.popitem(last=False)
    return result


async def search_communes(query: str) -> list[Commune]:
    """Search by an exact postcode or a partial commune name outside the event loop."""
    if query.isdigit():
        if len(query) != 5:
            return []
        parameters = {"codePostal": query}
    else:
        parameters = {"nom": query, "boost": "population"}
    return await anyio.to_thread.run_sync(lambda: fetch_communes(parameters))


async def validate_commune(code: str, postcode: str) -> str:
    """Return the canonical commune name only when the selected postcode belongs to it."""
    matches = await anyio.to_thread.run_sync(lambda: fetch_communes({"code": code}))
    for commune in matches:
        if commune.code == code and postcode in commune.codesPostaux:
            return commune.nom
    raise AuthError(422, "Sélectionnez une commune et un code postal correspondants.")
