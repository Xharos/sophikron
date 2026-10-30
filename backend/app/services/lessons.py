"""Transactional course editing and server-side filtering of student-visible content."""

from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.models import Promotion, Role, User, UserRole
from app.models.lessons import (
    Lesson,
    LessonCollaborator,
    LessonElement,
    LessonFile,
    LessonPromotion,
)
from app.models.site import Subject, TeacherSubject
from app.repositories.lessons import LessonRepository
from app.schemas.administration import PromotionBadge
from app.schemas.lessons import (
    ElementCreate,
    ElementFields,
    ElementMove,
    ElementResponse,
    ElementUpdate,
    FileResponse,
    LessonAccess,
    LessonCard,
    LessonDetail,
    LessonFields,
    LessonPerson,
    LessonUpdate,
    PromotionGrant,
    ResponsibilityUpdate,
    TableChange,
    normalized_title,
    youtube_id,
)
from app.services.activity import highest_role, record_event
from app.services.auth import AuthService, UserContext
from app.services.course_rights import has_subject
from app.services.errors import AuthError

SCHOOL_YEAR_END_MONTH = 8
SCHOOL_YEAR_END_DAY = 31
PARIS = ZoneInfo("Europe/Paris")
MAX_ELEMENTS = 500


def school_year_period(year: int) -> tuple[date, date]:
    """Return inclusive school-year dates, with August 31 fixed as the access deadline."""
    if not 1 <= year <= 9998:
        raise AuthError(422, "L’année de la promotion ne permet pas de calculer la fin d’année.")
    return date(year, 9, 1), date(year + 1, SCHOOL_YEAR_END_MONTH, SCHOOL_YEAR_END_DAY)


def effective_period(
    element: LessonElement,
    inherited: tuple[date | None, date | None, str | None],
) -> tuple[date | None, date | None, str | None]:
    """Apply dates only to a document or video, independently of structural ancestors."""
    if element.kind not in {"file", "youtube"} or element.schedule_mode == "inherit":
        return None, None, None
    return element.starts_on, element.ends_on, element.title or "Élément parent"


