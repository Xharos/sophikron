"""Minimal administrator account creation and explicit invitation delivery endpoints."""

from fastapi import APIRouter, Request

from app.dependencies.auth import AdminUser, AuthServiceDependency, client_ip
from app.schemas.auth import (
    AccessInvitationResponse,
    CreateUserRequest,
    ManualInvitationResponse,
    UserResponse,
)

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.post("/users/{user_id}/access-invitation", response_model=AccessInvitationResponse)
async def access_invitation(
    user_id: int, administrator: AdminUser, request: Request, service: AuthServiceDependency
) -> AccessInvitationResponse:
    """Reissue activation or password-reset access using automatic delivery selection."""
    return await service.access_invitation(administrator, user_id, client_ip(request))


@router.post("/users", status_code=201, response_model=UserResponse)
async def create_user(
    data: CreateUserRequest,
    administrator: AdminUser,
    service: AuthServiceDependency,
) -> UserResponse:
    """Create an unactivated account with an explicit set of existing roles."""
    return await service.create_user(administrator, data)


@router.post("/users/{user_id}/invite", status_code=204)
async def invite_user(
    user_id: int,
    administrator: AdminUser,
    request: Request,
    service: AuthServiceDependency,
) -> None:
    """Issue a new invitation, invalidating every previous unused invitation."""
    await service.invite(administrator, user_id, client_ip(request))


@router.post("/users/{user_id}/manual-invitation", response_model=ManualInvitationResponse)
async def invite_user_manually(
    user_id: int,
    administrator: AdminUser,
    request: Request,
    service: AuthServiceDependency,
) -> ManualInvitationResponse:
    """Return a single-use invitation only when manual delivery is explicitly enabled."""
    return await service.invite_manually(administrator, user_id, client_ip(request))
