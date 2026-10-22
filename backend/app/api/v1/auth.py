"""Cookie authentication HTTP endpoints; account rules belong to services."""

from fastapi import APIRouter, Depends, Request, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency, client_ip, require_csrf
from app.schemas.auth import (
    ActivateRequest,
    ChangePasswordRequest,
    CompleteSetupRequest,
    LoginRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def clear_session_cookie(request: Request, response: Response) -> None:
    """Expire the same host-only cookie that was issued during login."""
    settings = request.app.state.auth_settings
    response.delete_cookie(
        settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )


@router.post("/login", response_model=UserResponse, dependencies=[Depends(require_csrf)])
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> UserResponse:
    """Verify credentials and issue an opaque, host-only HttpOnly cookie."""
    settings = request.app.state.auth_settings
    actor, token = await service.login(
        data.identifier,
        data.password.get_secret_value(),
        client_ip(request),
        request.cookies.get(settings.cookie_name),
    )
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.session_seconds,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return actor.profile


@router.post("/activate", status_code=204, dependencies=[Depends(require_csrf)])
async def activate(
    data: ActivateRequest,
    request: Request,
    service: AuthServiceDependency,
) -> None:
    """Consume an invitation and set the initial password without issuing a session."""
    await service.activate(
        data.token.get_secret_value(), data.password.get_secret_value(), client_ip(request)
    )


@router.get("/me", response_model=UserResponse)
async def me(user: AuthenticatedUser) -> UserResponse:
    """Return only the identity and current roles of the authenticated account."""
    return user.profile


@router.post("/logout", status_code=204)
async def logout(
    user: AuthenticatedUser,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> None:
    """Revoke the current browser session and remove its cookie."""
    await service.logout(user)
    clear_session_cookie(request, response)


@router.post("/change-password", status_code=204)
async def change_password(
    data: ChangePasswordRequest,
    user: AuthenticatedUser,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> None:
    """Change the password with current-password proof and revoke all browser sessions."""
    await service.change_password(
        user,
        data.current_password.get_secret_value(),
        data.new_password.get_secret_value(),
        client_ip(request),
    )
    clear_session_cookie(request, response)


@router.post("/setup", response_model=UserResponse, status_code=201)
async def complete_setup(
    data: CompleteSetupRequest,
    user: AuthenticatedUser,
    request: Request,
    response: Response,
    service: AuthServiceDependency,
) -> UserResponse:
    """Finish initial setup without SMTP, revoke bootstrap sessions and require a fresh login."""
    permanent = await service.complete_setup(user, data, client_ip(request))
    clear_session_cookie(request, response)
    return permanent
