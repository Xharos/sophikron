"""Private timetable APIs and read-only, capability-authorized ICS retrieval."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.auth import InputModel
from app.schemas.teacher_availability import AvailabilitySave
from app.schemas.timetable import (
    CalendarRestore,
    CalendarSave,
    EventPreview,
    OccurrenceEdit,
    PreferencesSave,
    RoomSave,
    SchoolYearCreate,
    SeriesSave,
    SettingsSave,
    Version,
)
from app.services.calendar_subscriptions import Action, CalendarSubscriptionService, Category
from app.services.errors import AuthError
from app.services.teacher_availability import TeacherAvailabilityService
from app.services.timetable import TimetableService
from app.services.timetable_configuration import TimetableConfigurationService
from app.services.timetable_export import TimetableExportService


class SubscriptionCommand(InputModel):
    """Allow only administrator revocation or regeneration commands."""

    action: Action


class SubscriptionBulkCommand(SubscriptionCommand):
    """Select a supported member category without accepting arbitrary role names."""

    category: Category


router = APIRouter(prefix="/timetable", tags=["Timetables"])


def timetable_service(auth: AuthServiceDependency) -> TimetableService:
    """Build a request-scoped business service with the existing authentication resources."""
    return TimetableService(auth)


Service = Annotated[TimetableService, Depends(timetable_service)]


@router.get("/calendars/{identifier}/pdf", response_class=Response)
async def export_pdf(
    identifier: int,
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    year_id: Annotated[int, Query(gt=0)],
    day: date,
    node: Annotated[
        str,
        Query(
            pattern=r"^(promotion|unassigned|(halves|thirds|kholles|custom|student)-[1-9][0-9]{0,15})$"
        ),
    ] = "promotion",
) -> Response:
    """Export the selected authorized week and audience without khôlle sessions or exact dates."""
    document = await TimetableExportService(auth).generate(actor, identifier, year_id, day, node)
    return Response(
        document,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="emploi-du-temps-{identifier}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


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
    """Read establishment rooms and immutable school-year labels as an administrator."""
    return await TimetableConfigurationService(auth).read(actor)


@router.post("/school-years", status_code=201)
async def create_school_year(
    actor: AuthenticatedUser, auth: AuthServiceDependency, data: SchoolYearCreate
) -> dict:
    """Create an immutable academic label with administrator authorization."""
    return await TimetableConfigurationService(auth).create_school_year(actor, data)


@router.put("/preferences")
async def preferences(
    actor: AuthenticatedUser, auth: AuthServiceDependency, data: PreferencesSave
) -> dict:
    """Update the administrator-only annual archive policy."""
    return await TimetableConfigurationService(auth).preferences(actor, data)


@router.delete("/school-years/{school_year}")
async def delete_school_year(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: Version
) -> dict:
    """Remove a label only if it has never been used."""
    return await TimetableConfigurationService(auth).delete_school_year(actor, school_year, data)


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


@router.post("/calendars/{identifier}/archive")
async def archive_calendar(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: Version
) -> dict:
    """Archive without deleting any calendar or occurrence."""
    return await TimetableConfigurationService(auth).archive(actor, identifier, data)


@router.post("/calendars/{identifier}/restore")
async def restore_calendar(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency, data: CalendarRestore
) -> dict:
    """Restore an archive without implicitly enabling its diffusion."""
    return await TimetableConfigurationService(auth).restore(actor, identifier, data)


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
) -> dict:
    """Return selected agendas; students are denied even through direct API requests."""
    ids = list({int(item) for item in calendar_ids.split(",") if item})
    if not ids or len(ids) > 20:
        raise AuthError(422, "Sélectionnez entre un et vingt agendas.")
    return await service.board(actor, ids, school_year)


@router.post("/calendars", status_code=201)
async def create_calendar(actor: AuthenticatedUser, service: Service, data: CalendarSave) -> dict:
    """Create an administrator-owned annual calendar."""
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


@router.put("/years/{identifier}/settings")
async def settings(
    identifier: int, actor: AuthenticatedUser, service: Service, data: SettingsSave
) -> dict:
    """Change dates, holidays and Saturday opening; other daily rules are immutable."""
    return await service.save_settings(actor, identifier, data, data.settings)


@router.post("/years/{identifier}/settings/preview")
async def preview_settings(
    identifier: int, actor: AuthenticatedUser, service: Service, data: SettingsSave
) -> dict:
    """Preview settings effects without changing the live calendar."""
    return await service.preview_settings(actor, identifier, data, data.settings)


@router.post("/years/{identifier}/preview")
async def preview_event(
    identifier: int, actor: AuthenticatedUser, service: Service, data: EventPreview
) -> dict:
    """Return actual potential annual hours and diagnostics without saving the proposed event."""
    return await service.board(actor, [], None, preview_year=identifier, proposal=data)


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


@router.get("/subscription")
async def subscription_status(actor: AuthenticatedUser, auth: AuthServiceDependency) -> dict:
    """Return the authenticated owner's encrypted-at-rest personal credential only."""
    return await CalendarSubscriptionService(auth).personal(actor)


@router.get("/subscriptions/users/{user_id}")
async def member_subscription(
    user_id: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read administrator-only status without exposing the target's secret."""
    return await CalendarSubscriptionService(auth).manage(actor, user_id)


@router.post("/subscriptions/users/{user_id}")
async def change_member_subscription(
    user_id: int, data: SubscriptionCommand, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Revoke or regenerate a member's credential without returning its value."""
    return await CalendarSubscriptionService(auth).manage(actor, user_id, data.action)


@router.post("/subscriptions/bulk")
async def change_category_subscriptions(
    data: SubscriptionBulkCommand, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Change all eligible category members atomically with backend administrator checks."""
    return await CalendarSubscriptionService(auth).bulk(actor, data.category, data.action)


@router.get("/feed/{token}.ics", include_in_schema=False)
async def feed(token: str, service: Service, request: Request) -> Response:
    """Serve currently broadcast events using a revocable token instead of browser cookies."""
    return Response(
        await service.feed(token, outcome=request.scope),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
        },
    )
