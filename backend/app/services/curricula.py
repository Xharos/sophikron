"""Transactional programme administration and collaborative competency graph editing."""

from sqlalchemy import delete, or_, select, text
from sqlalchemy.exc import IntegrityError

from app.models.curricula import Competency, CompetencyLink, Curriculum, CurriculumSubject
from app.models.curriculum_undo import CurriculumUndo
from app.models.site import Subject, TeacherSubject
from app.repositories.curricula import CurriculaRepository
from app.schemas.curricula import (
    CompetencyFields,
    CompetencyFile,
    CompetencyImport,
    CurriculumFields,
)
from app.services.activity import record_event
from app.services.auth import AuthService, UserContext
from app.services.competency_codes import competency_codes
from app.services.errors import AuthError


def validate_parents(node_id: int, parent_ids: list[int], edges: list[tuple[int, int]]) -> None:
    """Reject new incoming edges that would make the graph cyclic.

    Parameters
    ----------
    node_id
        Competency whose incoming edges are replaced.
    parent_ids
        Proposed parents, already scoped to the same subject.
    edges
        Existing parent-child pairs.

    Returns
    -------
    None
        Raise a validation error if a parent is the node or one of its descendants.
    """
    children: dict[int, list[int]] = {}
    for parent, child in edges:
        children.setdefault(parent, []).append(child)
    descendants, pending = set(), [node_id]
    while pending:
        current = pending.pop()
        if current in descendants:
            continue
        descendants.add(current)
        pending.extend(children.get(current, []))
    if descendants.intersection(parent_ids):
        raise AuthError(422, "Ce rattachement créerait un cycle entre les compétences.")


def fields(row: Curriculum | Competency) -> dict[str, object]:
    """Serialize mapped programme fields without ORM internals."""
    return {
        column.key: getattr(row, column.key)
        for column in row.__table__.columns
        if column.key != "name_key"
    }


