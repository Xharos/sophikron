"""Explicit public presentation reads and administrator-only configuration routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.dependencies.auth import AdminUser, AuthenticatedUser, AuthServiceDependency
from app.schemas.lessons import Versioned
from app.schemas.site import (
    CourseImpact,
    EventFields,
    EventUpdate,
    PublicSite,
    SettingsResponse,
    SettingsUpdate,
    SubjectFields,
    SubjectResponse,
    SubjectUpdate,
    TimelineFields,
    TimelineUpdate,
)
from app.services.course_rights import course_impact
from app.services.site import SiteService

router = APIRouter(tags=["Site configuration"])
Identifier = Annotated[int, Path(gt=0)]


def get_site_service(auth: AuthServiceDependency) -> SiteService:
    """Construct a service without requiring authentication for public reads."""
    return SiteService(auth)


Service = Annotated[SiteService, Depends(get_site_service)]


@router.get("/site", response_model=PublicSite)
async def public_site(service: Service) -> PublicSite:
    """Publish the configured homepage without any private account or teaching data."""
    return await service.public()


@router.get("/admin/subjects")
async def subjects(
    actor: AdminUser,
    service: Service,
    q: Annotated[str, Query(max_length=100)] = "",
    is_active: bool | None = True,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    """List searchable subject metadata and administrator aggregates."""
    return await service.subjects(actor, q=q, is_active=is_active, offset=offset, limit=limit)


@router.get("/lessons/subject-options")
async def subject_options(
    actor: AuthenticatedUser,
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict[str, object]:
    """Offer only subjects currently assigned to the authenticated teacher."""
    return await service.subjects(actor, mine=True, offset=offset, limit=limit)


@router.post("/admin/subjects", response_model=SubjectResponse, status_code=201)
async def subject_create(
    data: SubjectFields, actor: AdminUser, service: Service
) -> SubjectResponse:
    """Create an active subject."""
    return await service.subject_save(actor, data)


@router.put("/admin/subjects/{subject_id}", response_model=SubjectResponse)
async def subject_update(
    subject_id: Identifier, data: SubjectUpdate, actor: AdminUser, service: Service
) -> SubjectResponse:
    """Update the identity inherited by all courses."""
    return await service.subject_save(actor, data, subject_id)


@router.delete("/admin/subjects/{subject_id}", status_code=204)
async def subject_archive(
    subject_id: Identifier, data: Versioned, actor: AdminUser, service: Service
) -> Response:
    """Archive an unused subject and revoke its teacher assignments."""
    await service.subject_archive(actor, subject_id, data.expected_version)
    return Response(status_code=204)


@router.get("/admin/users/{user_id}/course-impact", response_model=list[CourseImpact])
async def account_courses(
    user_id: Identifier, actor: AdminUser, service: Service
) -> list[CourseImpact]:
    """Identify course responsibilities before revoking account capabilities."""
    async with service.db.begin():
        await service.auth._actor(actor, admin=True)
        return await course_impact(service.db, user_id)


@router.put("/admin/site", response_model=SettingsResponse)
async def settings_save(
    data: SettingsUpdate, actor: AdminUser, service: Service
) -> SettingsResponse:
    """Apply live public presentation settings."""
    return await service.settings_save(actor, data)


@router.post("/admin/timelines", status_code=201)
async def timeline_create(data: TimelineFields, actor: AdminUser, service: Service) -> object:
    """Create an annual timeline."""
    return await service.calendar_save(actor, data, event=False)


@router.put("/admin/timelines/{identifier}")
async def timeline_update(
    identifier: Identifier, data: TimelineUpdate, actor: AdminUser, service: Service
) -> object:
    """Update a timeline's dates and identity."""
    return await service.calendar_save(actor, data, event=False, identifier=identifier)


@router.delete("/admin/timelines/{identifier}", status_code=204)
async def timeline_delete(
    identifier: Identifier, data: Versioned, actor: AdminUser, service: Service
) -> Response:
    """Delete a bar while retaining events shared with surviving bars."""
    await service.calendar_delete(actor, identifier, data.expected_version, event=False)
    return Response(status_code=204)


@router.post("/admin/timeline-events", status_code=201)
async def event_create(data: EventFields, actor: AdminUser, service: Service) -> object:
    """Create an event shared by the selected bars."""
    return await service.calendar_save(actor, data, event=True)


@router.put("/admin/timeline-events/{identifier}")
async def event_update(
    identifier: Identifier, data: EventUpdate, actor: AdminUser, service: Service
) -> object:
    """Update an event and all its bar associations atomically."""
    return await service.calendar_save(actor, data, event=True, identifier=identifier)


@router.delete("/admin/timeline-events/{identifier}", status_code=204)
async def event_delete(
    identifier: Identifier, data: Versioned, actor: AdminUser, service: Service
) -> Response:
    """Delete one event from every associated timeline."""
    await service.calendar_delete(actor, identifier, data.expected_version, event=True)
    return Response(status_code=204)
