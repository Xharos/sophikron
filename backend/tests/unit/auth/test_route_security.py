"""Application-wide authentication coverage and explicit private-draft capabilities."""

import re
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.kholloscope import router as kholloscope_router
from app.core.config import DatabaseSettings
from app.dependencies.auth import get_current_user
from app.main import create_app
from app.services.errors import AuthError

PUBLIC_OPERATIONS = {
    ("GET", "/health"),
    ("GET", "/api/v1"),
    ("GET", "/api/v1/site"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/activate"),
}


def concrete_path(path: str) -> str:
    """Replace path identifiers with harmless values for denied HTTP requests."""
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_private_operation_requires_authentication(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """Fail on undocumented anonymous routes and reject anonymous requests before services."""
    application = create_app(settings_factory())
    schema = application.openapi()
    anonymous = set()
    with (
        TestClient(application) as client,
        patch(
            "app.services.auth.AuthService.authenticate",
            new=AsyncMock(side_effect=AuthError(401, "Authentication required")),
        ),
    ):
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                key = (method.upper(), path)
                if not operation.get("security"):
                    anonymous.add(key)
                    continue
                response = client.request(method, concrete_path(path), json={})
                assert response.status_code == 401, (key, response.text)
                assert response.headers["cache-control"] == "no-store"
    assert anonymous == PUBLIC_OPERATIONS


@pytest.mark.parametrize("permissions", [(), ("kholloscope.read",)])
def test_kholloscope_routes_require_explicit_capabilities(
    settings_factory: Callable[..., DatabaseSettings], permissions: tuple[str, ...]
) -> None:
    """Reject every private read without read rights and every mutation with read-only rights."""
    application = create_app(settings_factory())
    actor = SimpleNamespace(permissions=permissions)
    application.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(application) as client:
        for route in kholloscope_router.routes:
            for method in route.methods:
                preview = route.path.endswith("/kholle/preview")
                if permissions and (method == "GET" or preview):
                    continue
                response = client.request(method, concrete_path("/api/v1" + route.path), json={})
                assert response.status_code == 403, (method, route.path, response.text)


def test_private_pdf_cache_policy_survives_middleware(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """Preserve private export headers while keeping ordinary API responses noncacheable."""
    application = create_app(settings_factory())
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        permissions=("kholloscope.read",)
    )
    with (
        TestClient(application) as client,
        patch(
            "app.services.kholloscope_generation.KholloscopeGenerationService.pdf",
            new=AsyncMock(return_value=b"%PDF-synthetic"),
        ),
    ):
        response = client.get("/api/v1/timetable/kholloscope/2026/pdf")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert response.headers["x-content-type-options"] == "nosniff"
