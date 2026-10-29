"""Aggregate statistics with independent global, author and course authorization."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Request

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.statistics import Period, StatisticsResponse
from app.services.api_monitoring import ApiMonitoringService
from app.services.errors import AuthError
from app.services.statistics import StatisticsService

router = APIRouter(tags=["Statistics"])


@router.get("/admin/monitoring")
async def api_monitoring(
    request: Request,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    period: Period = "day",
    category: str = "all",
    interval: datetime | None = None,
) -> dict:
    """Read reduced performance aggregates or one interval's exact codes as an administrator."""
    result = await ApiMonitoringService(auth).read(actor, period, category, interval)
    result["pending_interval_seconds"] = 30
    result["dropped_measurements"] = request.app.state.api_monitor.dropped
    return result


@router.get("/admin/statistics", response_model=StatisticsResponse)
async def administration_statistics(
    request: Request, actor: AuthenticatedUser, auth: AuthServiceDependency, period: Period = "week"
) -> StatisticsResponse:
    """Expose global statistics only to the explicit statistics reader permission."""
    if "statistics.read" not in actor.profile.permissions:
        raise AuthError(403, "Statistiques réservées aux administrateurs.")
    return await StatisticsService(auth, request.app.state.document_settings).read(actor, period)


@router.get("/teaching/statistics", response_model=StatisticsResponse)
async def author_statistics(
    request: Request, actor: AuthenticatedUser, auth: AuthServiceDependency, period: Period = "week"
) -> StatisticsResponse:
    """Show only the current author's own courses unless the caller has global permission."""
    return await StatisticsService(auth, request.app.state.document_settings).read(actor, period)


@router.get("/lessons/{lesson_id}/statistics", response_model=StatisticsResponse)
async def course_statistics(
    lesson_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    request: Request,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    period: Period = "week",
) -> StatisticsResponse:
    """Authorize current authorship, responsibility or collaboration on this precise course."""
    return await StatisticsService(auth, request.app.state.document_settings).read(
        actor, period, lesson_id
    )
