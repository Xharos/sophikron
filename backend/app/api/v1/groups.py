"""Scoped promotion-group consultation and administrator-only draft and save routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.administration import PromotionPage, PromotionResponse
from app.schemas.groups import (
    CustomGroupSave,
    CustomGroupVersion,
    GroupDraft,
    PartitionGenerate,
    PartitionKind,
    PartitionResponse,
    PartitionSave,
    PartitionVersion,
    PromotionGroupsResponse,
)
from app.services.custom_groups import CustomGroupsService
from app.services.groups import GroupsService

router = APIRouter(prefix="/promotion-groups", tags=["Promotion groups"])


def groups_service(auth: AuthServiceDependency) -> GroupsService:
    """Build the service using the current authenticated request session."""
    return GroupsService(auth)


Service = Annotated[GroupsService, Depends(groups_service)]


@router.get("/{promotion_id}/custom/groups")
async def custom_groups(
    promotion_id: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """List overlapping named audiences inside current staff scope."""
    return await CustomGroupsService(auth).read_custom(actor, promotion_id)


@router.put("/{promotion_id}/custom/{identifier}")
async def save_custom_group(
    promotion_id: int,
    identifier: int,
    data: CustomGroupSave,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
) -> dict:
    """Create with identifier zero or update a named audience as administrator."""
    return await CustomGroupsService(auth).save_custom(actor, promotion_id, identifier, data)


@router.delete("/{promotion_id}/custom/{identifier}")
async def delete_custom_group(
    promotion_id: int,
    identifier: int,
    data: CustomGroupVersion,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
) -> dict:
    """Remove a custom group from future choices without deleting assigned sessions."""
    return await CustomGroupsService(auth).delete_custom(actor, promotion_id, identifier, data)


@router.get("/promotions", response_model=PromotionPage)
async def promotions(
    actor: AuthenticatedUser,
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
) -> PromotionPage:
    """List promotions inside current staff scope without opening profile APIs."""
    return await service.promotions(actor, offset=offset, limit=limit, q=q, is_active=is_active)


@router.get("/{promotion_id}", response_model=PromotionGroupsResponse)
async def read(
    promotion_id: int,
    actor: AuthenticatedUser,
    service: Service,
) -> PromotionGroupsResponse:
    """Read names and partitions only for an authorized promotion."""
    return await service.read(actor, promotion_id)


@router.get("/promotions/{promotion_id}", response_model=PromotionResponse)
async def promotion(
    promotion_id: int,
    actor: AuthenticatedUser,
    service: Service,
) -> PromotionResponse:
    """Read one promotion's metadata after enforcing current staff scope."""
    return await service.promotion(actor, promotion_id)


@router.post("/{promotion_id}/{kind}/preview", response_model=list[GroupDraft])
async def preview(
    promotion_id: int,
    kind: PartitionKind,
    data: PartitionGenerate,
    actor: AuthenticatedUser,
    service: Service,
) -> list[GroupDraft]:
    """Generate an editable random preview without altering persisted assignments."""
    return await service.preview(actor, promotion_id, kind, data)


@router.put("/{promotion_id}/{kind}", response_model=PartitionResponse)
async def save(
    promotion_id: int,
    kind: PartitionKind,
    data: PartitionSave,
    actor: AuthenticatedUser,
    service: Service,
) -> PartitionResponse:
    """Save an administrator's complete validated replacement atomically."""
    return await service.save(actor, promotion_id, kind, data)


@router.delete("/{promotion_id}/{kind}", status_code=204)
async def delete(
    promotion_id: int,
    kind: PartitionKind,
    data: PartitionVersion,
    actor: AuthenticatedUser,
    service: Service,
) -> Response:
    """Remove this partition alone after checking the editor's revision."""
    await service.delete(actor, promotion_id, kind, data)
    return Response(status_code=204)
