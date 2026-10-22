"""Identity confidentiality, password policy, browser protections and safe diagnostics."""

import asyncio
import base64
import json
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.cli import generate_keys
from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.core.http import AuthRequestMiddleware
from app.core.security import (
    IdentityCipher,
    PasswordCapacityError,
    PasswordSecurity,
    new_token,
    normalize_email,
    normalize_username,
    token_digest,
    validate_password,
)
from app.dependencies.auth import RequireRole
from app.main import create_app
from app.schemas.auth import ActivateRequest, LoginRequest
from app.services.mail import MailDeliveryError, SmtpMailer

PASSWORD = "IndependentTestPassword2026!"


def test_identity_encryption_and_binding() -> None:
    """Use randomized ciphertext, keyed lookup and authenticated row/field binding."""
    cipher = IdentityCipher.from_file(AuthSettings().keys_file)
    user_id = uuid4()
    encrypted = cipher.encrypt(user_id, "email", "teacher@example.org")
    assert b"teacher@example.org" not in encrypted
    assert encrypted != cipher.encrypt(user_id, "email", "teacher@example.org")
    assert cipher.decrypt(user_id, "email", encrypted) == "teacher@example.org"
    assert cipher.lookup("email", "a") != cipher.lookup("username", "a")
    assert len(cipher.lookup("email", "a")) == 32
    for identifier, field, value in (
        (uuid4(), "email", encrypted),
        (user_id, "username", encrypted),
        (user_id, "email", encrypted[:-1] + bytes([encrypted[-1] ^ 1])),
        (user_id, "email", b"missing:invalid"),
    ):
        with pytest.raises(ValueError, match="Cannot decrypt"):
            cipher.decrypt(identifier, field, value)


def test_versioned_encryption_keys() -> None:
    """Keep old ciphertext readable during a versioned encryption-key transition."""
    previous = IdentityCipher("old", {"old": b"a" * 32}, b"b" * 32)
    current = IdentityCipher("new", {"old": b"a" * 32, "new": b"c" * 32}, b"b" * 32)
    user_id = uuid4()
    encrypted = previous.encrypt(user_id, "username", "teacher")
    assert current.decrypt(user_id, "username", encrypted) == "teacher"
    assert current.encrypt(user_id, "username", "teacher").startswith(b"new:")
    assert previous.lookup("username", "teacher") == current.lookup("username", "teacher")


@pytest.mark.parametrize(
    "raw", [b"not-json", b"{}", b"secret" * 20000], ids=["invalid", "missing", "oversized"]
)
def test_invalid_key_files_are_redacted(tmp_path: Path, raw: bytes) -> None:
    """Report a bounded generic error without echoing key-file content."""
    path = tmp_path / "invalid"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="Cannot load identity encryption keys"):
        IdentityCipher.from_file(path)