class LessonService:
    """Never infer edit rights from historical authorship without checking current grants."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse request-owned authentication, encryption and database resources."""
        self.auth, self.db = auth, auth.db
        self.repo = LessonRepository(self.db)

    def today(self) -> date:
        """Evaluate inclusive date rules consistently at the Paris calendar boundary."""
        return self.auth.clock().astimezone(PARIS).date()

    async def _principal(self, actor: UserContext) -> tuple[bool, bool]:
        """Revalidate the live session, status and grants inside the business transaction."""
        user = await self.auth._actor(actor)
        if user.is_bootstrap:
            raise AuthError(403, "Accès réservé aux comptes permanents.")
        _, permissions = await self.auth.repo.grants(actor.id)
        return "teacher.access" in permissions, "users.manage" in permissions

    async def _lesson(self, lesson_id: int, *, lock: bool = False) -> Lesson:
        """Require an existing page before reading its tree or changing its settings."""
        lesson = await self.repo.lesson(lesson_id, lock=lock)
        if lesson is None:
            raise AuthError(404, "Cours introuvable.")
        return lesson

    async def _edit_rights(
        self,
        actor: UserContext,
        lesson: Lesson,
        teacher: bool,
        admin: bool,
    ) -> tuple[bool, bool]:
        """Require current teaching and subject eligibility for responsibility or collaboration."""
        eligible = teacher and await has_subject(self.db, actor.id, lesson.subject_id)
        responsible = eligible and lesson.responsible_id == actor.id
        edit = (
            admin or responsible or (eligible and await self.repo.collaborator(lesson.id, actor.id))
        )
        return edit, admin or responsible

    async def _write(
        self,
        actor: UserContext,
        lesson_id: int,
        expected_version: int,
        *,
        collaborators: bool = False,
    ) -> Lesson:
        """Serialize against role/status changes and reject unauthorized or stale writes."""
        await self.auth._lifecycle_lock()
        teacher, admin = await self._principal(actor)
        lesson = await self._lesson(lesson_id, lock=True)
        edit, manage = await self._edit_rights(actor, lesson, teacher, admin)
        if not edit or (collaborators and not manage):
            raise AuthError(403, "Vous n’avez plus le droit de modifier ce cours.")
        if lesson.version != expected_version:
            raise AuthError(409, "Ce cours a été modifié. Rechargez la page avant de réessayer.")
        return lesson

    async def _person(self, user_id: int, subject_id: int | None = None) -> LessonPerson:
        """Decrypt only staff names; historical ownership never reveals private profiles."""
        user = await self.db.get(User, user_id)
        if user is None:
            return LessonPerson(id=user_id, label="Compte non disponible")
        cipher = self.auth.cipher
        names = [
            cipher.decrypt(user.id, field, getattr(user, f"{field}_encrypted"))
            for field in ("first_name", "last_name")
        ]
        roles, permissions = await self.auth.repo.grants(user.id)
        return LessonPerson(
            id=user.id,
            label=" ".join(name for name in names if name) or "Compte non disponible",
            role="teacher"
            if "teacher" in roles
            else "kholleur"
            if "kholleur" in roles
            else highest_role(roles),
            can_edit=user.status == "active"
            and "teacher.access" in permissions
            and (subject_id is None or await has_subject(self.db, user.id, subject_id)),
        )

    async def _card(
        self,
        actor: UserContext,
        lesson: Lesson,
        teacher: bool,
        admin: bool,
        accessible: set[int],
    ) -> LessonCard:
        """Build catalogue metadata without loading or leaking any course content."""
        edit, _ = await self._edit_rights(actor, lesson, teacher, admin)
        subject = await self.db.get(Subject, lesson.subject_id)
        permissions = await self.auth.repo.permissions(actor.id)
        reader = "kholleur.access" in permissions and await self.repo.collaborator(
            lesson.id, actor.id
        )
        collaborators = list(
            (
                await self.db.scalars(
                    select(LessonCollaborator.user_id)
                    .where(LessonCollaborator.lesson_id == lesson.id)
                    .order_by(LessonCollaborator.user_id)
                )
            ).all()
        )
        return LessonCard(
            id=lesson.id,
            title=lesson.title,
            description=lesson.description,
            subject_id=subject.id,
            subject_name=subject.name,
            icon=subject.icon,
            color=subject.color,
            creator=await self._person(lesson.creator_id),
            responsible=await self._person(lesson.responsible_id, lesson.subject_id),
            collaborators=[
                await self._person(identifier, lesson.subject_id) for identifier in collaborators
            ],
            can_open=teacher or admin or reader or lesson.id in accessible,
            can_edit=edit,
            version=lesson.version,
            updated_at=lesson.updated_at,
        )

    async def catalogue(
        self,
        actor: UserContext,
        *,
        offset: int,
        limit: int,
        q: str,
    ) -> dict[str, object]:
        """List every course card while computing page access from current promotion grants."""
        async with self.db.begin():
            teacher, admin = await self._principal(actor)
            query = select(Lesson)
            if q.strip():
                escaped = normalized_title(q).casefold().replace("\\", "\\\\")
                escaped = escaped.replace("%", "\\%").replace("_", "\\_")
                query = query.where(Lesson.title_key.like(f"%{escaped}%", escape="\\"))
            total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
            lessons = (
                await self.db.scalars(
                    query.order_by(Lesson.title_key, Lesson.id).offset(offset).limit(limit)
                )
            ).all()
            accessible = set(
                (await self.db.scalars(self.repo.accessible(actor.id, self.today()))).all()
            )
            return {
                "items": [
                    await self._card(actor, item, teacher, admin, accessible) for item in lessons
                ],
                "total": total,
                "offset": offset,
                "limit": limit,
                "can_create": teacher
                and bool(
                    await self.db.scalar(
                        select(TeacherSubject.user_id)
                        .join(Subject)
                        .where(TeacherSubject.user_id == actor.id, Subject.is_active)
                        .limit(1)
                    )
                ),
            }

    async def _detail(self, actor: UserContext, lesson: Lesson) -> LessonDetail:
        """Exclude private subtrees and redact unavailable video bodies for student previews."""
        teacher, admin = await self._principal(actor)
        today = self.today()
        accessible = set((await self.db.scalars(self.repo.accessible(actor.id, today))).all())
        card = await self._card(actor, lesson, teacher, admin, accessible)
        permissions = await self.auth.repo.permissions(actor.id)
        staff_view = (
            teacher
            or admin
            or (
                "kholleur.access" in permissions
                and await self.repo.collaborator(lesson.id, actor.id)
            )
        )
        if not card.can_open:
            raise AuthError(403, "Votre promotion ne dispose pas d’un accès actif à ce cours.")
        _, manage = await self._edit_rights(actor, lesson, teacher, admin)
        elements = await self.repo.elements(lesson.id)
        files = {
            file.element_id: file
            for file in (
                await self.db.scalars(select(LessonFile).where(LessonFile.lesson_id == lesson.id))
            ).all()
        }
        children: dict[int | None, list[LessonElement]] = {}
        for element in elements:
            children.setdefault(element.parent_id, []).append(element)
        output: list[ElementResponse] = []
        warnings: list[str] = []

        by_id = {item.id: item for item in elements}
        private_roots = {
            self.section_root(item, by_id).id for item in elements if item.audience == "staff"
        }

        def visit(
            parent_id: int | None,
            inherited: tuple[date | None, date | None, str | None],
            staff_only: bool = False,
        ) -> None:
            """Apply section visibility and independent media schedules across the content tree."""
            for item in children.get(parent_id, []):
                restricted = staff_only or (item.kind == "section" and item.id in private_roots)
                if restricted and not staff_view:
                    continue
                start, end, source = (
                    (None, None, None) if restricted else effective_period(item, inherited)
                )
                status = (
                    "scheduled"
                    if start and today < start
                    else ("expired" if end and today > end else "available")
                )
                available = status == "available"
                output.append(
                    ElementResponse(
                        id=item.id,
                        parent_id=item.parent_id,
                        kind=item.kind,
                        position=item.position,
                        title=item.title,
                        body=item.body if available or staff_view else "",
                        schedule_mode=item.schedule_mode
                        if item.kind in {"file", "youtube"} and not restricted
                        else "inherit",
                        starts_on=start,
                        ends_on=end,
                        effective_starts_on=start,
                        effective_ends_on=end,
                        inherited_from=source if item.schedule_mode == "inherit" else None,
                        available=available,
                        status=status,
                        audience="staff" if item.kind == "section" and restricted else "students",
                        effective_audience="staff" if restricted else "students",
                        table_rows=item.table_rows,
                        table_columns=item.table_columns,
                        row_index=item.row_index,
                        column_index=item.column_index,
                        file=FileResponse.model_validate(files[item.id], from_attributes=True)
                        if item.id in files
                        else None,
                    )
                )
                if card.can_edit and status == "expired":
                    warnings.append(f"{item.title or 'Élément'} : période terminée.")
                visit(item.id, (start, end, source), restricted)

        visit(None, (None, None, None))
        grants: list[LessonAccess] = []
        if card.can_edit:
            for grant, promotion in await self.db.execute(
                select(LessonPromotion, Promotion)
                .join(Promotion, Promotion.id == LessonPromotion.promotion_id)
                .where(LessonPromotion.lesson_id == lesson.id)
                .order_by(Promotion.year.desc(), Promotion.identifier)
            ):
                grants.append(
                    LessonAccess(
                        promotion_id=promotion.id,
                        identifier=promotion.identifier,
                        year=promotion.year,
                        color=promotion.color,
                        is_active=promotion.is_active,
                        starts_on=grant.starts_on,
                        ends_on=grant.ends_on,
                    )
                )
            active = [grant for grant in grants if grant.is_active and grant.ends_on >= today]
            if not active:
                warnings.insert(0, "Aucune promotion ne dispose d’un accès actuel ou à venir.")
            for item in output:
                start, end = item.effective_starts_on, item.effective_ends_on
                if (
                    active
                    and (start or end)
                    and not any(
                        (start is None or grant.ends_on >= start)
                        and (end is None or grant.starts_on <= end)
                        for grant in active
                    )
                ):
                    warnings.append(
                        f"{item.title or 'Élément'} : aucune période de promotion compatible."
                    )
        return LessonDetail(
            **card.model_dump(),
            can_view_statistics=admin
            or (teacher and actor.id in {lesson.creator_id, lesson.responsible_id})
            or (
                (teacher or "kholleur.access" in await self.auth.repo.permissions(actor.id))
                and await self.repo.collaborator(lesson.id, actor.id)
            ),
            can_manage_collaborators=manage,
            can_transfer=admin,
            staff_view=staff_view,
            today=today,
            elements=output,
            promotions=grants,
            warnings=warnings[:30],
        )

    async def detail(self, actor: UserContext, lesson_id: int) -> LessonDetail:
        """Authorize direct page requests independently of catalogue visibility."""
        async with self.db.begin():
            return await self._detail(actor, await self._lesson(lesson_id))

    async def _event(
        self,
        actor: UserContext,
        lesson: Lesson,
        action: str,
        *,
        subject_id: int | None = None,
        **data: object,
    ) -> None:
        """Commit detailed, bounded audit facts with the same transaction as the edit."""
        await record_event(
            self.db,
            f"lesson.{action}",
            actor.id,
            subject_user_id=subject_id,
            resource_type="lesson",
            resource_id=lesson.id,
            data={"lesson_title": lesson.title, **data},
            occurred_at=self.auth.clock(),
        )

    async def _changed(self, lesson: Lesson) -> None:
        """Advance the page revision exactly once after a successful meaningful mutation."""
        lesson.version += 1
        lesson.updated_at = self.auth.clock()
        await self.db.flush()

    async def create(self, actor: UserContext, data: LessonFields) -> LessonDetail:
        """Create an immediately listed course, exclusively with a current teacher grant."""
        try:
            async with self.db.begin():
                await self.auth._lifecycle_lock()
                teacher, _ = await self._principal(actor)
                if not teacher:
                    raise AuthError(403, "Seul un enseignant peut créer un cours.")
                if not await has_subject(self.db, actor.id, data.subject_id):
                    raise AuthError(
                        403, "Cette matière ne vous est pas affectée. Contactez un administrateur."
                    )
                lesson = Lesson(
                    **data.model_dump(),
                    title_key=data.title.casefold(),
                    creator_id=actor.id,
                    responsible_id=actor.id,
                )
                self.db.add(lesson)
                await self.db.flush()
                await self._event(actor, lesson, "created")
                return await self._detail(actor, lesson)
        except IntegrityError:
            raise AuthError(409, "Ce titre de cours est déjà utilisé.") from None

    async def update(self, actor: UserContext, lesson_id: int, data: LessonUpdate) -> LessonDetail:
        """Update card metadata and journal changed field names without copying content."""
        try:
            async with self.db.begin():
                lesson = await self._write(actor, lesson_id, data.expected_version)
                if data.subject_id != lesson.subject_id:
                    raise AuthError(
                        403,
                        "La matière se modifie par un administrateur avec le responsable du cours.",
                    )
                changes = {
                    key: value
                    for key, value in data.model_dump(exclude={"expected_version"}).items()
                    if getattr(lesson, key) != value
                }
                if changes:
                    for key, value in changes.items():
                        setattr(lesson, key, value)
                    lesson.title_key = lesson.title.casefold()
                    await self._changed(lesson)
                    await self._event(actor, lesson, "updated", changed_fields=sorted(changes))
                return await self._detail(actor, lesson)
        except IntegrityError:
            raise AuthError(409, "Ce titre de cours est déjà utilisé.") from None

    @staticmethod
    def section_root(element: LessonElement, by_id: dict[int, LessonElement]) -> LessonElement:
        """Find the owning section through the validated, shallow content tree."""
        while element.parent_id is not None:
            element = by_id[element.parent_id]
        return element

    @classmethod
    def section_staff(cls, parent: LessonElement, elements: list[LessonElement]) -> bool:
        """Preserve legacy private descendants until their section policy is normalized."""
        by_id = {item.id: item for item in elements}
        root = cls.section_root(parent, by_id)
        return any(
            item.audience == "staff" and cls.section_root(item, by_id).id == root.id
            for item in elements
        )

    def _element_values(
        self, kind: str, data: ElementFields, *, staff_only: bool = False
    ) -> dict[str, object]:
        """Validate type-specific content without accepting raw HTML embeds or remote fetches."""
        values = data.model_dump(
            include={"title", "body", "schedule_mode", "starts_on", "ends_on", "audience"}
        )
        if kind != "section" and data.audience != "students":
            raise AuthError(422, "La visibilité se règle uniquement sur la section.")
        if kind not in {"file", "youtube"} or staff_only:
            values.update(schedule_mode="inherit", starts_on=None, ends_on=None)
        if kind in {"section", "subsection", "table", "file"}:
            if not data.title or data.body:
                raise AuthError(422, "Une section nécessite un titre et aucun contenu libre.")
        elif not data.body.strip():
            raise AuthError(422, "Le contenu de cet élément est obligatoire.")
        elif kind == "youtube":
            try:
                values["body"] = f"https://www.youtube.com/watch?v={youtube_id(data.body.strip())}"
            except ValueError as error:
                raise AuthError(422, str(error)) from None
        return values

    async def add_element(
        self,
        actor: UserContext,
        lesson_id: int,
        data: ElementCreate,
    ) -> LessonDetail:
        """Enforce the shallow hierarchy and append an element with an inherited default rule."""
        async with self.db.begin():
            if data.kind == "file":
                raise AuthError(422, "Utilisez le dépôt de document pour créer un fichier.")
            lesson = await self._write(actor, lesson_id, data.expected_version)
            elements = await self.repo.elements(lesson.id)
            if len(elements) >= MAX_ELEMENTS:
                raise AuthError(422, "Ce cours a atteint la limite de 500 éléments.")
            parent = next((item for item in elements if item.id == data.parent_id), None)
            if data.kind == "section":
                valid = data.parent_id is None
            else:
                valid = parent is not None and parent.kind in {"section", "subsection", "table"}
                if data.kind == "subsection":
                    valid = valid and parent.kind == "section"
                if parent is not None and parent.kind == "table":
                    valid = valid and data.kind in {"text", "youtube"}
            self.validate_cell(parent, data.row_index, data.column_index)
            if (
                parent is not None
                and parent.kind == "table"
                and any(
                    item.parent_id == parent.id
                    and item.row_index == data.row_index
                    and item.column_index == data.column_index
                    for item in elements
                )
            ):
                raise AuthError(409, "Cette cellule contient déjà une ressource.")
            if not valid:
                raise AuthError(
                    422, "Cet élément doit appartenir à une section compatible du cours."
                )
            siblings = [item.position for item in elements if item.parent_id == data.parent_id]
            element = LessonElement(
                lesson_id=lesson.id,
                parent_id=data.parent_id,
                kind=data.kind,
                position=max(siblings, default=-1) + 1,
                row_index=data.row_index,
                column_index=data.column_index,
                table_rows=data.table_rows,
                table_columns=data.table_columns,
                **self._element_values(
                    data.kind,
                    data,
                    staff_only=parent is not None and self.section_staff(parent, elements),
                ),
            )
            self.db.add(element)
            await self.db.flush()
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                "element_created",
                element_id=element.id,
                element_kind=element.kind,
                element_title=element.title,
            )
            return await self._detail(actor, lesson)

    async def change_element(
        self,
        actor: UserContext,
        lesson_id: int,
        element_id: int,
        data: ElementUpdate,
    ) -> LessonDetail:
        """Edit only an element belonging to the page whose permissions were checked."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, data.expected_version)
            element = await self.db.get(LessonElement, element_id)
            if element is None or element.lesson_id != lesson.id:
                raise AuthError(404, "Élément introuvable.")
            elements = await self.repo.elements(lesson.id)
            changes = {
                key: value
                for key, value in self._element_values(
                    element.kind,
                    data,
                    staff_only=element.kind != "section" and self.section_staff(element, elements),
                ).items()
                if getattr(element, key) != value
            }
            descendants_changed = False
            if element.kind == "section":
                by_id = {item.id: item for item in elements}
                for child in elements:
                    if child.id != element.id and self.section_root(child, by_id).id == element.id:
                        if child.audience != "students":
                            child.audience = "students"
                            descendants_changed = True
                        if data.audience == "staff" or child.kind not in {"file", "youtube"}:
                            if child.schedule_mode != "inherit" or child.starts_on or child.ends_on:
                                child.schedule_mode, child.starts_on, child.ends_on = (
                                    "inherit",
                                    None,
                                    None,
                                )
                                descendants_changed = True
            previous_period = self._period_data(element)
            if changes or descendants_changed:
                for key, value in changes.items():
                    setattr(element, key, value)
                await self._changed(lesson)
                await self._event(
                    actor,
                    lesson,
                    "element_updated",
                    element_id=element.id,
                    element_kind=element.kind,
                    element_title=element.title,
                    changed_fields=sorted(changes),
                    previous_period=previous_period,
                    period=self._period_data(element),
                )
            return await self._detail(actor, lesson)

    def _period_data(self, element: LessonElement) -> dict[str, object]:
        """Serialize only scheduling facts for the immutable journal, never the text body."""
        return {
            "mode": element.schedule_mode,
            "starts_on": element.starts_on.isoformat() if element.starts_on else None,
            "ends_on": element.ends_on.isoformat() if element.ends_on else None,
        }

    async def remove_element(
        self,
        actor: UserContext,
        lesson_id: int,
        element_id: int,
        expected_version: int,
    ) -> LessonDetail:
        """Remove a confirmed subtree atomically and preserve its size in the audit event."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, expected_version)
            elements = await self.repo.elements(lesson.id)
            element = next((item for item in elements if item.id == element_id), None)
            if element is None:
                raise AuthError(404, "Élément introuvable.")
            ids = {element_id}
            while True:
                expanded = ids | {item.id for item in elements if item.parent_id in ids}
                if expanded == ids:
                    break
                ids = expanded
            await self.db.execute(delete(LessonElement).where(LessonElement.id.in_(ids)))
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                "element_deleted",
                element_id=element.id,
                element_kind=element.kind,
                element_title=element.title,
                removed_count=len(ids),
            )
            return await self._detail(actor, lesson)

    async def move_element(
        self,
        actor: UserContext,
        lesson_id: int,
        element_id: int,
        data: ElementMove,
    ) -> LessonDetail:
        """Swap sibling positions while preserving hierarchy and all element identifiers."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, data.expected_version)
            elements = await self.repo.elements(lesson.id)
            item = next((item for item in elements if item.id == element_id), None)
            if item is None:
                raise AuthError(404, "Élément introuvable.")
            if item.row_index is not None:
                raise AuthError(422, "Les cellules se déplacent avec leurs lignes et colonnes.")
            siblings = [element for element in elements if element.parent_id == item.parent_id]
            index = siblings.index(item)
            target = index + (-1 if data.direction == "up" else 1)
            if 0 <= target < len(siblings):
                other = siblings[target]
                item.position, other.position = other.position, item.position
                await self._changed(lesson)
                await self._event(
                    actor,
                    lesson,
                    "element_moved",
                    element_id=item.id,
                    element_kind=item.kind,
                    element_title=item.title,
                    direction=data.direction,
                )
            return await self._detail(actor, lesson)

    def validate_cell(
        self, parent: LessonElement | None, row: int | None, column: int | None
    ) -> None:
        """Reject missing/outside table coordinates and coordinates on ordinary content."""
        if parent is not None and parent.kind == "table":
            if (
                row is None
                or column is None
                or row >= parent.table_rows
                or column >= len(parent.table_columns)
            ):
                raise AuthError(422, "Cellule située en dehors du tableau.")
        elif row is not None or column is not None:
            raise AuthError(422, "Ces coordonnées ne correspondent pas à un tableau.")

    async def change_table(
        self, actor: UserContext, lesson_id: int, element_id: int, data: TableChange
    ) -> LessonDetail:
        """Change arbitrary column labels/dimensions and cascade documents from removed cells."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, data.expected_version)
            table = await self.db.get(LessonElement, element_id)
            if table is None or table.lesson_id != lesson.id or table.kind != "table":
                raise AuthError(404, "Tableau introuvable.")
            cells = [
                item for item in await self.repo.elements(lesson.id) if item.parent_id == table.id
            ]
            columns = list(table.table_columns)
            dimension = table.table_rows if data.action.endswith("row") else len(columns)
            if data.action.startswith("add"):
                maximum = 20 if data.action == "add_row" else 6
                if dimension >= maximum:
                    raise AuthError(422, "Le tableau a atteint sa taille maximale.")
                if data.action == "add_row":
                    table.table_rows += 1
                else:
                    label = " ".join(data.label.split())
                    if not label:
                        raise AuthError(422, "Donnez un titre à la nouvelle colonne.")
                    table.table_columns = [*columns, label]
            else:
                if data.index >= dimension:
                    raise AuthError(422, "Ligne ou colonne introuvable.")
                if data.action == "rename_column":
                    label = " ".join(data.label.split())
                    if not label:
                        raise AuthError(422, "Donnez un titre à la colonne.")
                    columns[data.index] = label
                    table.table_columns = columns
                else:
                    if dimension <= 1:
                        raise AuthError(422, "Conservez au moins une ligne et une colonne.")
                    coordinate = "row_index" if data.action == "remove_row" else "column_index"
                    for cell in cells:
                        if getattr(cell, coordinate) == data.index:
                            await self.db.delete(cell)
                    await self.db.flush()
                    for cell in sorted(cells, key=lambda cell: getattr(cell, coordinate)):
                        if getattr(cell, coordinate) > data.index:
                            setattr(cell, coordinate, getattr(cell, coordinate) - 1)
                            await self.db.flush()
                    if data.action == "remove_row":
                        table.table_rows -= 1
                    else:
                        table.table_columns = columns[: data.index] + columns[data.index + 1 :]
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                "element_updated",
                element_id=table.id,
                element_kind="table",
                element_title=table.title,
                changed_fields=["table_structure"],
            )
            return await self._detail(actor, lesson)

    async def remove(self, actor: UserContext, lesson_id: int, expected_version: int) -> None:
        """Delete a whole course only for its eligible responsible teacher or an administrator."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, expected_version, collaborators=True)
            await self._event(actor, lesson, "deleted")
            await self.db.delete(lesson)

    async def collaborator(
        self,
        actor: UserContext,
        lesson_id: int,
        user_id: int,
        expected_version: int,
        *,
        add: bool,
    ) -> LessonDetail:
        """Let the eligible responsible teacher or administrator change collaboration grants."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, expected_version, collaborators=True)
            if user_id == lesson.responsible_id:
                raise AuthError(422, "Le créateur ne peut pas être ajouté comme collaborateur.")
            link = await self.db.get(LessonCollaborator, (lesson_id, user_id))
            if add:
                user = await self.db.get(User, user_id)
                if user is None or user.status != "active" or user.is_bootstrap:
                    raise AuthError(422, "Choisissez un enseignant ou un khôlleur actif.")
                permissions = await self.auth.repo.permissions(user_id)
                if "kholleur.access" not in permissions and not (
                    "teacher.access" in permissions
                    and await has_subject(self.db, user_id, lesson.subject_id)
                ):
                    raise AuthError(
                        422,
                        "Choisissez un khôlleur ou un enseignant possédant la matière du cours.",
                    )
            if add and link is None:
                self.db.add(LessonCollaborator(lesson_id=lesson.id, user_id=user_id))
            elif not add and link is not None:
                await self.db.delete(link)
            else:
                return await self._detail(actor, lesson)
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                "collaborator_added" if add else "collaborator_removed",
                subject_id=user_id,
            )
            return await self._detail(actor, lesson)

    async def promotion(
        self,
        actor: UserContext,
        lesson_id: int,
        promotion_id: int,
        data: PromotionGrant,
        *,
        add: bool,
    ) -> LessonDetail:
        """Grant, renew or revoke access without changing administrator-owned memberships."""
        async with self.db.begin():
            lesson = await self._write(actor, lesson_id, data.expected_version)
            promotion = await self.db.get(Promotion, promotion_id)
            if promotion is None:
                raise AuthError(404, "Promotion introuvable.")
            grant = await self.db.get(LessonPromotion, (lesson_id, promotion_id))
            previous_period = None
            if add:
                if not promotion.is_active:
                    raise AuthError(409, "Une promotion archivée ne peut pas recevoir d’accès.")
                start, end = (
                    (data.starts_on, data.ends_on)
                    if data.starts_on
                    else school_year_period(promotion.year)
                )
                if grant is not None and grant.starts_on == start and grant.ends_on == end:
                    return await self._detail(actor, lesson)
                if grant is None:
                    grant = LessonPromotion(
                        lesson_id=lesson.id, promotion_id=promotion_id, starts_on=start, ends_on=end
                    )
                    self.db.add(grant)
                    action = "promotion_added"
                else:
                    previous_period = {
                        "mode": "range",
                        "starts_on": grant.starts_on.isoformat(),
                        "ends_on": grant.ends_on.isoformat(),
                    }
                    grant.starts_on, grant.ends_on = start, end
                    action = "promotion_updated"
            elif grant is not None:
                start, end = grant.starts_on, grant.ends_on
                await self.db.delete(grant)
                action = "promotion_removed"
            else:
                return await self._detail(actor, lesson)
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                action,
                promotion_id=promotion.id,
                promotion={
                    "identifier": promotion.identifier,
                    "year": promotion.year,
                    "color": promotion.color,
                },
                period={
                    "mode": "range",
                    "starts_on": start.isoformat(),
                    "ends_on": end.isoformat(),
                },
                previous_period=previous_period,
            )
            return await self._detail(actor, lesson)

    async def promotion_options(
        self,
        actor: UserContext,
        lesson_id: int,
        offset: int,
        limit: int,
    ) -> list[PromotionBadge]:
        """Expose only active promotion metadata to an authorized page editor."""
        async with self.db.begin():
            teacher, admin = await self._principal(actor)
            lesson = await self._lesson(lesson_id)
            if not (await self._edit_rights(actor, lesson, teacher, admin))[0]:
                raise AuthError(403, "Accès réservé aux éditeurs du cours.")
            promotions = (
                await self.db.scalars(
                    select(Promotion)
                    .where(Promotion.is_active)
                    .order_by(Promotion.year.desc(), Promotion.identifier, Promotion.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return [
                PromotionBadge.model_validate(item, from_attributes=True) for item in promotions
            ]

    async def teacher_options(
        self,
        actor: UserContext,
        lesson_id: int,
        query: str,
    ) -> list[LessonPerson]:
        """Offer five unassociated teaching identities within the collaboration policy."""
        async with self.db.begin():
            teacher, admin = await self._principal(actor)
            lesson = await self._lesson(lesson_id)
            if not (await self._edit_rights(actor, lesson, teacher, admin))[1]:
                raise AuthError(
                    403, "Seul le responsable ou un administrateur peut ajouter des collaborateurs."
                )
            ids = (
                await self.db.scalars(
                    select(User.id)
                    .join(UserRole)
                    .join(Role)
                    .where(
                        Role.code.in_(["teacher", "kholleur"]),
                        User.status == "active",
                        ~User.is_bootstrap,
                        User.id.not_in({lesson.responsible_id, lesson.creator_id}),
                        ~select(LessonCollaborator.user_id)
                        .where(
                            LessonCollaborator.lesson_id == lesson.id,
                            LessonCollaborator.user_id == User.id,
                        )
                        .exists(),
                    )
                    .distinct()
                    .order_by(User.id)
                )
            ).all()
            needle = normalized_title(query).casefold()
            results = []
            for user_id in ids:
                grants = await self.auth.repo.permissions(user_id)
                if "kholleur.access" not in grants and not (
                    "teacher.access" in grants
                    and await has_subject(self.db, user_id, lesson.subject_id)
                ):
                    continue
                person = await self._person(user_id, lesson.subject_id)
                person.role = "teacher" if person.can_edit else "kholleur"
                if needle in person.label.casefold():
                    results.append(person)
                    if len(results) == 5:
                        break
            return results

    async def responsible_options(
        self, actor: UserContext, lesson_id: int, subject_id: int, query: str
    ) -> list[LessonPerson]:
        """Search active teachers currently eligible to manage the chosen subject."""
        async with self.db.begin():
            await self.auth._actor(actor, admin=True)
            await self._lesson(lesson_id)
            ids = (
                await self.db.scalars(
                    select(User.id)
                    .join(TeacherSubject)
                    .where(
                        TeacherSubject.subject_id == subject_id,
                        User.status == "active",
                        ~User.is_bootstrap,
                    )
                    .order_by(User.id)
                )
            ).all()
            results = []
            for identifier in ids:
                if "teacher.access" not in await self.auth.repo.permissions(identifier):
                    continue
                person = await self._person(identifier, subject_id)
                if normalized_title(query).casefold() in person.label.casefold():
                    results.append(person)
                if len(results) >= 20:
                    break
            return results

    async def transfer(
        self, actor: UserContext, lesson_id: int, data: ResponsibilityUpdate
    ) -> LessonDetail:
        """Let administrators replace responsibility without rewriting the original authorship."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.auth._actor(actor, admin=True)
            lesson = await self._lesson(lesson_id, lock=True)
            if lesson.version != data.expected_version:
                raise AuthError(409, "Ce cours a été modifié. Rechargez-le.")
            user = await self.db.get(User, data.responsible_id)
            if (
                user is None
                or user.status != "active"
                or user.is_bootstrap
                or "teacher.access" not in await self.auth.repo.permissions(user.id)
                or not await has_subject(self.db, user.id, data.subject_id)
            ):
                raise AuthError(
                    422,
                    "Le responsable doit être un enseignant actif possédant la matière choisie.",
                )
            previous_subject = lesson.subject_id
            previous_responsible = lesson.responsible_id
            if (previous_subject, previous_responsible) == (data.subject_id, data.responsible_id):
                return await self._detail(actor, lesson)
            lesson.responsible_id, lesson.subject_id = data.responsible_id, data.subject_id
            # A former responsible teacher receives no implicit collaborator grant.
            await self.db.execute(
                delete(LessonCollaborator).where(
                    LessonCollaborator.lesson_id == lesson.id,
                    LessonCollaborator.user_id.in_({previous_responsible, user.id}),
                )
            )
            for link in (
                await self.db.scalars(
                    select(LessonCollaborator).where(LessonCollaborator.lesson_id == lesson.id)
                )
            ).all():
                grants = await self.auth.repo.permissions(link.user_id)
                if "kholleur.access" not in grants and not await has_subject(
                    self.db, link.user_id, lesson.subject_id
                ):
                    await self.db.delete(link)
            await self._changed(lesson)
            await self._event(
                actor,
                lesson,
                "responsibility_updated",
                subject_id=user.id,
                changed_fields=["responsible_id", "subject_id"],
                previous_responsible_id=previous_responsible,
                previous_subject_id=previous_subject,
            )
            return await self._detail(actor, lesson)
