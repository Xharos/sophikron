"""Authentication integration tests using actual PostgreSQL transactions and HTTP dependencies."""

import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.cli import execute, generate_keys
from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.core.database import Database
from app.core.security import IdentityCipher, PasswordSecurity, token_digest
from app.dependencies.auth import AuthenticatedUser, StudentUser, TeacherUser
from app.main import create_app
from app.models import (
    AccountInvitation,
    ApplicationState,
    AuthRateLimit,
    LoginAttempt,
    LoginEvent,
    Session,
    User,
    UserRole,
)
from app.services.auth import AuthService
from app.services.errors import AuthError
from app.services.mail import MailDeliveryError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Dedicated PostgreSQL required"
    ),
]
PASSWORD = "IndependentSophikronPassword2026!"
SECOND_PASSWORD = "DifferentIndependentPassword2026!"
HEADERS = {"Origin": "https://testserver", "X-CSRF-Protection": "1"}


class MemoryMailer:
    """Capture invitation delivery only inside isolated test memory."""

    available = True

    def __init__(self) -> None:
        """Initialize captured deliveries and an explicit transport failure switch."""
        self.messages: list[tuple[str, str]] = []
        self.fail = False

    async def send_invitation(self, recipient: str, token: str) -> None:
        """Capture successful sends or simulate a sanitized transport failure."""
        if self.fail:
            raise MailDeliveryError("synthetic transport failure")
        self.messages.append((recipient, token))


@dataclass
class Harness:
    """Own HTTP clients and only the account records created by this test."""

    app: FastAPI
    database: Database
    client: httpx.AsyncClient
    mailer: MemoryMailer
    prefix: str
    ids: list[UUID] = field(default_factory=list)
    administrator: UUID | None = None
    admin_token: str = ""

    def as_admin(self) -> None:
        """Restore the fixture administrator's browser cookie after a role-specific login."""
        self.client.cookies.clear()
        self.client.cookies.set(
            self.app.state.auth_settings.cookie_name,
            self.admin_token,
            domain="testserver.local",
            path="/",
        )

    async def create(self, role: str = "student", *, activate: bool = True) -> tuple[UUID, str]:
        """Create and optionally activate a uniquely named account through the real HTTP API."""
        self.as_admin()
        username = f"{self.prefix}_{len(self.ids)}"
        response = await self.client.post(
            "/api/v1/admin/users",
            json={
                "username": username,
                "email": f"{username}@example.org",
                "roles": [role],
            },
        )
        assert response.status_code == 201, response.text
        user_id = UUID(response.json()["id"])
        self.ids.append(user_id)
        if activate:
            response = await self.client.post(f"/api/v1/admin/users/{user_id}/invite")
            assert response.status_code == 204
            token = self.mailer.messages[-1][1]
            response = await self.client.post(
                "/api/v1/auth/activate",
                json={
                    "token": token,
                    "password": PASSWORD,
                },
            )
            assert response.status_code == 204
        return user_id, username


@pytest_asyncio.fixture
async def auth_case(migrated_database: None, tmp_path: Path) -> AsyncIterator[Harness]:
    """Exercise the initial administrator handover before yielding a normal installation."""
    database = Database(DatabaseSettings())
    mailer = MemoryMailer()
    prefix = "u" + uuid4().hex[:12]
    secret = tmp_path / "bootstrap-password"
    secret.write_text(PASSWORD)
    settings = AuthSettings(bootstrap_username=prefix + "_setup", bootstrap_password_file=secret)
    app = create_app(mailer=mailer, auth_settings=settings)
    async with database.sessions.begin() as session:
        await session.execute(update(ApplicationState).values(initialized_at=None))

    @app.get("/api/v1/test/teacher")
    async def teacher(user: TeacherUser) -> dict[str, str]:
        """Exercise the reusable teacher-only dependency on a protected operation."""
        return {"id": str(user.id)}

    @app.get("/api/v1/test/student")
    async def student(user: StudentUser) -> dict[str, str]:
        """Exercise the reusable student-only dependency."""
        return {"id": str(user.id)}

    @app.post("/api/v1/test/write")
    async def write(user: AuthenticatedUser) -> dict[str, str]:
        """Exercise CSRF enforcement inherited by a future cookie-authenticated route."""
        return {"id": str(user.id)}

    case: Harness | None = None
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://testserver",
                headers=HEADERS,
            ) as client:
                case = Harness(app, database, client, mailer, prefix)
                async with database.sessions() as session:
                    initial = await session.scalar(select(User).where(User.is_bootstrap))
                    case.ids.append(initial.id)
                response = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "identifier": prefix + "_setup",
                        "password": PASSWORD,
                    },
                )
                assert response.status_code == 200
                # Bootstrap sessions can only inspect/logout/complete initial setup.
                assert (
                    await client.post(
                        "/api/v1/admin/users",
                        json={
                            "username": prefix + "_forbidden",
                            "email": f"{prefix}_forbidden@example.org",
                            "roles": ["teacher"],
                        },
                    )
                ).status_code == 403
                case.admin_token = client.cookies.get(app.state.auth_settings.cookie_name)
                response = await client.post(
                    "/api/v1/auth/setup",
                    json={
                        "username": prefix + "_1",
                        "email": f"{prefix}_1@example.org",
                        "password": PASSWORD,
                    },
                )
                assert response.status_code == 201, response.text
                owner = UUID(response.json()["id"])
                case.ids.append(owner)
                case.administrator = owner
                assert (await client.get("/api/v1/auth/me")).status_code == 401
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={
                            "identifier": f"{prefix}_1",
                            "password": PASSWORD,
                        },
                    )
                ).status_code == 200
                case.admin_token = client.cookies.get(app.state.auth_settings.cookie_name)
                yield case
    finally:
        if case and case.ids:
            async with database.sessions.begin() as session:
                await session.execute(
                    delete(AccountInvitation).where(
                        AccountInvitation.user_id.in_(case.ids)
                        | AccountInvitation.issued_by_user_id.in_(case.ids)
                    )
                )
                await session.execute(delete(User).where(User.id.in_(case.ids)))
                await session.execute(update(ApplicationState).values(initialized_at=None))
        await database.close()


