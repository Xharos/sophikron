"""Memory-only local API transport with sanitized errors and paginated reads."""

import json
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from .configuration import SeedError


class Client:
    """Reuse an administrator session without direct database access or invitations."""

    def __init__(self, base_url: str, origin: str, timeout: int = 30) -> None:
        """Accept a local API only and never pass cookies through an ambient proxy."""
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise SeedError(
                "BASE_URL doit désigner une API HTTP locale, sans chemin ni identifiants."
            )
        self.base_url, self.origin, self.timeout = base_url, origin, timeout
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def request(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        """Perform one API request without logging credentials or raw failure bodies."""
        headers = {
            "Accept": "application/json",
            "Origin": self.origin,
            "X-CSRF-Protection": "1",
        }
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}/api/v1{path}", data=body, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = {} if response.status == 204 else json.load(response)
                if not isinstance(result, (dict, list)) or (
                    isinstance(result, list) and any(not isinstance(item, dict) for item in result)
                ):
                    raise SeedError("Format de réponse API invalide.")
                return result
        except HTTPError as error:
            status = error.code
            error.close()
            raise SeedError(
                f"HTTP {status} : {method} {path.split('?')[0]}. "
                "Vérifiez les droits, migrations et données existantes."
            ) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise SeedError("API locale indisponible ou réponse JSON invalide.") from None

    def pages(self, path: str, filters: dict | None = None) -> list[dict]:
        """Read every page and reject an inconsistent empty page instead of looping forever."""
        result = []
        while True:
            page = self.request(
                "GET",
                f"{path}?{urlencode({**(filters or {}), 'offset': len(result), 'limit': 100})}",
            )
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise SeedError("Format de pagination invalide.")
            batch, total = page["items"], page.get("total")
            if not isinstance(total, int) or any(not isinstance(item, dict) for item in batch):
                raise SeedError("Format de catalogue invalide.")
            result.extend(batch)
            if len(result) >= total:
                return result
            if not batch:
                raise SeedError("Le catalogue a changé pendant sa lecture.")
