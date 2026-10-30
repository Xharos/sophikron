"""Verify the backend boundaries retained when SvelteKit relays browser requests."""

from collections.abc import Callable

from fastapi import Request
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.dependencies.auth import client_ip, require_csrf
from app.main import create_app


def test_private_api_keeps_csrf_without_cors(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """Disabling browser CORS must never disable the backend write-origin checks."""
    app = create_app(settings_factory(), auth_settings=AuthSettings(cors_enabled=False))

    @app.post("/api/v1/test/origin")
    def protected(request: Request) -> dict[str, bool]:
        """Exercise the real CSRF validator independently of persistence."""
        require_csrf(request)
        return {"accepted": True}

    with TestClient(app, base_url="https://testserver") as client:
        for headers in ({}, {"Origin": "https://evil.example", "X-CSRF-Protection": "1"}):
            assert client.post("/api/v1/test/origin", headers=headers).status_code == 403
        response = client.post(
            "/api/v1/test/origin",
            headers={"Origin": "https://testserver", "X-CSRF-Protection": "1"},
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


def test_only_trusted_bff_can_forward_client_ip(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """A direct caller cannot spoof its IP, but the configured BFF can forward one."""
    app = create_app(settings_factory())

    @app.get("/api/v1/test/ip")
    def address(request: Request) -> dict[str, str]:
        """Return the address used by the actual rate-limit key builder."""
        return {"ip": client_ip(request)}

    proxy = ProxyHeadersMiddleware(app, trusted_hosts=["172.30.85.2"])
    for peer, expected in (("172.30.85.2", "203.0.113.7"), ("198.51.100.4", "198.51.100.4")):
        with TestClient(proxy, base_url="https://testserver", client=(peer, 1234)) as client:
            response = client.get("/api/v1/test/ip", headers={"X-Forwarded-For": "203.0.113.7"})
            assert response.json() == {"ip": expected}