@pytest.mark.asyncio
async def test_login_cookie_stats_and_logout(auth_case: Harness) -> None:
    """Persist one event per successful login and keep other browsers independent on logout."""
    case = auth_case
    user_id, username = await case.create()
    response = await case.client.post(
        "/api/v1/auth/login",
        json={
            "identifier": username.upper(),
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Domain=" not in cookie and "Path=/" in cookie and "Max-Age=28800" in cookie
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app),
        base_url="https://testserver",
        headers=HEADERS,
    ) as second:
        assert (
            await second.post(
                "/api/v1/auth/login",
                json={
                    "identifier": f"{username.upper()}@EXAMPLE.ORG",
                    "password": PASSWORD,
                },
            )
        ).status_code == 200
        for _ in range(3):
            response = await case.client.get("/api/v1/auth/me")
            assert response.status_code == 200 and response.json()["roles"] == ["student"]
        async with case.database.sessions() as session:
            user = await session.get(User, user_id)
            assert user.login_count == 2 and user.last_login_at is not None
            assert user.password_hash.startswith("$argon2id$")
            assert username.encode() not in user.username_encrypted
            sessions = list(
                (await session.scalars(select(Session).where(Session.user_id == user_id))).all()
            )
            assert len(sessions) == 2
            assert token_digest(token) in [item.token_hash for item in sessions]
            assert all(item.token_hash != token.encode() for item in sessions)
            events = list(
                (
                    await session.scalars(select(LoginEvent).where(LoginEvent.user_id == user_id))
                ).all()
            )
            assert len(events) == 2 and all(event.occurred_at.tzinfo for event in events)
        assert (await case.client.post("/api/v1/auth/logout")).status_code == 204
        case.client.cookies.set(case.app.state.auth_settings.cookie_name, token)
        assert (await case.client.get("/api/v1/auth/me")).status_code == 401
        assert (await second.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_generic_failures_and_role_boundaries(auth_case: Harness) -> None:
    """Hide account state at login and enforce current explicit roles on every request."""
    case = auth_case
    user_id, username = await case.create("teacher")
    pending_id, pending = await case.create(activate=False)
    messages = []
    for identifier in ("unknown_name", username, pending):
        result = await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": identifier,
                "password": "incorrect password",
            },
        )
        assert result.status_code == 401
        messages.append(result.json())
    assert messages[0] == messages[1] == messages[2]
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": PASSWORD,
            },
        )
    ).status_code == 200
    assert (await case.client.get("/api/v1/test/teacher")).status_code == 200
    assert (await case.client.get("/api/v1/test/student")).status_code == 403
    assert (
        await case.client.post(
            "/api/v1/admin/users",
            json={
                "username": "unauthorized",
                "email": "unauthorized@example.org",
                "roles": ["admin"],
            },
        )
    ).status_code == 403
    async with case.database.sessions.begin() as session:
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    assert (await case.client.get("/api/v1/test/teacher")).status_code == 403
    async with case.database.sessions.begin() as session:
        await session.execute(update(User).where(User.id == user_id).values(status="disabled"))
    assert (await case.client.get("/api/v1/auth/me")).status_code == 401
    result = await case.client.post(
        "/api/v1/auth/login",
        json={
            "identifier": username,
            "password": PASSWORD,
        },
    )
    assert result.status_code == 401 and result.json() == messages[0]
    async with case.database.sessions() as session:
        assert (await session.get(User, pending_id)).password_hash is None


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["absolute", "idle", "revoked", "pending", "disabled"])
async def test_invalid_sessions(auth_case: Harness, condition: str) -> None:
    """Reject every invalid session or inactive account with the same 401 semantics."""
    case = auth_case
    user_id, username = await case.create()
    assert (
        await case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": PASSWORD,
            },
        )
    ).status_code == 200
    token = case.client.cookies.get(case.app.state.auth_settings.cookie_name)
    now = datetime.now(UTC)
    async with case.database.sessions.begin() as session:
        stored = await session.scalar(
            select(Session).where(Session.token_hash == token_digest(token))
        )
        if condition in {"absolute", "idle"}:
            stored.created_at = now - timedelta(hours=10)
            stored.last_activity_at = now - timedelta(minutes=31)
            if condition == "absolute":
                stored.expires_at = now - timedelta(seconds=1)
        elif condition == "revoked":
            stored.revoked_at = now
        else:
            user = await session.get(User, user_id)
            user.status = "pending_activation" if condition == "pending" else "disabled"
            if condition == "pending":
                user.password_hash = None
    for method, path in (("GET", "/api/v1/auth/me"), ("POST", "/api/v1/auth/logout")):
        response = await case.client.request(
            method,
            path,
            headers={
                "Cookie": f"{case.app.state.auth_settings.cookie_name}={token}",
            },
        )
        assert response.status_code == 401
    case.client.cookies.clear()
    case.client.cookies.set(case.app.state.auth_settings.cookie_name, str(user_id))
    assert (await case.client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_invitation_renewal_expiry_and_single_use(auth_case: Harness) -> None:
    """Replace unused links, reject expired links and consume an accepted link only once."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    path = f"/api/v1/admin/users/{user_id}/invite"
    assert (await case.client.post(path)).status_code == 204
    first = case.mailer.messages[-1][1]
    assert (await case.client.post(path)).status_code == 204
    second = case.mailer.messages[-1][1]
    assert first != second
    async with case.database.sessions.begin() as session:
        old = await session.scalar(
            select(AccountInvitation).where(AccountInvitation.token_hash == token_digest(first))
        )
        assert old.revoked_at is not None
        current = await session.scalar(
            select(AccountInvitation).where(AccountInvitation.token_hash == token_digest(second))
        )
        assert current.expires_at - current.created_at == timedelta(hours=48)
        current.created_at = datetime.now(UTC) - timedelta(days=3)
        current.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    failures = []
    for token in (first, second, "x" * 43):
        response = await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "password": PASSWORD,
            },
        )
        assert response.status_code == 400
        failures.append(response.json())
    assert failures[0] == failures[1] == failures[2]
    assert (await case.client.post(path)).status_code == 204
    fresh = case.mailer.messages[-1][1]
    assert (
        await case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": fresh,
                "password": PASSWORD,
            },
        )
    ).status_code == 204
    repeated = await case.client.post(
        "/api/v1/auth/activate",
        json={
            "token": fresh,
            "password": PASSWORD,
        },
    )
    assert repeated.status_code == 400 and repeated.json() == failures[0]
    async with case.database.sessions() as session:
        assert (await session.get(User, user_id)).email_verified_at is not None
        assert (
            await session.scalar(
                select(func.count()).select_from(Session).where(Session.user_id == user_id)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_concurrent_activation(auth_case: Harness) -> None:
    """Allow exactly one winner when the same invitation is submitted concurrently."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    await case.client.post(f"/api/v1/admin/users/{user_id}/invite")
    token = case.mailer.messages[-1][1]
    results = await asyncio.gather(
        *[
            case.client.post("/api/v1/auth/activate", json={"token": token, "password": password})
            for password in (PASSWORD, SECOND_PASSWORD)
        ]
    )
    assert sorted(result.status_code for result in results) == [204, 400]


@pytest.mark.asyncio
async def test_password_change_revokes_every_browser(auth_case: Harness) -> None:
    """Require the current password, then invalidate every session including the caller."""
    case = auth_case
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=case.app),
        base_url="https://testserver",
        headers=HEADERS,
    ) as second:
        await second.post(
            "/api/v1/auth/login",
            json={
                "identifier": case.prefix + "_1",
                "password": PASSWORD,
            },
        )
        response = await case.client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "incorrect",
                "new_password": SECOND_PASSWORD,
            },
        )
        assert response.status_code == 400
        response = await case.client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": PASSWORD,
                "new_password": SECOND_PASSWORD,
            },
        )
        assert response.status_code == 204
        assert (await second.get("/api/v1/auth/me")).status_code == 401
        assert (await case.client.get("/api/v1/auth/me")).status_code == 401
        assert (
            await case.client.post(
                "/api/v1/auth/login",
                json={
                    "identifier": case.prefix + "_1",
                    "password": PASSWORD,
                },
            )
        ).status_code == 401
        assert (
            await case.client.post(
                "/api/v1/auth/login",
                json={
                    "identifier": case.prefix + "_1",
                    "password": SECOND_PASSWORD,
                },
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_rate_limiting_is_shared_and_not_rolled_back(auth_case: Harness) -> None:
    """Share failed IP/identifier budgets without blocking the account from a different IP."""
    case = auth_case
    user_id, username = await case.create()
    configuration = AuthSettings(login_identity_limit=2, login_ip_limit=1000)
    for identifier in (username, username.upper()):
        async with case.database.sessions() as session:
            service = AuthService(
                session,
                configuration,
                case.app.state.identity_cipher,
                case.app.state.passwords,
                case.mailer,
            )
            with pytest.raises(AuthError) as failure:
                await service.login(identifier, "incorrect", "same-ip")
            assert failure.value.status == 401
    async with case.database.sessions() as session:
        service = AuthService(
            session,
            configuration,
            case.app.state.identity_cipher,
            case.app.state.passwords,
            case.mailer,
        )
        with pytest.raises(AuthError) as failure:
            await service.login(username, PASSWORD, "same-ip")
        assert failure.value.status == 429 and failure.value.retry_after > 0
        assert (await service.login(username, PASSWORD, "third-ip"))[0].id == user_id
    async with case.database.sessions() as session:
        assert (await session.get(User, user_id)).login_count == 1


@pytest.mark.asyncio
async def test_csrf_inherited_by_protected_writes(auth_case: Harness) -> None:
    """Reject missing/custom malicious origins while preserving generic messages."""
    case = auth_case
    token = case.admin_token
    for headers in (
        {"Cookie": f"__Host-sophikron_session={token}"},
        {
            "Cookie": f"__Host-sophikron_session={token}",
            "Origin": "https://evil.example",
            "X-CSRF-Protection": "1",
        },
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=case.app),
            base_url="https://testserver",
        ) as attacker:
            response = await attacker.post("/api/v1/test/write", headers=headers)
            assert response.status_code == 403
            assert "csrf" not in response.text.lower()
    assert (await case.client.post("/api/v1/test/write")).status_code == 200


@pytest.mark.asyncio
async def test_delivery_failure_and_duplicates(auth_case: Harness) -> None:
    """Revoke unsuccessful deliveries and enforce canonical database uniqueness."""
    case = auth_case
    user_id, username = await case.create(activate=False)
    case.mailer.fail = True
    assert (await case.client.post(f"/api/v1/admin/users/{user_id}/invite")).status_code == 503
    async with case.database.sessions() as session:
        invitation = await session.scalar(
            select(AccountInvitation).where(AccountInvitation.user_id == user_id)
        )
        assert invitation.revoked_at is not None
    for data in (
        {"username": username.upper(), "email": "distinct@example.org", "roles": ["student"]},
        {
            "username": username + "x",
            "email": username.upper() + "@EXAMPLE.ORG",
            "roles": ["student"],
        },
    ):
        assert (await case.client.post("/api/v1/admin/users", json=data)).status_code == 409
    assert (
        await case.client.post(
            "/api/v1/admin/users",
            json={
                "username": username + "unknown",
                "email": "unknown_role@example.org",
                "roles": ["missing"],
            },
        )
    ).status_code == 422
    async with case.database.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    update(User).where(User.id == user_id).values(status="active")
                )


