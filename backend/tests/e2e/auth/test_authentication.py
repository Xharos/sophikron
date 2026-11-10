"""Real TCP authentication journey against the runner's disposable installation."""

import os
from pathlib import Path

import httpx2 as httpx
import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


@pytest.fixture(scope="session")
def live_installation() -> tuple[str, str, Path]:
    """Capture runner settings before function-scoped synthetic AUTH settings replace them."""
    if os.environ.get("DB_INTEGRATION") != "1" or os.environ.get("DB_NAME") != "sophikron_test":
        pytest.skip("Run through backend/run_tests.py with its disposable API")
    url = os.environ.get("DB_TEST_API_URL")
    directory = os.environ.get("SOPHIKRON_SECRETS_DIRECTORY")
    username = os.environ.get("AUTH_BOOTSTRAP_USERNAME")
    if not url or not directory or not username:
        pytest.skip("Disposable live API bootstrap configuration required")
    return url, username, Path(directory) / "bootstrap_password"


def test_login_profile_logout_and_revoked_session(
    live_installation: tuple[str, str, Path],
) -> None:
    """Authenticate over TCP, read own identity, log out and reject reuse of the session."""
    url, username, secret = live_installation
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Protection": "1"}
    with httpx.Client(base_url=url, headers=headers, timeout=15) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401
        response = client.post(
            "/api/v1/auth/login",
            json={"identifier": username, "password": secret.read_text().strip()},
        )
        assert response.status_code == 200
        assert response.json()["is_bootstrap"] is True
        saved_cookies = dict(client.cookies)
        try:
            assert client.get("/api/v1/auth/me").status_code == 200
            assert client.get("/api/v1/admin/users").status_code == 403
        finally:
            assert client.post("/api/v1/auth/logout").status_code == 204
        client.cookies.update(saved_cookies)
        assert client.get("/api/v1/auth/me").status_code == 401
