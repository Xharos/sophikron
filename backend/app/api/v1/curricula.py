"""Authenticated programme catalogues, administration and subject-scoped graph routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import ValidationError

from app.dependencies.auth import AuthenticatedUser, AuthServiceDependency
from app.schemas.curricula import (
    CompetencyFields,
    CurriculumFields,
    CurriculumUpdate,
    Revision,
)
from app.services.curricula import CurriculaService
from app.services.curriculum_files import parse_import
from app.services.errors import AuthError

router = APIRouter(prefix="/curricula", tags=["Curricula"])
Identifier = Annotated[int, Path(gt=0)]


def get_service(auth: AuthServiceDependency) -> CurriculaService:
    """Construct the programme service using request-owned resources."""
    return CurriculaService(auth)


Service = Annotated[CurriculaService, Depends(get_service)]


@router.get("/catalog")
async def catalog(actor: AuthenticatedUser, service: Service) -> dict[str, object]:
    """List programme metadata without loading competency graphs."""
    return await service.catalog(actor)


@router.post("", status_code=201)
async def curriculum_create(
    data: CurriculumFields, actor: AuthenticatedUser, service: Service
) -> dict[str, object]:
    """Create a programme with multiple existing subjects."""
    return await service.curriculum_save(actor, data)


@router.put("/{curriculum_id}")
async def curriculum_update(
    curriculum_id: Identifier, data: CurriculumUpdate, actor: AuthenticatedUser, service: Service
) -> dict[str, object]:
    """Update administrator-owned programme metadata."""
    return await service.curriculum_save(actor, data, curriculum_id, data.expected_version)


@router.get("/{curriculum_id}/subjects/{subject_id}")
async def graph(
    curriculum_id: Identifier, subject_id: Identifier, actor: AuthenticatedUser, service: Service
) -> dict[str, object]:
    """Read one selected subject's competency graph."""
    return await service.graph(actor, curriculum_id, subject_id)


@router.post("/{curriculum_id}/undo")
async def undo(
    curriculum_id: Identifier, data: Revision, actor: AuthenticatedUser, service: Service
) -> dict[str, object]:
    """Undo this actor's latest edit without overwriting intervening changes."""
    return await service.undo(actor, curriculum_id, data.expected_version)


@router.get("/{curriculum_id}/subjects/{subject_id}/export")
async def export_file(
    curriculum_id: Identifier, subject_id: Identifier, actor: AuthenticatedUser, service: Service
) -> dict:
    """Return the versioned portable subject graph to authorized readers."""
    try:
        return await service.export_file(actor, curriculum_id, subject_id)
    except ValidationError:
        raise AuthError(
            422, "Ce graphe dépasse les limites du format d’échange (128 niveaux, 20 000 liens)."
        ) from None


@router.post("/{curriculum_id}/subjects/{subject_id}/import")
async def import_file(
    curriculum_id: Identifier,
    subject_id: Identifier,
    request: Request,
    actor: AuthenticatedUser,
    service: Service,
) -> dict:
    """Validate strict bounded JSON before invoking the subject-authorized transaction."""
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise AuthError(415, "Un fichier JSON est requis.")
    return await service.import_file(
        actor, curriculum_id, subject_id, parse_import(await request.body())
    )


@router.post("/{curriculum_id}/subjects/{subject_id}/nodes", status_code=201)
async def node_create(
    curriculum_id: Identifier,
    subject_id: Identifier,
    data: CompetencyFields,
    actor: AuthenticatedUser,
    service: Service,
) -> dict[str, object]:
    """Add a competency with zero or more parents."""
    return await service.node_save(actor, curriculum_id, subject_id, data)


@router.put("/{curriculum_id}/subjects/{subject_id}/nodes/{node_id}")
async def node_update(
    curriculum_id: Identifier,
    subject_id: Identifier,
    node_id: Identifier,
    data: CompetencyFields,
    actor: AuthenticatedUser,
    service: Service,
) -> dict[str, object]:
    """Replace one shared competency and its parent links."""
    return await service.node_save(actor, curriculum_id, subject_id, data, node_id)


@router.delete("/{curriculum_id}/subjects/{subject_id}/nodes/{node_id}")
async def node_delete(
    curriculum_id: Identifier,
    subject_id: Identifier,
    node_id: Identifier,
    data: Revision,
    actor: AuthenticatedUser,
    service: Service,
) -> dict[str, object]:
    """Remove a node from every branch while retaining its children."""
    return await service.node_delete(
        actor, curriculum_id, subject_id, node_id, data.expected_version
    )
