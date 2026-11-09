"""Private kholloscope preparation, generation, assignment and revision endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency, RequirePermission
from app.schemas.kholle import KholleSave, KholleWishesSave, KholloscopeValidate
from app.schemas.kholloscope_generation import (
    ApplyDraft,
    AssignGroups,
    CancelGeneration,
    DraftMove,
    DraftVersion,
    GenerationStart,
    RemoveKholloscope,
)
from app.schemas.kholloscope_revision import (
    RevisionCalculate,
    RevisionCreate,
    RevisionMerge,
    RevisionRollback,
    RevisionRoomChange,
)
from app.services.auth import UserContext
from app.services.kholle import KholleService
from app.services.kholle_wishes import KholleWishesService
from app.services.kholloscope_generation import KholloscopeGenerationService
from app.services.kholloscope_revision import KholloscopeRevisionService
from app.services.kholloscope_workflow import KholloscopeWorkflowService

router = APIRouter(
    prefix="/timetable",
    tags=["Kholloscope"],
    dependencies=[Depends(RequirePermission("kholloscope.read"))],
)
KholloscopeWriter = Annotated[UserContext, Depends(RequirePermission("kholloscope.write"))]


@router.get("/kholloscope/{school_year}/revision")
async def revision_state(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read the private subject branch and its published baseline."""
    return await KholloscopeRevisionService(auth).read(actor, school_year)


