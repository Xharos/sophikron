"""Private timetable APIs and read-only, capability-authorized ICS retrieval."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.teacher_availability import AvailabilitySave
from app.schemas.timetable import (
    CalendarSave,
    CommonSettingsSave,
    OccurrenceEdit,
    RoomSave,
    SeriesSave,
    SettingsSave,
    TemplateSave,
    Version,
    YearCreate,
)
from app.services.errors import AuthError
from app.services.teacher_availability import TeacherAvailabilityService
from app.services.timetable import TimetableService
from app.services.timetable_configuration import TimetableConfigurationService
from app.services.timetable_templates import TimetableTemplateService

router = APIRouter(prefix="/timetable", tags=["Timetables"])


def timetable_service(auth: AuthServiceDependency) -> TimetableService:
    """Build a request-scoped business service with the existing authentication resources."""
    return TimetableService(auth)


Service = Annotated[TimetableService, Depends(timetable_service)]


@router.get("/staff/catalog")
async def staff_catalog(actor: AuthenticatedUser, auth: AuthServiceDependency) -> dict:
    """Read the permanent teaching workspace metadata as staff or administrator."""
    return await TeacherAvailabilityService(auth).catalog(actor)


@router.get("/staff/board")
async def staff_board(
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    school_year: Annotated[int, Query(ge=1900, le=9998)],
    teacher_ids: Annotated[str, Query(pattern=r"^[0-9,]{1,1000}$")],
    include_occupancy: bool = False,
) -> dict:
    """Read selected teachers' availability and their assigned sessions only."""
    identifiers = sorted({int(item) for item in teacher_ids.split(",") if item})
    if not identifiers or len(identifiers) > 100 or any(item < 1 for item in identifiers):
        raise AuthError(422, "Sélectionnez entre un et cent enseignants.")
    return await TeacherAvailabilityService(auth).board(
        actor, school_year, identifiers, include_occupancy=include_occupancy
    )


@router.put("/staff/{school_year}/{teacher_id}/availability")
async def save_availability(
    school_year: int,
    teacher_id: int,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    data: AvailabilitySave,
) -> dict:
    """Save an annual weekly pattern; backend authorization independently requires admin access."""
    return await TeacherAvailabilityService(auth).save(actor, school_year, teacher_id, data)


@router.get("/configuration")
async def configuration(actor: AuthenticatedUser, auth: AuthServiceDependency) -> dict:
    """Read establishment rooms and shared annual settings as an administrator."""
    return await TimetableConfigurationService(auth).read(actor)


@router.put("/configuration")
async def save_configuration(
    actor: AuthenticatedUser, auth: AuthServiceDependency, data: CommonSettingsSave
) -> dict:
    """Replace one common annual configuration without changing any published snapshot."""
    return await TimetableConfigurationService(auth).save(actor, data)


@router.put("/rooms/{identifier}")
async def save_room(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: RoomSave
) -> dict:
    """Rename a room using its observed revision."""
    return await TimetableConfigurationService(auth).room(actor, identifier, data)


@router.delete("/rooms/{identifier}")
async def delete_room(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: Version
) -> dict:
    """Retire a room from future selection while preserving historical references."""
    return await TimetableConfigurationService(auth).room(
        actor, identifier, None, data.expected_revision
    )


@router.delete("/calendars/{identifier}")
async def delete_calendar(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: Version
) -> dict:
    """Remove an agenda from active listings and personal exports after confirmation."""
    return await TimetableConfigurationService(auth).delete_calendar(
        actor, identifier, data.expected_revision
    )


@router.get("/years/{identifier}/template")
async def read_template(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read the latest weekly organization and effective version history."""
    return await TimetableTemplateService(auth).read(actor, identifier)


@router.put("/years/{identifier}/template")
async def save_template(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: TemplateSave
) -> dict:
    """Append an effective weekly copy, preserving history and dated exceptions."""
    return await TimetableTemplateService(auth).save(actor, identifier, data)


@router.get("/catalog")
async def catalog(actor: AuthenticatedUser, service: Service) -> dict:
    """List agendas and minimal options inside current administrator or teaching scope."""
    return await service.catalog(actor)


@router.get("/board")
async def board(
    actor: AuthenticatedUser,
    service: Service,
    calendar_ids: Annotated[str, Query(pattern=r"^[0-9,]{1,200}$")],
    school_year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
    draft: bool = False,
) -> dict:
    """Return selected agendas; students are denied even through direct API requests."""
    ids = list({int(item) for item in calendar_ids.split(",") if item})
    if not ids or len(ids) > 20:
        raise AuthError(422, "Sélectionnez entre un et vingt agendas.")
    return await service.board(actor, ids, school_year, draft)


@router.post("/calendars", status_code=201)
async def create_calendar(actor: AuthenticatedUser, service: Service, data: CalendarSave) -> dict:
    """Create an administrator-owned reusable agenda."""
    return await service.save_calendar(actor, data, None)


@router.put("/calendars/{identifier}")
async def save_calendar(
    identifier: int, actor: AuthenticatedUser, service: Service, data: CalendarSave
) -> dict:
    """Rename or manually reassign an agenda using its observed revision."""
    return await service.save_calendar(actor, data, identifier)


@router.post("/rooms", status_code=201)
async def create_room(actor: AuthenticatedUser, service: Service, data: RoomSave) -> dict:
    """Create or reuse a canonical room for timetable blocks."""
    return await service.add_room(actor, data.name)


@router.post("/calendars/{identifier}/years", status_code=201)
async def create_year(
    identifier: int, actor: AuthenticatedUser, service: Service, data: YearCreate
) -> dict:
    """Prepare an annual draft, optionally copying the previous recurring organization."""
    return await service.create_year(actor, identifier, data)


@router.put("/years/{identifier}/settings")
async def settings(
    identifier: int, actor: AuthenticatedUser, service: Service, data: SettingsSave
) -> dict:
    """Replace draft dates, daily hours, pauses, holidays and Saturday opening."""
    return await service.save_settings(actor, identifier, data, data.settings)


@router.post("/years/{identifier}/series", status_code=201)
async def create_series(
    identifier: int, actor: AuthenticatedUser, service: Service, data: SeriesSave
) -> dict:
    """Create an audience-scoped block, optionally repeating every one, two or three weeks."""
    return await service.add_series(actor, identifier, data, data.block)


@router.put("/years/{identifier}/series/{series_id}")
async def edit_occurrence(
    identifier: int,
    series_id: str,
    actor: AuthenticatedUser,
    service: Service,
    data: OccurrenceEdit,
) -> dict:
    """Change or cancel this occurrence alone, or this and all future occurrences."""
    return await service.edit_occurrence(actor, identifier, series_id, data)


@router.post("/years/{identifier}/publish")
async def publish(
    identifier: int, actor: AuthenticatedUser, service: Service, data: Version
) -> dict:
    """Publish an atomic snapshot; subsequent draft edits keep serving this version."""
    return await service.publish(actor, identifier, data)


@router.get("/subscription")
async def subscription_status(actor: AuthenticatedUser, service: Service) -> dict:
    """Return whether a subscription exists, never its original token."""
    return await service.subscription(actor)


@router.post("/subscription")
async def generate_subscription(actor: AuthenticatedUser, service: Service) -> dict:
    """Generate one personal token and atomically invalidate its predecessor."""
    return await service.subscription(actor, generate=True)


@router.get("/feed/{token}.ics", include_in_schema=False)
async def feed(token: str, service: Service) -> Response:
    """Serve current published events using a revocable token instead of browser cookies."""
    return Response(
        await service.feed(token),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
        },
    )