@pytest.mark.asyncio
async def test_bootstrap_completion_and_no_automatic_recreation(
    auth_case: Harness,
) -> None:
    """Disable bootstrap after handover and prohibit restoring it over a permanent administrator."""
    case = auth_case
    async with case.database.sessions() as session:
        initial = await session.get(User, case.ids[0])
        assert initial.status == "disabled" and initial.email_verified_at is None
    async with case.database.sessions() as session:
        service = AuthService(
            session,
            case.app.state.auth_settings,
            case.app.state.identity_cipher,
            case.app.state.passwords,
            case.mailer,
        )
        assert not await service.initialize_installation()
        with pytest.raises(ValueError, match="already complete"):
            await service.initialize_installation(renew=True)


@pytest.mark.asyncio
async def test_identity_key_rotation_preserves_login(
    auth_case: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-encrypt identities and rebuild keyed indexes without changing UUIDs or passwords."""
    case = auth_case
    previous_path = AuthSettings().keys_file
    new_path = tmp_path / "rotated-keys"
    generate_keys(new_path)
    monkeypatch.setenv("AUTH_KEYS_FILE", str(new_path))
    await execute(
        argparse.Namespace(
            command="rotate-identities", previous_keys_file=previous_path, maintenance=True
        )
    )
    configuration = AuthSettings()
    cipher = IdentityCipher.from_file(new_path)
    async with case.database.sessions() as session:
        service = AuthService(session, configuration, cipher, case.app.state.passwords, case.mailer)
        actor, _ = await service.login(case.prefix + "_1", PASSWORD, "rotation-test")
        assert actor.id == case.administrator


@pytest.mark.asyncio
@pytest.mark.parametrize("bootstrap_password", ["", "simple"])
async def test_automatic_bootstrap_and_renewal(
    migrated_database: None,
    tmp_path: Path,
    bootstrap_password: str,
) -> None:
    """Keep credentials/deadlines stable across restarts and allow explicit local recovery."""
    prefix = "setup_" + uuid4().hex[:10]
    secret = tmp_path / "password"
    secret.write_text(bootstrap_password)
    settings = AuthSettings(bootstrap_username=prefix, bootstrap_password_file=secret)
    app = create_app(auth_settings=settings)
    database = Database(DatabaseSettings())
    user_id = None
    try:
        async with app.router.lifespan_context(app):
            async with database.sessions() as session:
                user = await session.scalar(select(User).where(User.is_bootstrap))
                user_id = user.id
                assert user.email_encrypted is None and user.email_lookup is None
                original_hash, deadline = user.password_hash, user.bootstrap_expires_at
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://testserver",
                headers=HEADERS,
            ) as client:
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={
                            "identifier": prefix,
                            "password": bootstrap_password,
                        },
                    )
                ).status_code == 200
                async with database.sessions.begin() as session:
                    await session.execute(
                        update(User)
                        .where(User.id == user_id)
                        .values(
                            bootstrap_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                        )
                    )
                assert (await client.get("/api/v1/auth/me")).status_code == 401
            secret.write_text(SECOND_PASSWORD)
        restarted = create_app(auth_settings=settings)
        async with restarted.router.lifespan_context(restarted):
            async with database.sessions() as session:
                user = await session.get(User, user_id)
                assert user.password_hash == original_hash
                assert user.bootstrap_expires_at < deadline
                renewed_settings = settings.model_copy(
                    update={"bootstrap_username": prefix + "_new"}
                )
                service = AuthService(
                    session,
                    renewed_settings,
                    restarted.state.identity_cipher,
                    restarted.state.passwords,
                    MemoryMailer(),
                )
                await session.rollback()
                assert await service.initialize_installation(renew=True)
            async with database.sessions() as session:
                user = await session.get(User, user_id)
                assert user.status == "active" and user.password_hash != original_hash
                assert restarted.state.identity_cipher.decrypt(
                    user.id, "username", user.username_encrypted
                ) == prefix + "_new"
                assert await restarted.state.passwords.verify(user.password_hash, SECOND_PASSWORD)
    finally:
        async with database.sessions.begin() as session:
            if user_id:
                await session.execute(delete(User).where(User.id == user_id))
            await session.execute(update(ApplicationState).values(initialized_at=None))
        await database.close()


@pytest.mark.asyncio
async def test_concurrent_bootstrap(migrated_database: None, tmp_path: Path) -> None:
    """Create exactly one temporary account with concurrent independent startup workers."""
    database = Database(DatabaseSettings())
    prefix = "setup_" + uuid4().hex[:10]
    secret = tmp_path / "password"
    secret.write_text(PASSWORD)
    configuration = AuthSettings(bootstrap_username=prefix, bootstrap_password_file=secret)
    cipher = IdentityCipher.from_file(configuration.keys_file)
    passwords = PasswordSecurity(configuration)

    async def initialize() -> bool:
        """Use an independent session as a separate startup worker would."""
        async with database.sessions() as session:
            return await AuthService(
                session, configuration, cipher, passwords, MemoryMailer()
            ).initialize_installation()

    try:
        assert sorted(await asyncio.gather(initialize(), initialize())) == [False, True]
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(User)) == 1
    finally:
        async with database.sessions.begin() as session:
            await session.execute(delete(User).where(User.is_bootstrap))
        await database.close()


@pytest.mark.asyncio
async def test_setup_is_atomic_and_never_reopens(
    migrated_database: None,
    tmp_path: Path,
) -> None:
    """Keep setup retryable, serialize completion and ignore stale bootstrap configuration."""
    prefix = "setup_" + uuid4().hex[:10]
    secret = tmp_path / "secret"
    secret.write_text("admin")
    settings = AuthSettings(bootstrap_username=prefix, bootstrap_password_file=secret)
    app = create_app(auth_settings=settings, mailer=MemoryMailer())
    database = Database(DatabaseSettings())
    ids: list[UUID] = []
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://testserver",
                headers=HEADERS,
            ) as client:
                assert (
                    await client.post(
                        "/api/v1/auth/setup",
                        json={
                            "username": prefix + "_owner",
                            "email": "owner@example.org",
                            "password": PASSWORD,
                        },
                    )
                ).status_code == 401
                login = await client.post(
                    "/api/v1/auth/login",
                    json={
                        "identifier": prefix,
                        "password": "admin",
                    },
                )
                assert login.status_code == 200 and login.json()["email"] is None
                ids.append(UUID(login.json()["id"]))
                bootstrap_token = client.cookies.get(settings.cookie_name)
                body = {"username": prefix, "email": "owner@example.org", "password": PASSWORD}
                assert (await client.post("/api/v1/auth/setup", json=body)).status_code == 409
                async with database.sessions() as session:
                    assert (await session.get(ApplicationState, 1)).initialized_at is None
                    assert (await session.get(User, ids[0])).status == "active"
                body["username"] = prefix + "_owner"
                rejected = await client.post(
                    "/api/v1/auth/setup", json=body, headers={"Origin": "https://evil.example"}
                )
                assert rejected.status_code == 403
                assert (
                    await client.post(
                        "/api/v1/auth/setup",
                        json=body
                        | {
                            "roles": ["student"],
                        },
                    )
                ).status_code == 422
                assert (
                    await client.post(
                        "/api/v1/auth/setup",
                        json=body
                        | {
                            "password": "admin",
                        },
                    )
                ).status_code == 422
                results = await asyncio.gather(
                    client.post("/api/v1/auth/setup", json=body),
                    client.post("/api/v1/auth/setup", json=body),
                )
                assert sorted(r.status_code for r in results)[0] == 201
                assert sorted(r.status_code for r in results)[1] in {401, 403}
                permanent = next(r for r in results if r.status_code == 201).json()
                ids.append(UUID(permanent["id"]))
                assert permanent["roles"] == ["admin"] and permanent["email_verified"] is False
                client.cookies.set(
                    settings.cookie_name, bootstrap_token, domain="testserver.local", path="/"
                )
                assert (await client.get("/api/v1/auth/me")).status_code == 401
                async with database.sessions() as session:
                    initial = await session.get(User, ids[0])
                    assert initial.status == "disabled" and initial.password_hash is None
                    stamp = (await session.get(ApplicationState, 1)).initialized_at
                    assert stamp is not None
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={
                            "identifier": prefix,
                            "password": "admin",
                        },
                    )
                ).status_code == 401
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={
                            "identifier": prefix + "_owner",
                            "password": PASSWORD,
                        },
                    )
                ).status_code == 200
                assert (await client.post("/api/v1/auth/setup", json=body)).status_code == 403
        # Missing username/secret cannot reopen a completed installation, even after deletion
        # of the disabled temporary record by a local operator.
        async with database.sessions.begin() as session:
            await session.execute(delete(User).where(User.id == ids[0]))
        restarted = create_app(
            auth_settings=AuthSettings(
                bootstrap_username=None,
                bootstrap_password_file=tmp_path / "missing",
            )
        )
        async with restarted.router.lifespan_context(restarted):
            async with database.sessions() as session:
                assert (await session.get(ApplicationState, 1)).initialized_at == stamp
                assert await session.scalar(select(func.count()).select_from(User)) == 1
                service = AuthService(
                    session,
                    settings,
                    restarted.state.identity_cipher,
                    restarted.state.passwords,
                    MemoryMailer(),
                )
                await session.rollback()
                with pytest.raises(ValueError, match="already complete"):
                    await service.initialize_installation(renew=True)
    finally:
        async with database.sessions.begin() as session:
            await session.execute(delete(User).where(User.id.in_(ids)))
            await session.execute(update(ApplicationState).values(initialized_at=None))
        await database.close()


@pytest.mark.asyncio
async def test_missing_username_stops_first_start(migrated_database: None) -> None:
    """Fail before creating any temporary account when first-start configuration is absent."""
    app = create_app(auth_settings=AuthSettings(bootstrap_username=None))
    with pytest.raises(ValueError, match="AUTH_BOOTSTRAP_USERNAME"):
        async with app.router.lifespan_context(app):
            pytest.fail("Unconfigured installation unexpectedly started")
    assert not hasattr(app.state, "database")


@pytest.mark.asyncio
async def test_login_rechecks_password_race(
    auth_case: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never issue a session from credentials replaced while their verification was running."""
    case = auth_case
    user_id, username = await case.create()
    checked, release = asyncio.Event(), asyncio.Event()
    original = case.app.state.passwords.verify

    async def paused(encoded: str | None, password: str) -> bool:
        """Pause after real verification to reproduce a concurrent password replacement."""
        valid = await original(encoded, password)
        checked.set()
        await release.wait()
        return valid

    monkeypatch.setattr(case.app.state.passwords, "verify", paused)
    login = asyncio.create_task(
        case.client.post(
            "/api/v1/auth/login",
            json={
                "identifier": username,
                "password": PASSWORD,
            },
        )
    )
    try:
        await asyncio.wait_for(checked.wait(), timeout=5)
        hashed = await case.app.state.passwords.hash(SECOND_PASSWORD)
        async with case.database.sessions.begin() as session:
            await session.execute(
                update(User).where(User.id == user_id).values(password_hash=hashed)
            )
    finally:
        release.set()
    assert (await asyncio.wait_for(login, timeout=5)).status_code == 401
    async with case.database.sessions() as session:
        assert (await session.get(User, user_id)).login_count == 0
        assert (
            await session.scalar(
                select(func.count()).select_from(Session).where(Session.user_id == user_id)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_activation_rechecks_renewal_race(
    auth_case: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an invitation replaced while the activation password was being hashed."""
    case = auth_case
    user_id, _ = await case.create(activate=False)
    path = f"/api/v1/admin/users/{user_id}/invite"
    await case.client.post(path)
    token = case.mailer.messages[-1][1]
    checked, release = asyncio.Event(), asyncio.Event()
    original = case.app.state.passwords.hash

    async def paused(password: str) -> str:
        """Pause after a real hash without holding a database transaction."""
        hashed = await original(password)
        checked.set()
        await release.wait()
        return hashed

    monkeypatch.setattr(case.app.state.passwords, "hash", paused)
    activation = asyncio.create_task(
        case.client.post(
            "/api/v1/auth/activate",
            json={
                "token": token,
                "password": PASSWORD,
            },
        )
    )
    try:
        await asyncio.wait_for(checked.wait(), timeout=5)
        assert (await case.client.post(path)).status_code == 204
    finally:
        release.set()
    assert (await asyncio.wait_for(activation, timeout=5)).status_code == 400
    async with case.database.sessions() as session:
        assert (await session.get(User, user_id)).status == "pending_activation"


@pytest.mark.asyncio
async def test_blocked_ip_cannot_grow_identity_budgets(auth_case: Harness) -> None:
    """Stop adding unknown account keys after the IP quota has already been exhausted."""
    case = auth_case
    configuration = AuthSettings(login_identity_limit=100, login_ip_limit=1)
    for identifier, expected in (("first_unknown", 401), ("second_unknown", 429)):
        async with case.database.sessions() as session:
            service = AuthService(
                session,
                configuration,
                case.app.state.identity_cipher,
                case.app.state.passwords,
                case.mailer,
            )
            with pytest.raises(AuthError) as failure:
                await service.login(identifier, "incorrect", "blocked-test-ip")
            assert failure.value.status == expected
    cipher = case.app.state.identity_cipher
    keys = [
        cipher.lookup("rate:login:identity", f"blocked-test-ip\0username\0{name}")
        for name in (
            "first_unknown",
            "second_unknown",
        )
    ]
    async with case.database.sessions() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AuthRateLimit).where(AuthRateLimit.key.in_(keys))
            )
            == 1
        )
    # A later window starts a fresh budget without needing a background reset job.
    async with case.database.sessions() as session:
        service = AuthService(
            session,
            configuration,
            cipher,
            case.app.state.passwords,
            case.mailer,
            clock=lambda: datetime.now(UTC) + timedelta(minutes=16),
        )
        with pytest.raises(AuthError) as failure:
            await service.login("second_unknown", "incorrect", "blocked-test-ip")
        assert failure.value.status == 401


@pytest.mark.asyncio
async def test_expired_rate_counter_maintenance(auth_case: Harness) -> None:
    """Remove only expired ephemeral counters, preserving accounts and successful-login events."""
    case = auth_case
    expired, active = token_digest(str(uuid4())), token_digest(str(uuid4()))
    async with case.database.sessions.begin() as session:
        session.add_all(
            [
                AuthRateLimit(
                    key=expired, attempts=1, expires_at=datetime.now(UTC) - timedelta(days=1)
                ),
                AuthRateLimit(
                    key=active, attempts=1, expires_at=datetime.now(UTC) + timedelta(days=1)
                ),
            ]
        )
        event_count = await session.scalar(select(func.count()).select_from(LoginEvent))
    try:
        await execute(argparse.Namespace(command="prune-rate-limits"))
        async with case.database.sessions() as session:
            assert await session.get(AuthRateLimit, expired) is None
            assert await session.get(AuthRateLimit, active) is not None
            assert await session.get(User, case.administrator) is not None
            assert await session.scalar(select(func.count()).select_from(LoginEvent)) == event_count
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(
                delete(AuthRateLimit).where(AuthRateLimit.key.in_([expired, active]))
            )


async def login_status(
    case: Harness,
    identifier: str,
    password: str,
    ip: str,
    settings: AuthSettings,
    now: datetime | None = None,
) -> int:
    """Return a service login status using an independent session and optional clock."""
    async with case.database.sessions() as session:
        service = AuthService(
            session, settings, case.app.state.identity_cipher, case.app.state.passwords,
            case.mailer, clock=(lambda: now) if now is not None else None,
        )
        try:
            await service.login(identifier, password, ip)
            return 200
        except AuthError as error:
            return error.status


@pytest.mark.asyncio
@pytest.mark.parametrize("password, expected", [("Abcdefg1!@", 204), ("Abcdefgh12", 422)])
async def test_activation_uses_permanent_password_policy(
    auth_case: Harness, password: str, expected: int
) -> None:
    """Enforce the ten-character four-category policy through the real activation endpoint."""
    case = auth_case
    user_id, username = await case.create(activate=False)
    assert (await case.client.post(f"/api/v1/admin/users/{user_id}/invite")).status_code == 204
    token = case.mailer.messages[-1][1]
    response = await case.client.post(
        "/api/v1/auth/activate", json={"token": token, "password": password}
    )
    assert response.status_code == expected
    if expected == 204:
        assert (await case.client.post(
            "/api/v1/auth/login", json={"identifier": username, "password": password}
        )).status_code == 200


@pytest.mark.asyncio
async def test_login_successes_do_not_consume_or_clear_failures(auth_case: Harness) -> None:
    """Allow repeated successes but retain earlier failures until the fixed window expires."""
    case = auth_case
    user_id, username = await case.create()
    settings = AuthSettings(login_identity_limit=2, login_ip_limit=20)
    parallel_settings = settings.model_copy(update={"login_identity_limit": 6})
    results = await asyncio.gather(*(
        login_status(case, username, PASSWORD, "success-ip", parallel_settings)
        for _ in range(6)
    ))
    assert results == [200] * 6
    assert await login_status(case, username, "incorrect", "success-ip", settings) == 401
    assert await login_status(case, username, PASSWORD, "success-ip", settings) == 200
    assert await login_status(case, username, "incorrect", "success-ip", settings) == 401
    assert await login_status(case, username, PASSWORD, "success-ip", settings) == 429
    async with case.database.sessions() as session:
        assert (await session.get(User, user_id)).login_count == 7
        assert await session.scalar(select(func.count()).select_from(LoginAttempt)) == 0


@pytest.mark.asyncio
async def test_login_window_begins_at_first_failure(auth_case: Harness) -> None:
    """Reset exactly fifteen minutes after the first failure, without sliding on later requests."""
    case = auth_case
    _, username = await case.create()
    settings = AuthSettings(login_identity_limit=2, login_ip_limit=20)
    start = datetime.now(UTC)
    for seconds in (0, 899):
        assert await login_status(
            case, username, "incorrect", "window-ip", settings, start + timedelta(seconds=seconds)
        ) == 401
    assert await login_status(
        case, username, PASSWORD, "window-ip", settings, start + timedelta(seconds=899)
    ) == 429
    assert await login_status(
        case, username, PASSWORD, "window-ip", settings, start + timedelta(seconds=900)
    ) == 200


@pytest.mark.asyncio
async def test_login_aliases_do_not_reveal_account_links(auth_case: Harness) -> None:
    """Apply pair limits independently of account existence or username/email relationships."""
    case = auth_case
    _, username = await case.create()
    settings = AuthSettings(login_identity_limit=2, login_ip_limit=20)
    for identifier in (username, "unknown_" + case.prefix):
        for _ in range(2):
            assert await login_status(case, identifier, "incorrect", "alias-ip", settings) == 401
        assert await login_status(case, identifier, "incorrect", "alias-ip", settings) == 429
    for email in (username + "@example.org", "unknown_" + case.prefix + "@example.org"):
        assert await login_status(case, email, "incorrect", "alias-ip", settings) == 401
    assert await login_status(case, username, PASSWORD, "other-ip", settings) == 200


@pytest.mark.asyncio
async def test_parallel_logins_cannot_exceed_failure_budget(
    auth_case: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Count in-flight leases across sessions so parallel failures cannot overrun the budget."""
    case = auth_case
    _, username = await case.create()
    settings = AuthSettings(login_identity_limit=2, login_ip_limit=20)
    entered, release = asyncio.Event(), asyncio.Event()
    original = case.app.state.passwords.verify
    calls = 0

    async def paused(encoded: str | None, password: str) -> bool:
        """Hold admitted verifications until competing reservations have been rejected."""
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
        await release.wait()
        return await original(encoded, password)

    monkeypatch.setattr(case.app.state.passwords, "verify", paused)
    tasks = [asyncio.create_task(login_status(
        case, username, "incorrect", "parallel-ip", settings
    )) for _ in range(12)]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with asyncio.timeout(5):
            while sum(task.done() for task in tasks) != 10:
                await asyncio.sleep(0.01)
    finally:
        release.set()
        results = await asyncio.gather(*tasks)
    assert results.count(401) == 2 and results.count(429) == 10
    assert calls == 2
    async with case.database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(LoginAttempt)) == 0


@pytest.mark.asyncio
async def test_login_capacity_and_cancellation_release_reservations(
    auth_case: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not charge failures for server saturation or cancelled verification work."""
    from app.core.security import PasswordCapacityError

    case = auth_case
    _, username = await case.create()
    settings = AuthSettings(login_identity_limit=1)

    async def unavailable(encoded: str | None, password: str) -> bool:
        """Simulate exhausted password capacity before credential verification."""
        raise PasswordCapacityError

    original = case.app.state.passwords.verify
    monkeypatch.setattr(case.app.state.passwords, "verify", unavailable)
    with pytest.raises(PasswordCapacityError):
        await login_status(case, username, PASSWORD, "capacity-ip", settings)
    entered = asyncio.Event()

    async def paused(encoded: str | None, password: str) -> bool:
        """Wait for cancellation after a database reservation has committed."""
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(case.app.state.passwords, "verify", paused)
    task = asyncio.create_task(login_status(case, username, PASSWORD, "capacity-ip", settings))
    try:
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    monkeypatch.setattr(case.app.state.passwords, "verify", original)
    assert await login_status(case, username, PASSWORD, "capacity-ip", settings) == 200
    async with case.database.sessions() as session:
        ip_key = case.app.state.identity_cipher.lookup("rate:login:ip", "capacity-ip")
        assert await session.get(AuthRateLimit, ip_key) is None


@pytest.mark.asyncio
async def test_abandoned_login_leases_expire(auth_case: Harness) -> None:
    """Recover capacity after a worker crash without charging a failed password."""
    case = auth_case
    now = datetime.now(UTC)
    cipher = case.app.state.identity_cipher
    from app.repositories.auth import AuthRepository

    ip_key = cipher.lookup("rate:login:ip", "abandoned-ip")
    identity_key = cipher.lookup("rate:login:identity", "abandoned-ip\0username\0unknown")
    async with case.database.sessions.begin() as session:
        lease, _ = await AuthRepository(session).reserve_login(ip_key, identity_key, 1, 1, now, 120)
        assert lease is not None
    settings = AuthSettings(login_ip_limit=1, login_identity_limit=1)
    try:
        assert await login_status(
            case, "unknown", "incorrect", "abandoned-ip", settings, now
        ) == 429
        assert await login_status(
            case, "unknown", "incorrect", "abandoned-ip", settings, now + timedelta(seconds=120)
        ) == 401
    finally:
        async with case.database.sessions.begin() as session:
            await session.execute(delete(LoginAttempt).where(LoginAttempt.id == lease.id))
