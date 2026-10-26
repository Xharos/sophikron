"""Bounded administrator dashboard endpoints; policies and business rules are server-side."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from app.dependencies.auth import AuthServiceDependency, RequirePermission
from app.schemas.administration import (
    AccountArchive,
    AdminAccountResponse,
    DashboardSummary,
    EventPage,
    EventTypeResponse,
    MembershipBatch,
    PromotionArchiveImpact,
    PromotionCreate,
    PromotionPage,
    PromotionResponse,
    PromotionUpdate,
    SearchResult,
    TeachingTeam,
    UserPage,
)
from app.services.administration import AdministrationService
from app.services.auth import UserContext

router = APIRouter(prefix="/admin", tags=["Dashboard"])
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
PositiveId = Annotated[int, Query(gt=0)]
RoleFilter = Literal["user", "kholleur", "teacher", "admin", "teaching"]
StatusFilter = Literal["pending_activation", "active", "disabled"]


def get_administration_service(auth: AuthServiceDependency) -> AdministrationService:
    """Create a service sharing the authenticated request's database resources."""
    return AdministrationService(auth)


Service = Annotated[AdministrationService, Depends(get_administration_service)]
PromotionReader = Annotated[UserContext, Depends(RequirePermission("promotions.read"))]
PromotionManager = Annotated[UserContext, Depends(RequirePermission("promotions.manage"))]
AccountReader = Annotated[UserContext, Depends(RequirePermission("users.read"))]
EventReader = Annotated[UserContext, Depends(RequirePermission("events.read"))]
StatisticReader = Annotated[UserContext, Depends(RequirePermission("statistics.read"))]


@router.get("/summary", response_model=DashboardSummary)
async def summary(actor: StatisticReader, service: Service) -> DashboardSummary:
    """Read global statistics only with the explicit administrator capability."""
    return await service.summary(actor)


@router.get("/team", response_model=TeachingTeam)
async def teaching_team(
    actor: Annotated[UserContext, Depends(RequirePermission("users.manage"))], service: Service
) -> TeachingTeam:
    """Read the administrator-only subject and teaching staff directory."""
    return await service.teaching_team(actor)


@router.get("/promotions/{promotion_id}/archive-impact", response_model=PromotionArchiveImpact)
async def promotion_archive_impact(
    promotion_id: int, actor: PromotionManager, service: Service
) -> PromotionArchiveImpact:
    """Preview pupil login changes before confirming a promotion state change."""
    return await service.promotion_archive_impact(actor, promotion_id)


@router.patch("/users/{user_id}/archive", status_code=204)
async def archive_account(
    user_id: int,
    data: AccountArchive,
    actor: Annotated[UserContext, Depends(RequirePermission("users.manage"))],
    service: Service,
) -> None:
    """Archive/reactivate another permanent account and revoke outstanding access."""
    await service.archive_account(actor, user_id, data)


@router.post("/promotions", status_code=201, response_model=PromotionResponse)
async def create_promotion(
    data: PromotionCreate, actor: PromotionManager, service: Service
) -> PromotionResponse:
    """Create one active promotion; duplicate year/identifier pairs return 409."""
    return await service.create_promotion(actor, data)


