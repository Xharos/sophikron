"""Transactional subject administration and public homepage configuration."""

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.models.auth import Role, User, UserRole
from app.models.lessons import Lesson
from app.models.site import (
    SiteSettings,
    Subject,
    TeacherSubject,
    Timeline,
    TimelineEvent,
    TimelineEventBar,
)
from app.schemas.site import (
    EventFields,
    EventResponse,
    EventUpdate,
    PublicSite,
    SettingsResponse,
    SettingsUpdate,
    SubjectFields,
    SubjectResponse,
    SubjectUpdate,
    TimelineFields,
    TimelineResponse,
    TimelineUpdate,
)
from app.services.activity import SubjectSnapshot, record_event, record_subject_changes
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.lessons import PARIS


class SiteService:
    """Separate administrator writes from a deliberately narrow anonymous publication API."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse request-owned authentication and database resources."""
        self.auth, self.db = auth, auth.db

    async def _admin(self, actor: UserContext) -> None:
        """Serialize mutations against all account, role and course eligibility changes."""
        await self.auth._lifecycle_lock()
        await self.auth._actor(actor, admin=True)

    async def _event(
        self,
        actor: UserContext,
        action: str,
        resource: str,
        identifier: int,
        data: dict[str, object],
    ) -> None:
        """Journal bounded public facts without copying editable homepage text."""
        await record_event(
            self.db, action, actor.id, resource_type=resource, resource_id=identifier, data=data
        )

    async def subjects(
        self,
        actor: UserContext,
        *,
        q: str = "",
        is_active: bool | None = True,
        offset: int = 0,
        limit: int = 50,
        mine: bool = False,
    ) -> dict[str, object]:
        """Return a bounded catalogue, or only the current teacher's active assignments."""
        async with self.db.begin():
            await self.auth._actor(actor, permission="teacher.access" if mine else "users.manage")
            statement = select(Subject)
            if mine:
                statement = statement.join(TeacherSubject).where(TeacherSubject.user_id == actor.id)
                is_active = True
            if is_active is not None:
                statement = statement.where(Subject.is_active == is_active)
            if q.strip():
                escaped = (
                    q.strip()
                    .casefold()
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                statement = statement.where(Subject.name_key.like(f"%{escaped}%", escape="\\"))
            total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
            rows = (
                await self.db.scalars(
                    statement.order_by(Subject.name_key).offset(offset).limit(limit)
                )
            ).all()
            items = []
            for row in rows:
                teachers = (
                    await self.db.scalar(
                        select(func.count(func.distinct(TeacherSubject.user_id)))
                        .select_from(TeacherSubject)
                        .join(User, User.id == TeacherSubject.user_id)
                        .join(UserRole, UserRole.user_id == User.id)
                        .join(Role)
                        .where(
                            TeacherSubject.subject_id == row.id,
                            Role.code.in_(["teacher", "kholleur"]),
                            User.status.in_(["pending_activation", "active"]),
                        )
                    )
                    if not mine
                    else 0
                )
                lessons = (
                    await self.db.scalar(
                        select(func.count()).select_from(Lesson).where(Lesson.subject_id == row.id)
                    )
                    if not mine
                    else 0
                )
                items.append(
                    SubjectResponse.model_validate(
                        {
                            **{
                                key: getattr(row, key)
                                for key in ("id", "name", "icon", "color", "is_active", "version")
                            },
                            "teacher_count": teachers,
                            "lesson_count": lessons,
                        }
                    )
                )
            return {"items": items, "total": total, "offset": offset, "limit": limit}

    async def subject_save(
        self, actor: UserContext, data: SubjectFields | SubjectUpdate, subject_id: int | None = None
    ) -> SubjectResponse:
        """Create or update the shared course identity with conflict detection."""
        try:
            async with self.db.begin():
                await self._admin(actor)
                previous = None
                changed_fields = []
                if subject_id is None:
                    row = Subject(**data.model_dump(), name_key=data.name.casefold())
                    self.db.add(row)
                else:
                    row = await self.db.get(Subject, subject_id, with_for_update=True)
                    if row is None:
                        raise AuthError(404, "Matière introuvable.")
                    self._version(row, data.expected_version)
                    if not row.is_active:
                        raise AuthError(409, "Cette matière est archivée.")
                    previous = SubjectSnapshot.model_validate(row, from_attributes=True).model_dump(
                        mode="json"
                    )
                    changed_fields = [
                        key
                        for key in ("name", "icon", "color")
                        if getattr(row, key) != getattr(data, key)
                    ]
                    for key, value in data.model_dump(exclude={"expected_version"}).items():
                        setattr(row, key, value)
                    row.name_key = data.name.casefold()
                    row.version += 1
                    await self.db.execute(
                        update(Lesson)
                        .where(Lesson.subject_id == row.id)
                        .values(version=Lesson.version + 1)
                    )
                await self.db.flush()
                await self._event(
                    actor,
                    "subject.saved",
                    "subject",
                    row.id,
                    {
                        "action": "created" if subject_id is None else "updated",
                        "subject": SubjectSnapshot.model_validate(
                            row, from_attributes=True
                        ).model_dump(mode="json"),
                        "previous": previous,
                        "changed_fields": changed_fields,
                    },
                )
                return SubjectResponse.model_validate(row, from_attributes=True)
        except IntegrityError:
            raise AuthError(
                409, "Une matière porte déjà ce nom, y compris dans les archives."
            ) from None

    async def subject_archive(self, actor: UserContext, subject_id: int, version: int) -> None:
        """Refuse used subjects; otherwise archive and remove teacher assignments atomically."""
        async with self.db.begin():
            await self._admin(actor)
            row = await self.db.get(Subject, subject_id, with_for_update=True)
            if row is None:
                raise AuthError(404, "Matière introuvable.")
            self._version(row, version)
            if await self.db.scalar(
                select(Lesson.id).where(Lesson.subject_id == subject_id).limit(1)
            ):
                raise AuthError(
                    409,
                    "Impossible de supprimer cette matière : elle est utilisée par un cours. "
                    "Réaffectez d’abord la matière du cours.",
                )
            user_ids = list(
                await self.db.scalars(
                    select(TeacherSubject.user_id).where(TeacherSubject.subject_id == subject_id)
                )
            )
            for user_id in user_ids:
                await record_subject_changes(
                    self.db,
                    actor.id,
                    user_id,
                    added=set(),
                    removed={subject_id},
                    reason="subject_archived",
                )
            users = select(TeacherSubject.user_id).where(TeacherSubject.subject_id == subject_id)
            await self.db.execute(
                update(User)
                .where(User.id.in_(users))
                .values(profile_version=User.profile_version + 1)
            )
            await self.db.execute(
                delete(TeacherSubject).where(TeacherSubject.subject_id == subject_id)
            )
            row.is_active = False
            row.version += 1
            await self._event(
                actor,
                "subject.archived",
                "subject",
                row.id,
                {
                    "action": "archived",
                    "subject": SubjectSnapshot.model_validate(row, from_attributes=True).model_dump(
                        mode="json"
                    ),
                    "removed_assignments": len(user_ids),
                },
            )

    @staticmethod
    def _version(row: object, expected: int) -> None:
        """Reject stale editor revisions before changing any related table."""
        if row.version != expected:
            raise AuthError(409, "Cet élément a été modifié. Rechargez-le avant de réessayer.")

    async def public(self) -> PublicSite:
        """Publish only intentionally public text, dates and visual metadata."""
        async with self.db.begin():
            settings = await self.db.get(SiteSettings, 1)
            bars = (
                await self.db.scalars(select(Timeline).order_by(Timeline.starts_on, Timeline.id))
            ).all()
            links: dict[int, list[int]] = {}
            for event_id, timeline_id in await self.db.execute(
                select(TimelineEventBar.event_id, TimelineEventBar.timeline_id).order_by(
                    TimelineEventBar.timeline_id
                )
            ):
                links.setdefault(event_id, []).append(timeline_id)
            events = (
                await self.db.scalars(
                    select(TimelineEvent).order_by(TimelineEvent.starts_on, TimelineEvent.id)
                )
            ).all()
            return PublicSite(
                settings=SettingsResponse.model_validate(settings, from_attributes=True)
                if settings
                else SettingsResponse(name="Sophikron", home_text=""),
                timelines=[
                    TimelineResponse.model_validate(row, from_attributes=True) for row in bars
                ],
                events=[
                    EventResponse.model_validate(
                        {
                            **{
                                key: getattr(row, key)
                                for key in (
                                    "id",
                                    "name",
                                    "color",
                                    "starts_on",
                                    "ends_on",
                                    "kind",
                                    "version",
                                )
                            },
                            "color": settings.holiday_color
                            if row.kind == "holiday" and settings
                            else row.color,
                            "timeline_ids": links[row.id],
                        }
                    )
                    for row in events
                    if links.get(row.id)
                ],
                today=self.auth.clock().astimezone(PARIS).date(),
            )

    async def settings_save(self, actor: UserContext, data: SettingsUpdate) -> SettingsResponse:
        """Apply public presentation immediately without caches or restart requirements."""
        async with self.db.begin():
            await self._admin(actor)
            row = await self.db.get(SiteSettings, 1, with_for_update=True)
            self._version(row, data.expected_version)
            values = data.model_dump(exclude={"expected_version"}, exclude_unset=True)
            changed_fields = [key for key, value in values.items() if getattr(row, key) != value]
            previous_name = row.name
            if not changed_fields:
                return SettingsResponse.model_validate(row, from_attributes=True)
            for key, value in values.items():
                setattr(row, key, value)
            if "holiday_color" in changed_fields:
                await self.db.execute(
                    update(TimelineEvent)
                    .where(
                        TimelineEvent.kind == "holiday", TimelineEvent.color != row.holiday_color
                    )
                    .values(color=row.holiday_color, version=TimelineEvent.version + 1)
                )
            row.version += 1
            await self._event(
                actor,
                "site.updated",
                "site",
                1,
                {
                    "changed_fields": changed_fields,
                    "previous_name": previous_name,
                    "name": row.name,
                },
            )
            return SettingsResponse.model_validate(row, from_attributes=True)

    async def calendar_save(
        self,
        actor: UserContext,
        data: TimelineFields | TimelineUpdate | EventFields | EventUpdate,
        *,
        event: bool,
        identifier: int | None = None,
    ) -> TimelineResponse | EventResponse:
        """Save a bar or event and its shared associations in one locked transaction."""
        async with self.db.begin():
            await self._admin(actor)
            model = TimelineEvent if event else Timeline
            values = data.model_dump(exclude={"expected_version", "timeline_ids", "icon"})
            if event and data.kind == "holiday":
                settings = await self.db.get(SiteSettings, 1)
                values["color"] = settings.holiday_color
            previous_values = {}
            previous_links = []
            if identifier is None:
                if (await self.db.scalar(select(func.count()).select_from(model))) >= (
                    200 if event else 20
                ):
                    raise AuthError(422, "La limite du calendrier est atteinte.")
                row = model(**values)
                self.db.add(row)
            else:
                row = await self.db.get(model, identifier, with_for_update=True)
                if row is None:
                    raise AuthError(404, "Élément du calendrier introuvable.")
                self._version(row, data.expected_version)
                previous_values = {key: getattr(row, key) for key in values}
                if event:
                    previous_links = list(
                        await self.db.scalars(
                            select(TimelineEventBar.timeline_id).where(
                                TimelineEventBar.event_id == row.id
                            )
                        )
                    )
                for key, value in values.items():
                    setattr(row, key, value)
                row.version += 1
            await self.db.flush()
            if event:
                bars = (
                    await self.db.scalars(
                        select(Timeline).where(Timeline.id.in_(data.timeline_ids))
                    )
                ).all()
                if len(bars) != len(data.timeline_ids):
                    raise AuthError(422, "Une timeline sélectionnée n’existe plus.")
                if any(
                    data.starts_on < bar.starts_on or data.ends_on > bar.ends_on for bar in bars
                ):
                    raise AuthError(
                        422,
                        "L’événement doit être compris dans les dates "
                        "de chaque timeline sélectionnée.",
                    )
                await self.db.execute(
                    delete(TimelineEventBar).where(TimelineEventBar.event_id == row.id)
                )
                self.db.add_all(
                    [TimelineEventBar(event_id=row.id, timeline_id=bar.id) for bar in bars]
                )
                result = EventResponse.model_validate(
                    {
                        **{
                            key: getattr(row, key)
                            for key in (
                                "id",
                                "name",
                                "color",
                                "starts_on",
                                "ends_on",
                                "kind",
                                "version",
                            )
                        },
                        "timeline_ids": data.timeline_ids,
                    }
                )
            else:
                invalid = await self.db.scalar(
                    select(TimelineEvent.id)
                    .join(TimelineEventBar)
                    .where(
                        TimelineEventBar.timeline_id == row.id,
                        (TimelineEvent.starts_on < row.starts_on)
                        | (TimelineEvent.ends_on > row.ends_on),
                    )
                    .limit(1)
                )
                if invalid:
                    raise AuthError(
                        409,
                        "Ces dates excluent un événement associé. Modifiez d’abord l’événement.",
                    )
                result = TimelineResponse.model_validate(row, from_attributes=True)
            changed_fields = [
                key for key, value in previous_values.items() if value != getattr(row, key)
            ]
            if identifier is not None and event and set(previous_links) != set(data.timeline_ids):
                changed_fields.append("timeline_ids")
            await self._event(
                actor,
                "calendar.saved",
                "calendar",
                row.id,
                {
                    "entry_type": "event" if event else "timeline",
                    "action": "created" if identifier is None else "updated",
                    "name": row.name,
                    "starts_on": row.starts_on,
                    "ends_on": row.ends_on,
                    "kind": row.kind if event else None,
                    "changed_fields": changed_fields,
                    "timeline_count": len(data.timeline_ids) if event else None,
                },
            )
            return result

    async def calendar_delete(
        self, actor: UserContext, identifier: int, version: int, *, event: bool
    ) -> None:
        """Delete a calendar entry, preserving shared events still used by another bar."""
        async with self.db.begin():
            await self._admin(actor)
            model = TimelineEvent if event else Timeline
            row = await self.db.get(model, identifier, with_for_update=True)
            if row is None:
                raise AuthError(404, "Élément du calendrier introuvable.")
            self._version(row, version)
            deleted_events = retained_events = 0
            if not event:
                affected = list(
                    await self.db.scalars(
                        select(TimelineEventBar.event_id).where(
                            TimelineEventBar.timeline_id == identifier
                        )
                    )
                )
                await self.db.execute(
                    delete(TimelineEventBar).where(TimelineEventBar.timeline_id == identifier)
                )
                await self.db.execute(
                    update(TimelineEvent)
                    .where(TimelineEvent.id.in_(affected))
                    .values(version=TimelineEvent.version + 1)
                )
                deleted_events = await self.db.scalar(
                    select(func.count())
                    .select_from(TimelineEvent)
                    .where(
                        TimelineEvent.id.in_(affected),
                        ~TimelineEvent.id.in_(select(TimelineEventBar.event_id)),
                    )
                )
                retained_events = len(affected) - deleted_events
                await self.db.execute(
                    delete(TimelineEvent).where(
                        TimelineEvent.id.in_(affected),
                        ~TimelineEvent.id.in_(select(TimelineEventBar.event_id)),
                    )
                )
            await self.db.delete(row)
            await self._event(
                actor,
                "calendar.deleted",
                "calendar",
                identifier,
                {
                    "entry_type": "event" if event else "timeline",
                    "action": "deleted",
                    "name": row.name,
                    "starts_on": row.starts_on,
                    "ends_on": row.ends_on,
                    "kind": row.kind if event else None,
                    "deleted_events": deleted_events,
                    "retained_events": retained_events,
                },
            )