class CurriculaService:
    """Recheck live permissions and serialize edits against staff assignment changes."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse authentication resources and the request-owned transaction."""
        self.auth, self.db = auth, auth.db
        self.repo = CurriculaRepository(self.db)

    async def _access(self, actor: UserContext, *, write: bool = False) -> set[str]:
        """Revalidate the session and return fresh explicitly granted capabilities."""
        if write:
            await self.auth._lifecycle_lock()
        await self.auth._actor(actor, permission="curricula.read")
        return set(await self.auth.repo.permissions(actor.id))

    async def _event(
        self,
        actor: UserContext,
        resource: str,
        identifier: int,
        action: str = "referential_saved",
        node: Competency | None = None,
        changed: list[str] | None = None,
    ) -> None:
        """Journal human-readable identities and the exact type of successful change."""
        row = await self.repo.curriculum(identifier)
        subject = await self.db.get(Subject, node.subject_id) if node else None
        edges = await self.repo.edges(identifier, node.subject_id) if node else []
        await record_event(
            self.db,
            "curriculum.changed",
            actor.id,
            resource_type="curriculum",
            resource_id=identifier,
            data={
                "action": action,
                "curriculum_title": row.title,
                "subject_name": subject.name if subject else None,
                "competency_name": node.name if node else None,
                "changed_fields": changed or [],
                "parent_count": sum(child == node.id for _, child in edges) if node else 0,
                "child_count": sum(parent == node.id for parent, _ in edges) if node else 0,
            },
        )

    async def _remember(
        self,
        actor: UserContext,
        row: Curriculum,
        subject_id: int,
        node_id: int,
        before: dict | None,
        edges: list[tuple[int, int]],
    ) -> None:
        """Retain at most twenty inverse operations per actor and programme."""
        self.db.add(
            CurriculumUndo(
                actor_id=actor.id,
                curriculum_id=row.id,
                subject_id=subject_id,
                node_id=node_id,
                after_version=row.version,
                payload={
                    "before_version": row.version - 1,
                    "node": before,
                    "edges": [list(edge) for edge in edges if node_id in edge],
                },
            )
        )
        await self.db.flush()
        old = (
            select(CurriculumUndo.id)
            .where(CurriculumUndo.actor_id == actor.id, CurriculumUndo.curriculum_id == row.id)
            .order_by(CurriculumUndo.id.desc())
            .offset(20)
        )
        await self.db.execute(delete(CurriculumUndo).where(CurriculumUndo.id.in_(old)))

    async def catalog(self, actor: UserContext) -> dict[str, object]:
        """List metadata only; graph data is fetched for one selected subject."""
        async with self.db.begin():
            permissions = await self._access(actor)
            admin = "curricula.manage" in permissions
            subjects = list(await self.db.scalars(select(Subject).order_by(Subject.name_key)))
            assignments = set(
                await self.db.scalars(
                    select(TeacherSubject.subject_id).where(TeacherSubject.user_id == actor.id)
                )
            )
            curricula = list(await self.db.scalars(select(Curriculum).order_by(Curriculum.title)))
            links = (await self.db.execute(select(CurriculumSubject))).scalars().all()
            return {
                "can_manage": admin,
                "subjects": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "color": s.color,
                        "icon": s.icon,
                        "is_active": s.is_active,
                        "can_edit": admin
                        or (
                            "curricula.edit" in permissions and s.id in assignments and s.is_active
                        ),
                    }
                    for s in subjects
                ],
                "curricula": [
                    {
                        **fields(c),
                        "subject_ids": [s.subject_id for s in links if s.curriculum_id == c.id],
                    }
                    for c in curricula
                ],
            }

    async def curriculum_save(
        self,
        actor: UserContext,
        data: CurriculumFields,
        identifier: int | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        """Save admin-owned metadata; refuse removing subjects that still contain nodes."""
        async with self.db.begin():
            permissions = await self._access(actor, write=True)
            if "curricula.manage" not in permissions:
                raise AuthError(403, "Seul un administrateur peut gérer les référentiels.")
            row = await self.repo.curriculum(identifier, lock=True) if identifier else Curriculum()
            if row is None:
                raise AuthError(404, "Référentiel introuvable.")
            if identifier and row.version != version:
                raise AuthError(409, "Ce référentiel a changé. Actualisez la page.")
            available = set(
                await self.db.scalars(
                    select(Subject.id).where(Subject.id.in_(data.subject_ids), Subject.is_active)
                )
            )
            previous = (
                set(
                    await self.db.scalars(
                        select(CurriculumSubject.subject_id).where(
                            CurriculumSubject.curriculum_id == identifier
                        )
                    )
                )
                if identifier
                else set()
            )
            if not set(data.subject_ids) <= available | previous:
                raise AuthError(422, "Choisissez des matières existantes et actives.")
            removed = previous - set(data.subject_ids)
            if removed and await self.db.scalar(
                select(Competency.id)
                .where(Competency.curriculum_id == identifier, Competency.subject_id.in_(removed))
                .limit(1)
            ):
                raise AuthError(
                    409, "Une matière contenant des compétences ne peut pas être retirée."
                )
            row.title = data.title
            row.description = data.description.strip() or None if data.description else None
            row.source_url = str(data.source_url) if data.source_url else None
            row.is_active, row.version = data.is_active, row.version + 1 if identifier else 0
            self.db.add(row)
            await self.db.flush()
            if removed:
                await self.db.execute(
                    delete(CurriculumSubject).where(
                        CurriculumSubject.curriculum_id == row.id,
                        CurriculumSubject.subject_id.in_(removed),
                    )
                )
            self.db.add_all(
                CurriculumSubject(curriculum_id=row.id, subject_id=s)
                for s in set(data.subject_ids) - previous
            )
            await self.db.flush()
            await self._event(
                actor,
                "curriculum",
                row.id,
                "referential_archived"
                if not data.is_active
                else "referential_updated"
                if identifier
                else "referential_created",
                changed=sorted(data.model_fields_set - {"expected_version"}),
            )
            return {**fields(row), "subject_ids": data.subject_ids}

    async def _graph_access(
        self,
        actor: UserContext,
        curriculum_id: int,
        subject_id: int,
        *,
        write: bool = False,
        version: int | None = None,
    ) -> Curriculum:
        """Scope both graph endpoints and authorize live subject assignments."""
        permissions = await self._access(actor, write=write)
        row = await self.repo.curriculum(curriculum_id, lock=write)
        if row is None or await self.db.get(CurriculumSubject, (curriculum_id, subject_id)) is None:
            raise AuthError(404, "Référentiel ou matière introuvable.")
        if write:
            subject = await self.db.get(Subject, subject_id)
            admin = "curricula.manage" in permissions
            assigned = await self.db.get(TeacherSubject, (actor.id, subject_id))
            if not admin and ("curricula.edit" not in permissions or assigned is None):
                raise AuthError(403, "Vous ne pouvez modifier que vos matières.")
            if not row.is_active or not subject.is_active:
                raise AuthError(409, "Ce référentiel ou cette matière est archivé.")
            if row.version != version:
                raise AuthError(409, "Le référentiel a changé. Actualisez avant de réessayer.")
        return row

    async def _graph(self, row: Curriculum, subject_id: int) -> dict[str, object]:
        """Return a compact portable representation of one subject's graph."""
        nodes = await self.repo.nodes(row.id, subject_id)
        edges = await self.repo.edges(row.id, subject_id)
        codes, ordered = competency_codes(nodes, edges)
        by_id = {node.id: node for node in nodes}
        return {
            "curriculum_id": row.id,
            "subject_id": subject_id,
            "version": row.version,
            "nodes": [
                {**fields(by_id[identifier]), "code": codes[identifier]} for identifier in ordered
            ],
            "edges": [{"parent_id": p, "child_id": c} for p, c in edges],
        }

    async def graph(
        self, actor: UserContext, curriculum_id: int, subject_id: int
    ) -> dict[str, object]:
        """Read one graph for any authorized staff member."""
        async with self.db.begin():
            row = await self._graph_access(actor, curriculum_id, subject_id)
            return await self._graph(row, subject_id)

    async def export_file(self, actor: UserContext, curriculum_id: int, subject_id: int) -> dict:
        """Export the complete subject DAG, preserving shared identities and all content."""
        import json

        from app.services.curriculum_files import FILE_LIMIT

        async with self.db.begin():
            row = await self._graph_access(actor, curriculum_id, subject_id)
            graph = await self._graph(row, subject_id)
            subject = await self.db.get(Subject, subject_id)
            document = CompetencyFile.model_validate(
                {
                    "format": "sophikron.competencies",
                    "version": 1,
                    "subject_name": subject.name,
                    "nodes": [
                        {
                            **{
                                key: value
                                for key, value in node.items()
                                if key not in {"curriculum_id", "subject_id", "code"}
                            },
                            "parent_ids": [
                                edge["parent_id"]
                                for edge in graph["edges"]
                                if edge["child_id"] == node["id"]
                            ],
                        }
                        for node in graph["nodes"]
                    ],
                }
            ).model_dump(exclude={"nodes": {"__all__": {"expected_version"}}})
            if len(json.dumps(document, ensure_ascii=False).encode()) > FILE_LIMIT:
                raise AuthError(413, "Export supérieur à la limite de 4 Mo.")
            return document

    async def import_file(
        self, actor: UserContext, curriculum_id: int, subject_id: int, data: CompetencyImport
    ) -> dict:
        """Append an entire validated graph atomically using fresh database identities."""
        async with self.db.begin():
            row = await self._graph_access(
                actor, curriculum_id, subject_id, write=True, version=data.expected_version
            )
            existing = await self.repo.nodes(curriculum_id, subject_id)
            if len(existing) + len(data.document.nodes) > 2000:
                raise AuthError(422, "Limite de 2 000 compétences par matière atteinte.")
            if not data.document.nodes:
                raise AuthError(422, "Le fichier ne contient aucune compétence.")
            mapped: dict[int, Competency] = {}
            for item in data.document.nodes:
                node = Competency(
                    curriculum_id=curriculum_id,
                    subject_id=subject_id,
                    **item.model_dump(exclude={"id", "expected_version", "parent_ids"}),
                )
                self.db.add(node)
                mapped[item.id] = node
            await self.db.flush()
            self.db.add_all(
                CompetencyLink(
                    curriculum_id=curriculum_id,
                    subject_id=subject_id,
                    parent_id=mapped[parent].id,
                    child_id=mapped[item.id].id,
                )
                for item in data.document.nodes
                for parent in item.parent_ids
            )
            row.version += 1
            await self.db.flush()
            await self._remember(actor, row, subject_id, 0, None, [])
            history = await self.db.scalar(
                select(CurriculumUndo)
                .where(
                    CurriculumUndo.actor_id == actor.id,
                    CurriculumUndo.curriculum_id == curriculum_id,
                )
                .order_by(CurriculumUndo.id.desc())
                .limit(1)
            )
            history.payload = {
                **history.payload,
                "created_ids": [node.id for node in mapped.values()],
            }
            subject = await self.db.get(Subject, subject_id)
            await record_event(
                self.db,
                "curriculum.changed",
                actor.id,
                resource_type="curriculum",
                resource_id=curriculum_id,
                data={
                    "action": "competencies_imported",
                    "curriculum_title": row.title,
                    "subject_name": subject.name,
                    "imported_count": len(mapped),
                },
            )
            return {**await self._graph(row, subject_id), "can_undo": True}

    async def node_save(
        self,
        actor: UserContext,
        curriculum_id: int,
        subject_id: int,
        data: CompetencyFields,
        node_id: int | None = None,
    ) -> dict[str, object]:
        """Create or replace a competency and incoming edges with cycle prevention."""
        try:
            async with self.db.begin():
                row = await self._graph_access(
                    actor, curriculum_id, subject_id, write=True, version=data.expected_version
                )
                nodes = {n.id: n for n in await self.repo.nodes(curriculum_id, subject_id)}
                if node_id is not None and node_id not in nodes:
                    raise AuthError(404, "Compétence introuvable.")
                if not set(data.parent_ids) <= nodes.keys():
                    raise AuthError(
                        422, "Les parents doivent appartenir à cette matière du référentiel."
                    )
                if node_id is None and len(nodes) >= 2000:
                    raise AuthError(422, "Limite de 2 000 compétences par matière atteinte.")
                validate_parents(
                    node_id or -1, data.parent_ids, await self.repo.edges(curriculum_id, subject_id)
                )
                node = (
                    nodes[node_id]
                    if node_id
                    else Competency(curriculum_id=curriculum_id, subject_id=subject_id)
                )
                before = fields(node) if node_id else None
                previous_edges = await self.repo.edges(curriculum_id, subject_id)
                changed = [
                    key
                    for key, value in data.model_dump(
                        exclude={"expected_version", "parent_ids"}
                    ).items()
                    if before is None or before.get(key) != value
                ]
                if set(data.parent_ids) != {p for p, c in previous_edges if c == node.id}:
                    changed.append("parent_ids")
                for key, value in data.model_dump(
                    exclude={"expected_version", "parent_ids"}
                ).items():
                    setattr(node, key, value)
                self.db.add(node)
                await self.db.flush()
                await self.db.execute(
                    delete(CompetencyLink).where(CompetencyLink.child_id == node.id)
                )
                self.db.add_all(
                    CompetencyLink(
                        curriculum_id=curriculum_id,
                        subject_id=subject_id,
                        parent_id=p,
                        child_id=node.id,
                    )
                    for p in data.parent_ids
                )
                row.version += 1
                await self.db.flush()
                await self._remember(actor, row, subject_id, node.id, before, previous_edges)
                await self._event(
                    actor,
                    "curriculum",
                    row.id,
                    "competency_updated" if node_id else "competency_created",
                    node,
                    changed,
                )
                return {**await self._graph(row, subject_id), "can_undo": True}
        except IntegrityError:
            raise AuthError(409, "Le référentiel a changé. Actualisez la page.") from None

    async def node_delete(
        self, actor: UserContext, curriculum_id: int, subject_id: int, node_id: int, version: int
    ) -> dict[str, object]:
        """Delete only the selected node; cascading edges leave all children intact."""
        async with self.db.begin():
            row = await self._graph_access(
                actor, curriculum_id, subject_id, write=True, version=version
            )
            nodes = {n.id: n for n in await self.repo.nodes(curriculum_id, subject_id)}
            if node_id not in nodes:
                raise AuthError(404, "Compétence introuvable.")
            before = fields(nodes[node_id])
            previous_edges = await self.repo.edges(curriculum_id, subject_id)
            await self._event(actor, "curriculum", row.id, "competency_deleted", nodes[node_id])
            await self.db.delete(nodes[node_id])
            row.version += 1
            await self.db.flush()
            await self._remember(actor, row, subject_id, node_id, before, previous_edges)
            return {**await self._graph(row, subject_id), "can_undo": True}

    async def undo(self, actor: UserContext, curriculum_id: int, version: int) -> dict[str, object]:
        """Apply only a revision-matching inverse after rechecking subject authorization."""
        async with self.db.begin():
            await self._access(actor, write=True)
            entry = await self.db.scalar(
                select(CurriculumUndo)
                .where(
                    CurriculumUndo.actor_id == actor.id,
                    CurriculumUndo.curriculum_id == curriculum_id,
                )
                .order_by(CurriculumUndo.id.desc())
                .limit(1)
            )
            if entry is None:
                raise AuthError(409, "Aucune action à annuler.")
            row = await self._graph_access(
                actor, curriculum_id, entry.subject_id, write=True, version=version
            )
            if entry.after_version != row.version:
                raise AuthError(
                    409, "Le programme a changé depuis cette action. Annulation refusée."
                )
            before = entry.payload["node"]
            node = await self.db.get(Competency, entry.node_id)
            await self.db.execute(
                delete(CompetencyLink).where(
                    or_(
                        CompetencyLink.parent_id == entry.node_id,
                        CompetencyLink.child_id == entry.node_id,
                    )
                )
            )
            if before is None:
                if entry.payload.get("created_ids"):
                    await self.db.execute(
                        delete(Competency).where(
                            Competency.curriculum_id == curriculum_id,
                            Competency.subject_id == entry.subject_id,
                            Competency.id.in_(entry.payload["created_ids"]),
                        )
                    )
                if node:
                    await self.db.delete(node)
            else:
                if node is None:
                    columns = list(before)
                    statement = (
                        "INSERT INTO sophikron.competencies ("
                        + ", ".join(columns)
                        + ") OVERRIDING SYSTEM VALUE VALUES ("
                        + ", ".join(":" + key for key in columns)
                        + ")"
                    )
                    await self.db.execute(text(statement), before)
                else:
                    for key, value in before.items():
                        setattr(node, key, value)
                await self.db.flush()
                self.db.add_all(
                    CompetencyLink(
                        curriculum_id=curriculum_id,
                        subject_id=entry.subject_id,
                        parent_id=p,
                        child_id=c,
                    )
                    for p, c in entry.payload["edges"]
                )
            row.version += 1
            await self.db.delete(entry)
            await self.db.flush()
            previous = await self.db.scalar(
                select(CurriculumUndo)
                .where(
                    CurriculumUndo.actor_id == actor.id,
                    CurriculumUndo.curriculum_id == curriculum_id,
                )
                .order_by(CurriculumUndo.id.desc())
                .limit(1)
            )
            available = (
                previous is not None and previous.after_version == entry.payload["before_version"]
            )
            if available:
                previous.after_version = row.version
            await self._event(
                actor,
                "curriculum",
                row.id,
                "action_undone",
                node if node is not None else Competency(**before) if before else None,
            )
            return {**await self._graph(row, entry.subject_id), "can_undo": available}
