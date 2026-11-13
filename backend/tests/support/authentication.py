"""Shared synthetic fixtures and helpers; never collected as tests."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx2 as httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select, update

from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.core.database import Database
from app.dependencies.auth import AuthenticatedUser, TeacherUser, UserAccount
from app.main import create_app
from app.models import (
    AccountInvitation,
    ApplicationState,
    User,
)
from app.services.auth import AuthService
from app.services.errors import AuthError
from app.services.mail import MailDeliveryError
from tests.support.cleanup import clear_test_events

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
    ids: list[int] = field(default_factory=list)
    administrator: int | None = None
    admin_token: str = ""
    admin_username: str = ""
    emails: dict[str, str] = field(default_factory=dict)

    def as_admin(self) -> None:
        """Restore the fixture administrator's browser cookie after a role-specific login."""
        self.client.cookies.clear()
        self.client.cookies.set(
            self.app.state.auth_settings.cookie_name,
            self.admin_token,
            domain="testserver.local",
            path="/",
        )

    async def create(self, role: str = "user", *, activate: bool = True) -> tuple[int, str]:
        """Create and optionally activate a uniquely named account through the real HTTP API."""
        self.as_admin()
        username = f"{self.prefix}_{len(self.ids)}"
        response = await self.client.post(
            "/api/v1/admin/users",
            json={
                "first_name": "Exemple",
                "last_name": "Fictif",
                "email": f"{username}@example.org",
                "roles": [role],
            },
        )
        assert response.status_code == 201, response.text
        email = f"{username}@example.org"
        username = response.json()["username"]
        self.emails[username] = email
        user_id = int(response.json()["id"])
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
    async def student(user: UserAccount) -> dict[str, str]:
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
                            "first_name": "Exemple",
                            "last_name": "Fictif",
                            "email": f"{prefix}_forbidden@example.org",
                            "roles": ["teacher"],
                        },
                    )
                ).status_code == 403
                case.admin_token = client.cookies.get(app.state.auth_settings.cookie_name)
                response = await client.post(
                    "/api/v1/auth/setup",
                    json={
                        "first_name": "Exemple",
                        "last_name": "Fictif",
                        "email": f"{prefix}_1@example.org",
                        "password": PASSWORD,
                    },
                )
                assert response.status_code == 201, response.text
                case.admin_username = response.json()["username"]
                owner = int(response.json()["id"])
                case.ids.append(owner)
                case.administrator = owner
                assert (await client.get("/api/v1/auth/me")).status_code == 401
                assert (
                    await client.post(
                        "/api/v1/auth/login",
                        json={
                            "identifier": case.admin_username,
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
                await clear_test_events(case.ids)
                await session.execute(delete(User).where(User.id.in_(case.ids)))
                await session.execute(update(ApplicationState).values(initialized_at=None))
        await database.close()


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
            session,
            settings,
            case.app.state.identity_cipher,
            case.app.state.passwords,
            case.mailer,
            clock=(lambda: now) if now is not None else None,
        )
        try:
            await service.login(identifier, password, ip)
            return 200
        except AuthError as error:
            return error.status
