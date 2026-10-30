"""Annotated authorization aliases and browser request protections."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.documents import is_document_upload
from app.services.auth import AuthService, UserContext
from app.services.errors import FORBIDDEN, INVALID_REQUEST, AuthError

secure_cookie = APIKeyCookie(name="__Host-sophikron_session", auto_error=False)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    """Construct a request-scoped service using application-owned security resources."""
    state = request.app.state
    return AuthService(
        session,
        state.auth_settings,
        state.identity_cipher,
        state.passwords,
        state.mailer,
        name_search_cache=state.name_search_cache,
    )


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]


def client_ip(request: Request) -> str:
    """Use ASGI's peer address, accounting only for the server's explicitly trusted proxies."""
    return request.client.host if request.client else "unknown"


def require_csrf(
    request: Request,
    csrf_protection: Annotated[
        str | None,
        Header(alias="X-CSRF-Protection", description="Use 1 for browser write requests"),
    ] = None,
) -> None:
    """Require a custom browser header and an exact trusted origin for unsafe methods."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        if referer:
            try:
                parsed = urlsplit(referer)
            except ValueError:
                raise AuthError(403, INVALID_REQUEST) from None
            if parsed.scheme and parsed.netloc and not parsed.username and not parsed.password:
                origin = f"{parsed.scheme}://{parsed.netloc}"
    if (
        request.headers.get("x-csrf-protection") != "1"
        or origin not in request.app.state.auth_settings.allowed_origins
    ):
        raise AuthError(403, INVALID_REQUEST)
    if request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers:
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        expected_type = (
            "application/octet-stream"
            if is_document_upload(request.url.path, request.method)
            else "application/json"
        )
        if media_type != expected_type:
            raise AuthError(415, INVALID_REQUEST)


async def get_current_user(
    request: Request,
    service: AuthServiceDependency,
    documented_cookie: Annotated[str | None, Depends(secure_cookie)],
    csrf_protection: Annotated[
        str | None,
        Header(alias="X-CSRF-Protection", description="Use 1 for browser write requests"),
    ] = None,
) -> UserContext:
    """Authenticate before CSRF checks, returning 401 for every inactive or invalid session."""
    settings = request.app.state.auth_settings
    token = (
        documented_cookie if settings.cookie_secure else request.cookies.get(settings.cookie_name)
    )
    actor = await service.authenticate(token)
    require_csrf(request)
    if actor.profile.is_bootstrap:
        path = request.url.path
        permitted = path in {
            "/api/v1/auth/me",
            "/api/v1/auth/logout",
            "/api/v1/auth/setup",
        }
        if not permitted:
            raise AuthError(403, FORBIDDEN)
    return actor


AuthenticatedUser = Annotated[UserContext, Depends(get_current_user)]


class RequireRole:
    """Require at least one explicit role after the common active-account session check."""

    def __init__(self, *roles: str) -> None:
        """Refuse empty policies so missing configuration never grants access."""
        if not roles or any(not role for role in roles):
            raise ValueError("At least one role is required")
        self.roles = frozenset(roles)

    async def __call__(self, user: AuthenticatedUser) -> UserContext:
        """Return the authenticated principal or a generic forbidden response."""
        if not self.roles.intersection(user.roles):
            raise AuthError(403, FORBIDDEN)
        return user


class RequirePermission:
    """Require an explicit capability instead of inferring capabilities from role names."""

    def __init__(self, permission: str) -> None:
        """Refuse an empty permission policy."""
        if not permission:
            raise ValueError("A permission is required")
        self.permission = permission

    async def __call__(self, user: AuthenticatedUser) -> UserContext:
        """Return a verified principal or deny missing capabilities."""
        if self.permission not in user.permissions:
            raise AuthError(403, FORBIDDEN)
        return user


AdminUser = Annotated[UserContext, Depends(RequirePermission("users.manage"))]
TeacherUser = Annotated[UserContext, Depends(RequirePermission("teacher.access"))]
UserAccount = Annotated[UserContext, Depends(RequirePermission("user.access"))]