def test_key_generation_never_overwrites(tmp_path: Path) -> None:
    """Generate independent keys and preserve an existing installation's keyring."""
    path = tmp_path / "keys"
    generate_keys(path)
    original = path.read_bytes()
    data = json.loads(original)
    assert data["encryption_keys"]["v1"] != data["lookup_key"]
    assert len(base64.b64decode(data["lookup_key"])) == 32
    IdentityCipher.from_file(path)
    with pytest.raises(FileExistsError):
        generate_keys(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("password", [
    "Aa1!short", "Aa1!" + "x" * 125, "ABCDEFGHI1!", "abcdefghi1!",
    "Abcdefghi!!", "Abcdefghi12", "Abcdefghi1! ", "Abcdefghi1!é",
    "Abcdefghi1!\n", "Abcdefghi1!\x00",
])
def test_password_policy(password: str) -> None:
    """Reject invalid lengths, missing categories and characters outside printable ASCII."""
    with pytest.raises(ValueError):
        validate_password(password)


@pytest.mark.parametrize("password", ["Abcdefg1!@", "Aa1!" + "x" * 124])
def test_password_policy_boundaries(password: str) -> None:
    """Accept both length boundaries with all four categories and no dictionary screening."""
    validate_password(password)


@pytest.mark.asyncio
async def test_argon2id_and_dummy_verification() -> None:
    """Use independently salted Argon2id and perform a dummy check for absent credentials."""
    passwords = PasswordSecurity(AuthSettings())
    await passwords.initialize()
    first = await passwords.hash(PASSWORD)
    second = await passwords.hash(PASSWORD)
    assert first.startswith("$argon2id$") and first != second
    assert await passwords.verify(first, PASSWORD)
    assert not await passwords.verify(first, "incorrect")
    assert not await passwords.verify(None, PASSWORD)
    assert not await passwords.verify("invalid-hash", PASSWORD)
    validate_password(PASSWORD)
    assert not await passwords.verify(first, " " + PASSWORD + " ")


def test_normalized_identities_and_token_entropy() -> None:
    """Normalize both login forms consistently while keeping random token verifiers distinct."""
    assert normalize_username(" Teacher_1 ") == "teacher_1"
    assert normalize_email(" Teacher@EXAMPLE.org ") == "teacher@example.org"
    for username in ("a@b", "ab", "éléve", "a/b", "a b"):
        with pytest.raises(ValueError):
            normalize_username(username)
    first, second = new_token(), new_token()
    assert len(first) == 43 and first != second
    assert len(token_digest(first)) == 32 and token_digest(first) != token_digest(second)


def test_production_configuration_fails_closed() -> None:
    """Require TLS cookies, HTTPS origins and adequate production password hashing parameters."""
    settings = AuthSettings()
    values = settings.model_dump() | {"keys_file": settings.keys_file, "environment": "production"}
    values.update(argon_memory_kib=65536, argon_iterations=3)
    assert AuthSettings(**values).cookie_name.startswith("__Host-")
    for override in (
        {"cookie_secure": False},
        {"allowed_origins": ["http://example.org"]},
        {"allowed_origins": ["https://*.example.org"]},
        {"argon_memory_kib": 8192},
        {"allowed_origins": ["https://example.org/path"]},
    ):
        with pytest.raises(ValidationError):
            AuthSettings(**(values | override))
    with pytest.raises(ValueError):
        RequireRole()


def test_browser_protection_and_validation_redaction(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """Reject browser cross-origin writes before credential lookup and never echo invalid inputs."""
    with TestClient(create_app(settings_factory()), base_url="https://testserver") as client:
        payload = {"identifier": "private@example.org", "password": PASSWORD}
        for headers in (
            {},
            {"Origin": "https://evil.example", "X-CSRF-Protection": "1"},
            {"Origin": "null", "X-CSRF-Protection": "1"},
            {"Origin": "https://testserver"},
        ):
            response = client.post("/api/v1/auth/login", json=payload, headers=headers)
            assert response.status_code == 403
            assert "csrf" not in response.text.lower()
            assert "private@example.org" not in response.text
        response = client.post(
            "/api/v1/auth/login",
            json={"password": PASSWORD},
            headers={
                "Origin": "https://testserver",
                "X-CSRF-Protection": "1",
            },
        )
        assert response.status_code == 422 and PASSWORD not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/logout").status_code == 401
        assert client.get("/").status_code == 404
        rejected = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Protection,Content-Type",
            },
        )
        assert "access-control-allow-origin" not in rejected.headers
        allowed = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "https://testserver",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Protection,Content-Type",
            },
        )
        assert allowed.headers["access-control-allow-origin"] == "https://testserver"


def test_credential_models_redact_repr() -> None:
    """Keep passwords and activation secrets out of ordinary model diagnostics."""
    assert PASSWORD not in repr(LoginRequest(identifier="user", password=PASSWORD))
    activation = ActivateRequest(token=new_token(), password=PASSWORD)
    assert activation.token.get_secret_value() not in repr(activation)
    assert PASSWORD not in repr(activation)


@pytest.mark.asyncio
async def test_smtp_requires_tls_and_preserves_fragment_token() -> None:
    """Send through the replaceable SMTP adapter without putting the token in a query string."""
    settings = AuthSettings(
        mail_transport="smtp",
        smtp_host="smtp.example.org",
        smtp_sender="noreply@example.org",
        activation_url="https://testserver/activate",
    )
    token = new_token()
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    with patch("app.services.mail.smtplib.SMTP", return_value=smtp):
        await SmtpMailer(settings).send_invitation("teacher@example.org", token)
    smtp.starttls.assert_called_once()
    message = smtp.send_message.call_args.args[0]
    assert "#token=" + token in message.get_content()
    assert "?token=" not in message.get_content()
    smtp.send_message.side_effect = OSError("private transport diagnostic")
    with patch("app.services.mail.smtplib.SMTP", return_value=smtp):
        with pytest.raises(MailDeliveryError, match="Delivery unavailable"):
            await SmtpMailer(settings).send_invitation("teacher@example.org", token)


def test_bootstrap_password_is_independent_and_redacted(tmp_path: Path) -> None:
    """Allow simple or empty bootstrap secrets while rejecting malformed secret files."""
    from app.core.security_policy import read_bootstrap_password

    path = tmp_path / "secret"
    for value in ("", "admin", "simple", PASSWORD):
        path.write_text(value + "\n")
        assert read_bootstrap_password(path) == value
    for value in ("x" * 513, "x" * 129, "long\npassword-value", "nul\x00value"):
        path.write_text(value)
        with pytest.raises(ValueError):
            read_bootstrap_password(path)
    with pytest.raises(ValueError):
        read_bootstrap_password(None)


