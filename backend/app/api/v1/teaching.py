"""Teacher directory routes with SQL-enforced scope and no mutation operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import AuthServiceDependency, RequirePermission
from app.schemas.administration import PromotionPage, SearchResult, StudentPage, StudentResponse
from app.services.auth import UserContext
from app.services.teaching import TeachingService

router = APIRouter(prefix="/teaching", tags=["Teaching"])
Teacher = Annotated[UserContext, Depends(RequirePermission("teaching.read"))]


def teaching_service(auth: AuthServiceDependency) -> TeachingService:
    """Build a teacher service using the authenticated request's session."""
    return TeachingService(auth)


Service = Annotated[TeachingService, Depends(teaching_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/promotions", response_model=PromotionPage)
async def promotions(
    actor: Teacher,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
    q: Annotated[str | None, Query(max_length=100)] = None,
    is_active: bool | None = None,
) -> PromotionPage:
    """Read the teacher's promotions and role-specific student counts."""
    return await service.promotions(actor, offset=offset, limit=limit, q=q, is_active=is_active)


@router.get("/users", response_model=StudentPage)
async def students(
    actor: Teacher,
    service: Service,
    offset: Offset = 0,
    limit: Limit = 50,
    promotion_id: Annotated[int | None, Query(gt=0)] = None,
) -> StudentPage:
    """Read students, including archived accounts, within shared promotions."""
    return await service.students(actor, promotion_id=promotion_id, offset=offset, limit=limit)


@router.get("/users/search", response_model=list[SearchResult])
async def search(
    actor: Teacher,
    service: Service,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    promotion_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> list[SearchResult]:
    """Search authorized students without exposing the global directory."""
    return await service.search(actor, q, promotion_id=promotion_id, limit=limit)


@router.get("/users/{user_id}", response_model=StudentResponse)
async def student(user_id: int, actor: Teacher, service: Service) -> StudentResponse:
    """Read a restricted student card without email, login history or invitation details."""
    return await service.student(actor, user_id)
