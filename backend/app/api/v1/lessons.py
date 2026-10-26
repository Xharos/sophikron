"""Authenticated course routes; all page, element and grant policies are checked server-side."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.administration import PromotionBadge
from app.schemas.lessons import (
    ElementCreate,
    ElementMove,
    ElementUpdate,
    LessonDetail,
    LessonFields,
    LessonPage,
    LessonPerson,
    LessonUpdate,
    PromotionGrant,
    ResponsibilityUpdate,
    TableChange,
    Versioned,
)
from app.services.lessons import LessonService

router = APIRouter(prefix="/lessons", tags=["Courses"])
Identifier = Annotated[int, Path(gt=0)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=50)]


def get_lesson_service(auth: AuthServiceDependency) -> LessonService:
    """Build the business service from the authenticated request's resources."""
    return LessonService(auth)


Service = Annotated[LessonService, Depends(get_lesson_service)]


@router.delete("/{lesson_id}", status_code=204)
async def remove_lesson(
    lesson_id: Identifier, data: Versioned, actor: AuthenticatedUser, service: Service
) -> Response:
    """Remove an entire course and atomically queue all attached disk files for deletion."""
    await service.remove(actor, lesson_id, data.expected_version)
    return Response(status_code=204)


@router.post("/{lesson_id}/elements/{element_id}/table", response_model=LessonDetail)
async def change_table(
    lesson_id: Identifier,
    element_id: Identifier,
    data: TableChange,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Add/remove rows and columns or rename an arbitrary author-defined column."""
    return await service.change_table(actor, lesson_id, element_id, data)


@router.put("/{lesson_id}/responsibility", response_model=LessonDetail)
async def transfer(
    lesson_id: Identifier, data: ResponsibilityUpdate, actor: AuthenticatedUser, service: Service
) -> LessonDetail:
    """Reassign a course and its subject exclusively through a current administrator."""
    return await service.transfer(actor, lesson_id, data)


@router.get("", response_model=LessonPage)
async def catalogue(
    actor: AuthenticatedUser,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 24,
    q: Annotated[str, Query(max_length=160)] = "",
) -> dict[str, object]:
    """List all cards without exposing protected bodies or promotion rosters."""
    return await service.catalogue(actor, offset=offset, limit=limit, q=q)


@router.post("", status_code=201, response_model=LessonDetail)
async def create(data: LessonFields, actor: AuthenticatedUser, service: Service) -> LessonDetail:
    """Create a page only when the current account still has the teacher capability."""
    return await service.create(actor, data)


@router.get("/{lesson_id}", response_model=LessonDetail)
async def detail(lesson_id: Identifier, actor: AuthenticatedUser, service: Service) -> LessonDetail:
    """Authorize page access and filter unavailable student content before serialization."""
    return await service.detail(actor, lesson_id)


@router.put("/{lesson_id}", response_model=LessonDetail)
async def update(
    lesson_id: Identifier,
    data: LessonUpdate,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Save metadata with optimistic concurrency and current authorization checks."""
    return await service.update(actor, lesson_id, data)


@router.post("/{lesson_id}/elements", status_code=201, response_model=LessonDetail)
async def add_element(
    lesson_id: Identifier,
    data: ElementCreate,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Add a section, subsection, text or validated YouTube link."""
    return await service.add_element(actor, lesson_id, data)


@router.put("/{lesson_id}/elements/{element_id}", response_model=LessonDetail)
async def update_element(
    lesson_id: Identifier,
    element_id: Identifier,
    data: ElementUpdate,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Edit an existing element without changing its parent or type."""
    return await service.change_element(actor, lesson_id, element_id, data)


@router.delete("/{lesson_id}/elements/{element_id}", response_model=LessonDetail)
async def remove_element(
    lesson_id: Identifier,
    element_id: Identifier,
    data: Versioned,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Remove the selected subtree and record a successful deletion event."""
    return await service.remove_element(actor, lesson_id, element_id, data.expected_version)


@router.post("/{lesson_id}/elements/{element_id}/move", response_model=LessonDetail)
async def move_element(
    lesson_id: Identifier,
    element_id: Identifier,
    data: ElementMove,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Reorder siblings without allowing cross-page or arbitrary reparenting operations."""
    return await service.move_element(actor, lesson_id, element_id, data)


@router.put("/{lesson_id}/collaborators/{user_id}", response_model=LessonDetail)
async def add_collaborator(
    lesson_id: Identifier,
    user_id: Identifier,
    data: Versioned,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Immediately add an active teacher, exclusively through the creator or administrator."""
    return await service.collaborator(actor, lesson_id, user_id, data.expected_version, add=True)


@router.delete("/{lesson_id}/collaborators/{user_id}", response_model=LessonDetail)
async def remove_collaborator(
    lesson_id: Identifier,
    user_id: Identifier,
    data: Versioned,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Revoke collaboration without deleting or changing the target account."""
    return await service.collaborator(actor, lesson_id, user_id, data.expected_version, add=False)


@router.put("/{lesson_id}/promotions/{promotion_id}", response_model=LessonDetail)
async def grant_promotion(
    lesson_id: Identifier,
    promotion_id: Identifier,
    data: PromotionGrant,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Grant or renew an active promotion's period, defaulting to August 31 of the next year."""
    return await service.promotion(actor, lesson_id, promotion_id, data, add=True)


@router.delete("/{lesson_id}/promotions/{promotion_id}", response_model=LessonDetail)
async def revoke_promotion(
    lesson_id: Identifier,
    promotion_id: Identifier,
    data: Versioned,
    actor: AuthenticatedUser,
    service: Service,
) -> LessonDetail:
    """Immediately revoke page access while retaining catalogue visibility."""
    return await service.promotion(
        actor,
        lesson_id,
        promotion_id,
        PromotionGrant(expected_version=data.expected_version),
        add=False,
    )


@router.get("/{lesson_id}/promotion-options", response_model=list[PromotionBadge])
async def promotion_options(
    lesson_id: Identifier,
    actor: AuthenticatedUser,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
) -> list[PromotionBadge]:
    """Offer active promotion metadata to editors without exposing accounts or memberships."""
    return await service.promotion_options(actor, lesson_id, offset, limit)


@router.get("/{lesson_id}/teacher-options", response_model=list[LessonPerson])
async def teacher_options(
    lesson_id: Identifier,
    actor: AuthenticatedUser,
    service: Service,
    q: Annotated[str, Query(max_length=100)] = "",
) -> list[LessonPerson]:
    """Offer five eligible, unassociated staff accounts, including for an empty query."""
    return await service.teacher_options(actor, lesson_id, q)


@router.get("/{lesson_id}/responsible-options", response_model=list[LessonPerson])
async def responsible_options(
    lesson_id: Identifier,
    actor: AuthenticatedUser,
    service: Service,
    subject_id: Annotated[int, Query(gt=0)],
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> list[LessonPerson]:
    """Offer eligible responsibility candidates only to administrators."""
    return await service.responsible_options(actor, lesson_id, subject_id, q)
