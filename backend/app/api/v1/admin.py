"""Minimal administrator account creation and explicit invitation delivery endpoints."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.dependencies.auth import AdminUser, AuthServiceDependency, client_ip
from app.schemas.auth import CreateUserRequest, UserResponse

router = APIRouter(prefix="/admin", tags=["Administration"])


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
    user_id: UUID,
    administrator: AdminUser,
    request: Request,
    service: AuthServiceDependency,
) -> None:
    """Issue a new invitation, invalidating every previous unused invitation."""
    await service.invite(administrator, user_id, client_ip(request))