@router.get("/promotions", response_model=PromotionPage)
async def list_promotions(
    actor: PromotionReader,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
    year: Annotated[int | None, Query(ge=1, le=9999)] = None,
    is_active: bool | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> PromotionPage:
    """List all promotions, optionally filtered by active/archive state and year."""
    return await service.promotions(
        actor, year=year, is_active=is_active, offset=offset, limit=limit, q=q
    )


@router.get("/promotions/{promotion_id}", response_model=PromotionResponse)
async def promotion(
    promotion_id: int, actor: PromotionReader, service: Service
) -> PromotionResponse:
    """Read a promotion, including an archived one."""
    return await service.promotion(actor, promotion_id)


@router.patch("/promotions/{promotion_id}", response_model=PromotionResponse)
async def update_promotion(
    promotion_id: int, data: PromotionUpdate, actor: PromotionManager, service: Service
) -> PromotionResponse:
    """Edit metadata or set is_active to archive/reactivate a promotion."""
    return await service.update_promotion(actor, promotion_id, data)


@router.get("/promotions/{promotion_id}/users", response_model=UserPage)
async def promotion_users(
    promotion_id: int,
    actor: AccountReader,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
    role: RoleFilter | None = None,
    status: StatusFilter | None = None,
) -> UserPage:
    """Read a promotion's permanent accounts independently of their roles."""
    return await service.users(
        actor, role=role, status=status, promotion_id=promotion_id, offset=offset, limit=limit
    )


@router.post("/promotions/{promotion_id}/users", status_code=204)
async def add_members(
    promotion_id: int, data: MembershipBatch, actor: PromotionManager, service: Service
) -> None:
    """Add selected members with one atomic operation."""
    await service.add_members(actor, promotion_id, data)


@router.get("/users", response_model=UserPage)
async def users(
    actor: AccountReader,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
    role: RoleFilter | None = None,
    status: StatusFilter | None = None,
    promotion_id: PositiveId | None = None,
    exclude_promotion_id: PositiveId | None = None,
) -> UserPage:
    """List accounts ordered by integer ID with optional role, state and membership filters."""
    return await service.users(
        actor,
        role=role,
        status=status,
        promotion_id=promotion_id,
        exclude_promotion_id=exclude_promotion_id,
        offset=offset,
        limit=limit,
    )


@router.get("/users/search", response_model=list[SearchResult])
async def search_users(
    actor: AccountReader,
    service: Service,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
    role: RoleFilter | None = None,
    status: StatusFilter | None = None,
    promotion_id: PositiveId | None = None,
    exclude_promotion_id: PositiveId | None = None,
) -> list[SearchResult]:
    """Find partial and approximate French names without persisting the query or plaintext index."""
    return await service.search(
        actor,
        q,
        role=role,
        status=status,
        promotion_id=promotion_id,
        exclude_promotion_id=exclude_promotion_id,
        limit=limit,
    )


@router.get("/users/{user_id}", response_model=AdminAccountResponse)
async def user(user_id: int, actor: AccountReader, service: Service) -> AdminAccountResponse:
    """Read a permanent account's identity and explicitly assigned permissions."""
    return await service.user(actor, user_id)


@router.get("/users/{user_id}/promotions", response_model=PromotionPage)
async def user_promotions(
    user_id: int,
    actor: PromotionReader,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
) -> PromotionPage:
    """Read all memberships, including archived promotions."""
    return await service.promotions(
        actor, year=None, is_active=None, offset=offset, limit=limit, user_id=user_id
    )


@router.put("/users/{user_id}/promotions/{promotion_id}", status_code=204)
async def add_membership(
    user_id: int, promotion_id: int, actor: PromotionManager, service: Service
) -> None:
    """Idempotently add an account to an active promotion."""
    await service.membership(actor, user_id, promotion_id, add=True)


@router.delete("/users/{user_id}/promotions/{promotion_id}", status_code=204)
async def remove_membership(
    user_id: int, promotion_id: int, actor: PromotionManager, service: Service
) -> None:
    """Remove only the association, including from an archived promotion."""
    await service.membership(actor, user_id, promotion_id, add=False)


@router.get("/events/types", response_model=list[EventTypeResponse])
async def event_types(actor: EventReader, service: Service) -> list[EventTypeResponse]:
    """Expose the authorized event catalogue without loading any journal rows."""
    return await service.event_types(actor)


@router.get("/events", response_model=EventPage)
async def events(
    actor: EventReader,
    service: Service,
    limit: Limit = 50,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    event_type: Annotated[str | None, Query(max_length=96)] = None,
    actor_user_id: PositiveId | None = None,
    subject_user_id: PositiveId | None = None,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: PositiveId | None = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> EventPage:
    """Read an immutable journal with ID cursors and optional timezone-aware period filters."""
    return await service.events(
        actor,
        cursor=cursor,
        limit=limit,
        event_type=event_type,
        actor_user_id=actor_user_id,
        subject_user_id=subject_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        since=since,
        until=until,
        order=order,
    )
