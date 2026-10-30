"""Explicit full-profile routes kept separate from minimal directory and modal responses."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import (
    AdminUser,
    AuthenticatedUser,
    AuthServiceDependency,
    RequirePermission,
)
from app.schemas.profile import AdminProfileUpdate, FullProfile, OrientationUpdate
from app.services.auth import UserContext
from app.services.communes import Commune, search_communes
from app.services.profiles import ProfileService

router = APIRouter(tags=["School profiles"])
Teacher = Annotated[UserContext, Depends(RequirePermission("teaching.read"))]


@router.get("/auth/me/profile", response_model=FullProfile)
async def own_profile(actor: AuthenticatedUser, auth: AuthServiceDependency) -> FullProfile:
    """Read the caller's private profile without granting self-editing rights."""
    return await ProfileService(auth).read(actor, actor.id, owner=True)


@router.get("/admin/communes", response_model=list[Commune])
async def communes(
    actor: AdminUser,
    auth: AuthServiceDependency,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> list[Commune]:
    """Search the free public French commune reference without sending student identities."""
    async with auth.db.begin():
        await auth._actor(actor, permission="profiles.manage")
    return await search_communes(q.strip())


@router.get("/admin/users/{user_id}/profile", response_model=FullProfile)
async def admin_profile(user_id: int, actor: AdminUser, auth: AuthServiceDependency) -> FullProfile:
    """Read one permanent account's complete school profile."""
    return await ProfileService(auth).read(actor, user_id)


@router.patch("/admin/users/{user_id}/profile", response_model=FullProfile)
async def update_admin_profile(
    user_id: int,
    data: AdminProfileUpdate,
    actor: AdminUser,
    auth: AuthServiceDependency,
) -> FullProfile:
    """Save an administrator's validated patch and preserve the generated username."""
    return await ProfileService(auth).update(actor, user_id, data)


@router.get("/teaching/users/{user_id}/profile", response_model=FullProfile)
async def teacher_profile(user_id: int, actor: Teacher, auth: AuthServiceDependency) -> FullProfile:
    """Read complete information only for students in the teacher's promotions."""
    return await ProfileService(auth).read(actor, user_id)


@router.patch("/teaching/users/{user_id}/profile", response_model=FullProfile)
async def update_orientation(
    user_id: int,
    data: OrientationUpdate,
    actor: Teacher,
    auth: AuthServiceDependency,
) -> FullProfile:
    """Update exactly the orientation project after checking current membership and permission."""
    return await ProfileService(auth).update(actor, user_id, data)