def test_swagger_documents_browser_write_header() -> None:
    """Expose the custom header on all application writes without relaxing validation."""
    schema = create_app().openapi()
    for path, methods in schema["paths"].items():
        if path.startswith("/api/v1") and "post" in methods:
            parameters = methods["post"].get("parameters", [])
            assert any(
                p["name"] == "X-CSRF-Protection" and p["in"] == "header" for p in parameters
            ), path


@pytest.mark.parametrize("length_header", [None, "2097152", "1"])
def test_oversized_auth_body_precedes_json(
    settings_factory: Callable[..., DatabaseSettings], length_header: str | None
) -> None:
    """Reject large declared, chunked and underreported bodies before JSON or dependencies."""
    app = create_app(settings_factory())
    headers = {"Content-Type": "application/json"}
    if length_header is not None:
        headers["Content-Length"] = length_header
    body = b'{"identifier":"' + b"a" * (2 * 1024 * 1024) + b'","password":"synthetic"}'
    with TestClient(app) as client, patch(
        "starlette.requests.Request.json", new=AsyncMock(side_effect=AssertionError("JSON parsed"))
    ):
        response = client.post("/api/v1/auth/login", content=iter([body]), headers=headers)
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"


def test_exact_auth_body_limit(settings_factory: Callable[..., DatabaseSettings]) -> None:
    """Accept a body at the byte boundary for ordinary schema validation."""
    with TestClient(create_app(settings_factory())) as client:
        response = client.post(
            "/api/v1/auth/login",
            content=b"{}" + b" " * (16384 - 2),
            headers={
                "Origin": "https://testserver", "X-CSRF-Protection": "1",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth_body_read_timeout() -> None:
    """Expire a stalled body before any downstream application work."""
    from types import SimpleNamespace

    settings = AuthSettings(request_body_timeout_seconds=0.01)
    downstream = AsyncMock()
    send = AsyncMock()
    middleware = AuthRequestMiddleware(downstream)

    async def stalled_receive() -> dict:
        """Simulate a peer that does not complete its body."""
        await anyio.sleep_forever()

    await middleware(
        {
            "type": "http", "path": "/api/v1/auth/login", "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(auth_settings=settings)),
        },
        stalled_receive,
        send,
    )
    downstream.assert_not_awaited()
    assert send.call_args_list[0].args[0]["status"] == 408


@pytest.mark.asyncio
async def test_password_queue_is_bounded_and_recovers() -> None:
    """Reject overflow and expire queued work while preserving a running operation."""
    passwords = PasswordSecurity(AuthSettings(
        password_workers=1, password_queue_size=1, password_queue_timeout_seconds=0.05
    ))
    started, release = threading.Event(), threading.Event()

    def blocked() -> str:
        """Occupy one worker until the test releases it."""
        started.set()
        assert release.wait(5)
        return "completed"

    running = asyncio.create_task(passwords._run(blocked))
    queued = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        queued = asyncio.create_task(passwords.hash("synthetic"))
        with anyio.fail_after(2):
            while passwords._admission.borrowed_tokens != 2:
                await asyncio.sleep(0)
        with pytest.raises(PasswordCapacityError):
            await passwords.hash("overflow")
        with pytest.raises(PasswordCapacityError):
            await queued
    finally:
        release.set()
        assert await running == "completed"
        if queued is not None:
            await asyncio.gather(queued, return_exceptions=True)
    assert (await passwords.hash("synthetic")).startswith("$argon2id$")


def test_admission_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read configurable IP and pair limits plus HTTP and password queue bounds."""
    monkeypatch.setenv("AUTH_LOGIN_IP_LIMIT", "37")
    monkeypatch.setenv("AUTH_LOGIN_IDENTITY_LIMIT", "7")
    monkeypatch.setenv("AUTH_REQUEST_MAX_BYTES", "8192")
    settings = AuthSettings()
    assert (settings.login_ip_limit, settings.login_identity_limit) == (37, 7)
    assert settings.request_max_bytes == 8192


def test_password_overload_http_response(
    settings_factory: Callable[..., DatabaseSettings],
) -> None:
    """Return a generic retryable response without exposing saturation internals or credentials."""
    with TestClient(create_app(settings_factory())) as client, patch(
        "app.services.auth.AuthService.login", new=AsyncMock(side_effect=PasswordCapacityError)
    ):
        response = client.post(
            "/api/v1/auth/login", json={"identifier": "user", "password": PASSWORD},
            headers={"Origin": "https://testserver", "X-CSRF-Protection": "1"},
        )
    assert response.status_code == 503 and response.headers["retry-after"] == "1"
    assert PASSWORD not in response.text