@router.post("/kholloscope/{school_year}/revision")
async def create_revision(
    school_year: int, data: RevisionCreate, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Fork current published agendas with a future Monday boundary."""
    return await KholloscopeRevisionService(auth).create(actor, school_year, data)


@router.post("/kholloscope/{school_year}/revision/calculate")
async def calculate_revision(
    school_year: int,
    data: RevisionCalculate,
    actor: KholloscopeWriter,
    auth: AuthServiceDependency,
) -> dict:
    """Save private future wishes and enqueue a bounded repair."""
    return await KholloscopeRevisionService(auth).calculate(actor, school_year, data)


@router.post("/kholloscope/{school_year}/revision/merge")
async def merge_revision(
    school_year: int, data: RevisionMerge, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Publish only reviewed future differences after independent validation."""
    return await KholloscopeRevisionService(auth).merge(actor, school_year, data)


@router.post("/kholloscope/{school_year}/revision/discard")
async def discard_revision(
    school_year: int, data: DraftVersion, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Abandon private changes without removing any live session."""
    return await KholloscopeRevisionService(auth).discard(actor, school_year, data)


@router.post("/kholloscope/{school_year}/revision/rollback")
async def rollback_revision(
    school_year: int, data: RevisionRollback, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Cancel an unchanged future publication while retaining its audit trail."""
    return await KholloscopeRevisionService(auth).rollback(actor, school_year, data)


@router.post("/kholloscope/{school_year}/revision/room")
async def change_revision_room(
    school_year: int,
    data: RevisionRoomChange,
    actor: KholloscopeWriter,
    auth: AuthServiceDependency,
) -> dict:
    """Review then publish a room-only replacement after checking actual occupancy."""
    return await KholloscopeRevisionService(auth).change_room(actor, school_year, data)


@router.get("/kholloscope/{school_year}/generation")
async def generation_state(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read private progress and the latest annual proposal; recheck administrator access."""
    return await KholloscopeGenerationService(auth).view(actor, school_year)


@router.post("/kholloscope/{school_year}/generation")
async def start_generation(
    school_year: int, data: GenerationStart, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Enqueue a bounded calculation against fresh source revisions."""
    return await KholloscopeGenerationService(auth).start(actor, school_year, data)


@router.post("/kholloscope/{school_year}/generation/cancel")
async def cancel_generation(
    school_year: int, actor: KholloscopeWriter, auth: AuthServiceDependency, data: CancelGeneration
) -> dict:
    """Request cancellation without deleting any earlier calculation."""
    return await KholloscopeGenerationService(auth).cancel(actor, school_year, data.run_id)


@router.put("/kholloscope/{school_year}/generation/session")
async def move_generated_session(
    school_year: int, data: DraftMove, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Validate and lock an annual draft correction without writing a live event."""
    return await KholloscopeGenerationService(auth).move(actor, school_year, data)


@router.post("/kholloscope/{school_year}/generation/save")
async def save_generated_calendar(
    school_year: int, data: DraftVersion, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Confirm a current completed proposal before unlocking group assignment."""
    return await KholloscopeGenerationService(auth).save(actor, school_year, data)


@router.get("/kholloscope/{school_year}/groups")
async def generation_groups(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read actual group choices only after a complete anonymous proposal exists."""
    return await KholloscopeGenerationService(auth).group_choices(actor, school_year)


@router.get("/kholloscope/{school_year}/pdf")
async def export_kholloscope(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> Response:
    """Download the private assigned colloscope without trusting browser-supplied labels."""
    content = await KholloscopeGenerationService(auth).pdf(actor, school_year)
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="kholloscope-{school_year}.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex, nofollow",
        },
    )


@router.put("/kholloscope/{school_year}/groups")
async def assign_generated_groups(
    school_year: int, data: AssignGroups, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Persist a bijection between abstract positions and real promotion groups."""
    return await KholloscopeGenerationService(auth).assign(actor, school_year, data)


@router.post("/kholloscope/{school_year}/generation/apply")
async def apply_generated_calendar(
    school_year: int, data: ApplyDraft, actor: KholloscopeWriter, auth: AuthServiceDependency
) -> dict:
    """Atomically apply an explicitly confirmed and fully assigned annual calendar."""
    return await KholloscopeGenerationService(auth).apply(actor, school_year, data)


@router.post("/kholloscope/{school_year}/generation/remove")
async def remove_generated_calendar(
    school_year: int,
    data: RemoveKholloscope,
    actor: KholloscopeWriter,
    auth: AuthServiceDependency,
) -> dict:
    """Remove all or strictly future live kholles after an explicit administrator confirmation."""
    return await KholloscopeGenerationService(auth).remove(actor, school_year, data)


@router.get("/kholloscope")
async def kholloscope(
    actor: AuthenticatedUser,
    auth: AuthServiceDependency,
    school_year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
) -> dict:
    """Read administrator-only annual prerequisites or complete kholle statistics."""
    return await KholleService(auth).overview(actor, school_year)


@router.post("/calendars/{identifier}/kholle/preview")
async def kholle_configuration(
    identifier: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read administrator-only kholle settings through the private command relay."""
    return await KholleService(auth).read(actor, identifier)


@router.get("/kholloscope/{school_year}/wishes")
async def kholle_wishes(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read exact annual subject commitments as an administrator."""
    return await KholleWishesService(auth).read(actor, school_year)


@router.get("/kholloscope/{school_year}/workflow")
async def kholloscope_workflow(
    school_year: int, actor: AuthenticatedUser, auth: AuthServiceDependency
) -> dict:
    """Read annual preparation milestones and authorized rooms as an administrator."""
    return await KholloscopeWorkflowService(auth).read(actor, school_year)


@router.put("/kholloscope/{school_year}/workflow")
async def validate_kholloscope_step(
    school_year: int,
    actor: KholloscopeWriter,
    auth: AuthServiceDependency,
    data: KholloscopeValidate,
) -> dict:
    """Validate and save the next milestone without scheduling any appointments."""
    return await KholloscopeWorkflowService(auth).validate(actor, school_year, data)


@router.put("/kholloscope/{school_year}/wishes")
async def save_kholle_wishes(
    school_year: int, actor: KholloscopeWriter, auth: AuthServiceDependency, data: KholleWishesSave
) -> dict:
    """Save the complete annual roster atomically without changing any sessions."""
    return await KholleWishesService(auth).save(actor, school_year, data)


@router.put("/calendars/{identifier}/kholle")
async def save_kholle_configuration(
    identifier: int, actor: KholloscopeWriter, auth: AuthServiceDependency, data: KholleSave
) -> dict:
    """Save exact group requirements without scheduling sessions."""
    return await KholleService(auth).save(actor, identifier, data)
