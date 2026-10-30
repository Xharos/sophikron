"""Private annual timetable authorization, live mutations and personal calendar feeds."""

import math
import re
from datetime import date, datetime, timezone
from uuid import uuid4

from icalendar import Calendar, Event
from sqlalchemy import delete, literal, select, update

from app.core.security import token_digest
from app.models import (
    Promotion,
    PromotionCustomGroup,
    PromotionCustomGroupMember,
    PromotionGroup,
    PromotionGroupMember,
    Role,
    Subject,
    TeacherAvailability,
    TeacherSubject,
    TimetableCalendar,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableSeries,
    TimetableSubscription,
    TimetableYear,
    User,
    UserPromotion,
    UserRole,
)
from app.models.site import SiteSettings
from app.repositories.timetable import TimetableRepository
from app.schemas.timetable import (
    CalendarSave,
    EventPreview,
    OccurrenceEdit,
    SeriesFields,
    SessionFields,
    Version,
    YearDocument,
    YearSettings,
)
from app.services.activity import record_event
from app.services.auth import AuthService, UserContext
from app.services.calendar_subscriptions import student_promotions
from app.services.errors import AuthError
from app.services.timetable_assignments import assigned_teachers, individual_assignments
from app.services.timetable_engine import (
    PARIS,
    apply_event_change,
    current_school_year,
    daily_slots,
    occurrences,
    teaching_weeks,
)


class TimetableService:
    """Own transactions and recompute current rights for every timetable operation."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse request authentication resources and separate persistence queries."""
        self.auth = auth
        self.db = auth.db
        self.repo = TimetableRepository(self.db)

    def today(self) -> date:
        """Use the application's injectable clock in the school's Europe/Paris timezone."""
        return self.auth.clock().astimezone(PARIS).date()

    async def authorize(self, actor: UserContext, *, write: bool = False) -> bool:
        """Deny student web access and return whether the active actor is an administrator."""
        current = await self.auth._actor(actor)
        permissions = await self.auth.repo.permissions(actor.id)
        admin = "users.manage" in permissions and not current.is_bootstrap
        if (
            current.is_bootstrap
            or (write and not admin)
            or (not admin and not {"teaching.read", "kholleur.access"}.intersection(permissions))
        ):
            raise AuthError(403, "Vous n’avez pas accès aux emplois du temps.")
        from app.services.timetable_lifecycle import rollover

        await rollover(self.db, self.today())
        return admin

    async def _calendar(
        self, identifier: int, actor: UserContext, *, write: bool
    ) -> TimetableCalendar:
        """Hide unrelated calendars after checking current staff scope."""
        admin = await self.authorize(actor, write=write)
        calendars = await self.repo.calendars(
            None if admin else actor.id,
            archives=admin or "teaching.read" in await self.auth.repo.permissions(actor.id),
        )
        calendar = next((row for row in calendars if row.id == identifier), None)
        if calendar is None:
            raise AuthError(404, "Agenda introuvable.")
        if write and calendar.is_archived:
            raise AuthError(409, "Un calendrier archivé est en lecture seule.")
        return calendar

    async def _year(self, identifier: int, actor: UserContext, version: Version) -> TimetableYear:
        """Lock calendars after authorization and reject stale editing revisions."""
        await self.auth._lifecycle_lock()
        await self.authorize(actor, write=True)
        row = await self.db.scalar(
            select(TimetableYear).where(TimetableYear.id == identifier).with_for_update()
        )
        if row is None:
            raise AuthError(404, "Année scolaire introuvable.")
        calendar = await self.db.get(TimetableCalendar, row.calendar_id)
        if calendar is None:
            raise AuthError(404, "Agenda introuvable.")
        if calendar.is_archived:
            raise AuthError(409, "Un calendrier archivé est en lecture seule.")
        self.require_live_confirmation(calendar, version.confirmed_live)
        if row.revision != version.expected_revision:
            raise AuthError(409, "L’agenda a changé. Rechargez-le avant de continuer.")
        return row

    async def _references(
        self,
        block: SessionFields,
        calendar: TimetableCalendar,
        *,
        historical: bool = False,
        allow_unavailable_teacher: bool = False,
    ) -> None:
        """Validate live subject, teaching role and canonical room independently of the UI."""
        if len(block.teacher_ids) > 1:
            for identifier in block.teacher_ids:
                await self._references(
                    block.model_copy(
                        update={"teacher_id": identifier, "teacher_ids": [identifier]}
                    ),
                    calendar,
                    historical=historical,
                    allow_unavailable_teacher=allow_unavailable_teacher,
                )
            return
        subject = (
            await self.db.get(Subject, block.subject_id) if block.subject_id is not None else None
        )
        teacher = (
            await self.db.get(User, block.teacher_id) if block.teacher_id is not None else None
        )
        room = (
            await self.db.get(TimetableRoom, block.room_id) if block.room_id is not None else None
        )
        roles = (
            await self.auth.repo.roles(block.teacher_id) if block.teacher_id is not None else set()
        )
        if (
            (
                block.subject_id is not None
                and (subject is None or (not historical and not subject.is_active))
            )
            or (
                block.room_id is not None
                and (room is None or (not historical and not room.is_active))
            )
            or (
                block.teacher_id is not None
                and (
                    teacher is None
                    or teacher.is_bootstrap
                    or (
                        not historical
                        and not allow_unavailable_teacher
                        and (
                            teacher.status == "disabled"
                            or not {"teacher", "kholleur"}.intersection(roles)
                            or (block.kind != "kholle" and "teacher" not in roles)
                        )
                    )
                )
            )
        ):
            raise AuthError(422, "Choisissez une matière, une salle et un enseignant disponibles.")
        if calendar.promotion_id is not None:
            promotion = await self.db.get(Promotion, calendar.promotion_id)
            if promotion is None or not promotion.is_active:
                raise AuthError(
                    409, "Réaffectez l’agenda à une promotion active avant de l’éditer."
                )
        if not historical and block.target_kind != "promotion":
            if block.target_kind in {"halves", "thirds"}:
                return
            if calendar.promotion_id is None:
                raise AuthError(
                    422, "Affectez une promotion avant de choisir un groupe ou un élève."
                )
            if block.target_kind == "student":
                valid = await self.db.scalar(
                    select(User.id)
                    .join(UserPromotion)
                    .where(
                        User.id == block.target_user_id,
                        UserPromotion.promotion_id == calendar.promotion_id,
                        User.status != "disabled",
                        select(UserRole.user_id)
                        .join(Role)
                        .where(UserRole.user_id == User.id, Role.code == "user")
                        .exists(),
                    )
                )
            elif block.target_kind == "custom":
                valid = await self.db.scalar(
                    select(PromotionCustomGroup.id).where(
                        PromotionCustomGroup.id == block.target_number,
                        PromotionCustomGroup.promotion_id == calendar.promotion_id,
                        PromotionCustomGroup.is_active.is_(True),
                        select(PromotionCustomGroupMember.user_id)
                        .where(PromotionCustomGroupMember.group_id == PromotionCustomGroup.id)
                        .exists(),
                    )
                )
            else:
                valid = await self.db.get(
                    PromotionGroup, (calendar.promotion_id, block.target_kind, block.target_number)
                )
            if not valid:
                raise AuthError(
                    422, "Ce destinataire n’appartient plus à la promotion de l’agenda."
                )

    @staticmethod
    def require_live_confirmation(calendar: TimetableCalendar, confirmed: bool) -> None:
        """Require explicit acknowledgement before changing a calendar currently broadcast."""
        if not calendar.is_paused and calendar.promotion_id is not None and not confirmed:
            raise AuthError(409, "Confirmez la modification de ce calendrier diffusé en direct.")

    async def common_years(self) -> list[dict]:
        """Return immutable year labels and their permanent usage markers in one query."""
        return [
            {"school_year": row.school_year, "used": row.used, "revision": row.revision}
            for row in await self.db.scalars(
                select(TimetableSchoolYear).order_by(TimetableSchoolYear.school_year.desc())
            )
        ]

    async def catalog(self, actor: UserContext) -> dict:
        """Return minimal calendar and member metadata inside the caller's current scope."""
        async with self.db.begin():
            admin = await self.authorize(actor)
            read_archives = admin or "teaching.read" in await self.auth.repo.permissions(actor.id)
            calendars = await self.repo.calendars(
                None if admin else actor.id, archives=read_archives
            )
            all_years = list(
                await self.db.scalars(
                    select(TimetableYear).where(
                        TimetableYear.calendar_id.in_([calendar.id for calendar in calendars])
                    )
                )
            )
            items = []
            for calendar in calendars:
                visible = [
                    year
                    for year in all_years
                    if year.calendar_id == calendar.id
                    and (
                        admin
                        or calendar.is_archived
                        or year.starts_on <= self.today() <= year.ends_on
                    )
                ]
                if not admin and not visible:
                    continue
                items.append(
                    {
                        "id": calendar.id,
                        "name": calendar.name,
                        "promotion_id": calendar.promotion_id,
                        "revision": calendar.revision if admin else None,
                        "is_paused": calendar.is_paused,
                        "is_archived": calendar.is_archived,
                        "years": [
                            {
                                "id": year.id,
                                "school_year": year.school_year,
                                "revision": year.revision if admin else None,
                            }
                            for year in visible
                        ],
                    }
                )

            promotion_query = select(Promotion).where(Promotion.is_active.is_(True))
            if not admin:
                promotion_query = promotion_query.join(UserPromotion).where(
                    UserPromotion.user_id == actor.id
                )
            promotions = list(await self.db.scalars(promotion_query.order_by(Promotion.identifier)))
            teachers = []
            if admin:
                users = list(
                    await self.db.scalars(
                        select(User)
                        .where(
                            User.is_bootstrap.is_(False),
                            (User.status != "disabled")
                            if read_archives
                            else (User.status == "active"),
                            select(UserRole.user_id)
                            .join(Role)
                            .where(
                                UserRole.user_id == User.id, Role.code.in_(["teacher", "kholleur"])
                            )
                            .exists(),
                        )
                        .order_by(User.id)
                    )
                )
                subject_map: dict[int, list[int]] = {}
                role_map: dict[int, list[str]] = {}
                for user_id, code in await self.db.execute(
                    select(UserRole.user_id, Role.code)
                    .join(Role)
                    .where(
                        UserRole.user_id.in_({user.id for user in users}),
                        Role.code.in_(["teacher", "kholleur"]),
                    )
                ):
                    role_map.setdefault(user_id, []).append(code)
                for user_id, subject_id in await self.db.execute(
                    select(TeacherSubject.user_id, TeacherSubject.subject_id)
                    .join(Subject)
                    .where(
                        TeacherSubject.user_id.in_({user.id for user in users}),
                        Subject.is_active.is_(True),
                    )
                ):
                    subject_map.setdefault(user_id, []).append(subject_id)
                teachers = [
                    {
                        **self._identity(user),
                        "subject_ids": sorted(subject_map.get(user.id, [])),
                        "roles": sorted(role_map.get(user.id, [])),
                    }
                    for user in users
                ]
            return {
                "administrator": admin,
                "can_read_archives": read_archives,
                "today": self.today().isoformat(),
                "calendars": items,
                "promotions": [
                    {"id": item.id, "name": f"{item.identifier} {item.year}"} for item in promotions
                ],
                "teachers": teachers,
                "common_years": await self.common_years() if admin else [],
                "subjects": [
                    {"id": item.id, "name": item.name, "color": item.color}
                    for item in await self.db.scalars(
                        select(Subject).where(Subject.is_active.is_(True))
                    )
                ],
                "rooms": [
                    {"id": item.id, "name": item.name, "revision": item.revision}
                    for item in await self.db.scalars(
                        select(TimetableRoom)
                        .where(TimetableRoom.is_active.is_(True))
                        .order_by(TimetableRoom.name)
                    )
                ],
            }

    def _identity(self, user: User) -> dict:
        """Decrypt only the names needed by an already-authorized timetable view."""
        return {
            "id": user.id,
            "name": " ".join(
                [
                    self.auth.cipher.decrypt(user.id, "first_name", user.first_name_encrypted)
                    or "",
                    self.auth.cipher.decrypt(user.id, "last_name", user.last_name_encrypted) or "",
                ]
            ).strip(),
        }

    async def save_calendar(
        self, actor: UserContext, data: CalendarSave, identifier: int | None
    ) -> dict:
        """Create one annual calendar or confirm its live rename, assignment or diffusion change."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            name = " ".join(data.name.split())
            if not data.is_paused and data.promotion_id is None:
                raise AuthError(422, "Affectez une promotion avant d’activer la diffusion.")
            if not name or len(name.casefold()) > 300:
                raise AuthError(422, "Donnez un nom valide au calendrier.")
            if data.promotion_id is not None:
                promotion = await self.db.get(Promotion, data.promotion_id)
                if promotion is None or not promotion.is_active:
                    raise AuthError(422, "Choisissez une promotion active.")
                other = await self.db.scalar(
                    select(TimetableCalendar.id).where(
                        TimetableCalendar.promotion_id == data.promotion_id,
                        TimetableCalendar.is_archived.is_(False),
                        TimetableCalendar.id != identifier if identifier else True,
                    )
                )
                if other is not None:
                    raise AuthError(409, "Cette promotion possède déjà un calendrier actif.")
            other_name = await self.db.scalar(
                select(TimetableCalendar.id).where(
                    TimetableCalendar.name_key == name.casefold(),
                    TimetableCalendar.id != identifier if identifier else True,
                )
            )
            if other_name is not None:
                raise AuthError(
                    409, "Un calendrier porte déjà ce nom, y compris dans les archives."
                )
            row = await self.db.get(TimetableCalendar, identifier) if identifier else None
            if identifier:
                if row is None or row.revision != data.expected_revision:
                    raise AuthError(409, "Le calendrier a changé. Rechargez la liste.")
                if row.is_archived:
                    raise AuthError(409, "Un calendrier archivé est en lecture seule.")
                self.require_live_confirmation(row, data.confirmed_live)
                if row.promotion_id != data.promotion_id and not data.confirmed_assignment:
                    raise AuthError(
                        409, "Confirmez le changement de promotion et de destinataires."
                    )
                if data.settings is not None or data.school_year is not None:
                    raise AuthError(422, "L’année et les horaires initiaux sont immuables.")
            else:
                if data.school_year is None or data.settings is None:
                    raise AuthError(
                        422, "Choisissez une année scolaire et les réglages du calendrier."
                    )
                if data.school_year < current_school_year(self.today()):
                    raise AuthError(422, "Choisissez une année scolaire actuelle ou future.")
                tag = await self.db.get(TimetableSchoolYear, data.school_year)
                if tag is None:
                    raise AuthError(422, "Créez d’abord cette année scolaire dans le catalogue.")
                self.validate_year_bounds(data.school_year, data.settings)
                row = TimetableCalendar()
                self.db.add(row)
                tag.used = True
            row.name, row.name_key, row.promotion_id = name, name.casefold(), data.promotion_id
            row.is_paused = data.is_paused
            row.revision = uuid4().hex
            await self.db.flush()
            if identifier is None:
                self.db.add(
                    TimetableYear(
                        calendar_id=row.id,
                        school_year=data.school_year,
                        starts_on=data.settings.start,
                        ends_on=data.settings.end,
                        settings=data.settings.model_dump(mode="json"),
                        revision=uuid4().hex,
                        updated_at=self.auth.clock(),
                    )
                )
            else:
                for year in await self.repo.years(row.id):
                    year.revision = uuid4().hex
                    year.updated_at = self.auth.clock()
            await record_event(
                self.db,
                "timetable.created" if identifier is None else "timetable.updated",
                actor_user_id=actor.id,
                resource_type="timetable",
                resource_id=row.id,
                data={
                    "calendar_name": row.name,
                    "is_paused": row.is_paused,
                    "promotion_id": row.promotion_id,
                    "school_year": data.school_year,
                },
            )
            return {"id": row.id, "revision": row.revision}

    @staticmethod
    def validate_year_bounds(school_year: int, settings: YearSettings) -> None:
        """Keep a calendar inside its immutable September-to-August academic label."""
        if (
            not date(school_year, 9, 1)
            <= settings.start
            <= settings.end
            <= date(school_year + 1, 8, 31)
        ):
            raise AuthError(422, "Les dates doivent appartenir à l’année scolaire sélectionnée.")
        if not daily_slots(settings):
            raise AuthError(422, "Aucun demi-créneau complet dans cette grille.")

    async def add_room(self, actor: UserContext, name: str) -> dict:
        """Create or reuse a canonical room without duplicating case or whitespace variants."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            name = " ".join(name.split())
            if not name:
                raise AuthError(422, "Donnez un nom à la salle.")
            if len(name.casefold()) > 80:
                raise AuthError(422, "Le nom normalisé de la salle est trop long.")
            row = await self.db.scalar(
                select(TimetableRoom).where(TimetableRoom.name_key == name.casefold())
            )
            if row is None:
                row = TimetableRoom(name=name, name_key=name.casefold(), revision=uuid4().hex)
                self.db.add(row)
                await self.db.flush()
            if not row.is_active:
                row.is_active = True
                row.revision = uuid4().hex
            await record_event(self.db, "timetable.room_saved", actor.id, data={"title": row.name})
            return {"id": row.id, "name": row.name, "revision": row.revision}

    async def save_settings(
        self, actor: UserContext, identifier: int, version: Version, settings: YearSettings
    ) -> dict:
        """Change only dates, vacations and Saturday; retain hidden occurrences and exceptions."""
        async with self.db.begin():
            year = await self._year(identifier, actor, version)
            self.validate_year_bounds(year.school_year, settings)
            previous = YearSettings.model_validate(year.settings)
            for field in (
                "day_start",
                "day_end",
                "session_minutes",
                "breaks",
                "lunch_start",
                "lunch_end",
            ):
                if getattr(previous, field) != getattr(settings, field):
                    raise AuthError(
                        422, "Horaires, pauses, séance et self sont figés après création."
                    )
            year.settings = settings.model_dump(mode="json")
            year.starts_on, year.ends_on = settings.start, settings.end
            return await self._changed(actor, year, "settings_updated")

    async def preview_settings(
        self, actor: UserContext, identifier: int, data: Version, settings: YearSettings
    ) -> dict:
        """Describe hidden and added segments before an administrator confirms date changes."""
        async with self.db.begin():
            await self.authorize(actor, write=True)
            year = await self.db.get(TimetableYear, identifier)
            if year is None:
                raise AuthError(404, "Calendrier introuvable.")
            await self._calendar(year.calendar_id, actor, write=True)
            if year.revision != data.expected_revision:
                raise AuthError(409, "Le calendrier a changé. Rechargez-le.")
            self.validate_year_bounds(year.school_year, settings)
            document = await self.repo.document(year)
            before = {event["id"] for event in occurrences(document)}
            document.settings = settings
            after = {event["id"] for event in occurrences(document)}
            return {"hidden": len(before - after), "added": len(after - before)}

    async def _changed(
        self,
        actor: UserContext,
        year: TimetableYear,
        action: str = "changed",
        **facts: object,
    ) -> dict:
        """Advance the calendar revision and journal a successful mutation in its transaction."""
        year.revision = uuid4().hex
        year.updated_at = self.auth.clock()
        calendar = await self.db.get(TimetableCalendar, year.calendar_id)
        await record_event(
            self.db,
            f"timetable.{action}",
            actor_user_id=actor.id,
            resource_type="timetable",
            resource_id=year.calendar_id,
            data={"calendar_name": calendar.name, "school_year": year.school_year, **facts},
        )
        return {"revision": year.revision}

    async def add_series(
        self, actor: UserContext, identifier: int, version: Version, block: SeriesFields
    ) -> dict:
        """Create one validated series in the live annual calendar."""
        async with self.db.begin():
            year = await self._year(identifier, actor, version)
            calendar = await self.db.get(TimetableCalendar, year.calendar_id)
            document = await self.repo.document(year)
            await self._references(block, calendar)
            changed = apply_event_change(document, None, None, "one", block)
            await self.persist_document(year.id, document, changed)
            return await self._changed(actor, year, "series_created", title=block.title)

    async def persist_document(
        self, year_id: int, before: YearDocument, after: YearDocument
    ) -> None:
        """Persist only changed compact series in bulk; never materialize dated event rows."""
        previous = {item.id: item for item in before.series}
        retained = {item.id for item in after.series}
        changed = [item for item in after.series if previous.get(item.id) != item]
        removed = set(previous) - retained
        if removed:
            await self.db.execute(delete(TimetableSeries).where(TimetableSeries.id.in_(removed)))
        if changed:
            await self.repo.store_series_many(year_id, changed)

    async def edit_occurrence(
        self, actor: UserContext, identifier: int, series_id: str, data: OccurrenceEdit
    ) -> dict:
        """Use the preview's business rules to replace or cancel one or future occurrences."""
        async with self.db.begin():
            year = await self._year(identifier, actor, data)
            document = await self.repo.document(year)
            if data.block:
                calendar = await self.db.get(TimetableCalendar, year.calendar_id)
                await self._references(data.block, calendar)
            changed = apply_event_change(
                document, series_id, data.occurrence, data.scope, data.block
            )
            await self.persist_document(year.id, document, changed)
            source = next((item for item in document.series if item.id == series_id), None)
            return await self._changed(
                actor,
                year,
                "occurrence_updated" if data.block else "occurrence_deleted",
                title=data.block.title if data.block else source.title if source else None,
                occurrence=data.occurrence,
                scope=data.scope,
            )

    async def _decorate(self, events: list[dict], *, include_roles: bool = False) -> list[dict]:
        """Batch labels only for already-authorized events, never a global private directory."""
        if not events:
            return []
        subjects = {
            item.id: item
            for item in await self.db.scalars(
                select(Subject).where(Subject.id.in_({event["subject_id"] for event in events}))
            )
        }
        teachers = {
            item.id: {"name": self._identity(item)["name"], "available": item.status != "disabled"}
            for item in await self.db.scalars(
                select(User).where(
                    User.id.in_(
                        {teacher for event in events for teacher in assigned_teachers(event)}
                    )
                )
            )
        }
        teacher_roles: dict[int, list[str]] = {}
        if include_roles and teachers:
            for user_id, code in await self.db.execute(
                select(UserRole.user_id, Role.code)
                .join(Role)
                .where(UserRole.user_id.in_(teachers), Role.code.in_(["teacher", "kholleur"]))
            ):
                teacher_roles.setdefault(user_id, []).append(code)
        rooms = {
            item.id: item.name
            for item in await self.db.scalars(
                select(TimetableRoom).where(
                    TimetableRoom.id.in_({event["room_id"] for event in events})
                )
            )
        }
        custom_ids = {
            event.get("target_number") for event in events if event.get("target_kind") == "custom"
        }
        custom_names = (
            {
                group.id: group.name
                for group in await self.db.scalars(
                    select(PromotionCustomGroup).where(PromotionCustomGroup.id.in_(custom_ids))
                )
            }
            if custom_ids
            else {}
        )
        return [
            {
                **event,
                **(
                    {
                        "audience_label": custom_names.get(
                            event.get("target_number"), "Groupe personnalisé"
                        )
                    }
                    if event.get("target_kind") == "custom"
                    else {}
                ),
                "title": event["title"] or subjects[event["subject_id"]].name,
                "subject_label": subjects[event["subject_id"]].name
                if event["subject_id"] is not None
                else "Sans matière",
                "color": subjects[event["subject_id"]].color
                if event["subject_id"] is not None
                else "#64748B",
                "teachers": [
                    {
                        "id": identifier,
                        **teachers[identifier],
                        "roles": teacher_roles.get(identifier, []),
                    }
                    for identifier in assigned_teachers(event)
                ],
                "teacher": "\n".join(
                    teachers[identifier]["name"] for identifier in assigned_teachers(event)
                ),
                "teacher_available": all(
                    teachers[identifier]["available"] for identifier in assigned_teachers(event)
                ),
                **(
                    {
                        "teacher_roles": sorted(
                            {
                                role
                                for identifier in assigned_teachers(event)
                                for role in teacher_roles.get(identifier, [])
                            }
                        )
                    }
                    if include_roles
                    else {}
                ),
                "room": rooms[event["room_id"]] if event["room_id"] is not None else "",
            }
            for event in events
        ]

    async def board(
        self,
        actor: UserContext,
        calendar_ids: list[int],
        school_year: int | None,
        preview_year: int | None = None,
        proposal: EventPreview | None = None,
    ) -> dict:
        """Read authorized live events and administrator-only archives or unsaved previews."""
        async with self.db.begin():
            admin = await self.authorize(actor)
            if proposal is not None:
                await self.authorize(actor, write=True)
                preview_row = await self.db.get(TimetableYear, preview_year)
                if preview_row is None:
                    raise AuthError(404, "Calendrier introuvable.")
                calendar_ids = [preview_row.calendar_id]
            read_archives = admin or "teaching.read" in await self.auth.repo.permissions(actor.id)
            allowed = await self.repo.calendars(None if admin else actor.id, archives=read_archives)
            if not set(calendar_ids).issubset({row.id for row in allowed}):
                raise AuthError(404, "Agenda introuvable.")
            selected = [row for row in allowed if row.id in calendar_ids]
            result, years, warnings = [], [], []
            annual_rows = list(
                await self.db.scalars(
                    select(TimetableYear).where(TimetableYear.calendar_id.in_(calendar_ids))
                )
            )
            loaded = await self.repo.documents(annual_rows)
            documents = {}
            for calendar in selected:
                for year, document in loaded.values():
                    if year.calendar_id != calendar.id:
                        continue
                    if school_year is not None and year.school_year != school_year:
                        continue
                    if (
                        not admin
                        and not calendar.is_archived
                        and not year.starts_on <= self.today() <= year.ends_on
                    ):
                        continue
                    if proposal is not None:
                        if calendar.is_archived:
                            raise AuthError(409, "Un calendrier archivé est en lecture seule.")
                        if year.revision != proposal.expected_revision:
                            raise AuthError(409, "Le calendrier a changé. Rechargez-le.")
                        if proposal.block:
                            await self._references(proposal.block, calendar)
                        document = apply_event_change(
                            document,
                            proposal.series_id,
                            proposal.occurrence,
                            proposal.scope,
                            proposal.block,
                        )
                    documents[year.id] = document
                    years.append(
                        {
                            "id": year.id,
                            "calendar_id": calendar.id,
                            "school_year": year.school_year,
                            "settings": document.settings.model_dump(mode="json"),
                            "revision": year.revision if admin else None,
                            "slots": daily_slots(document.settings),
                            "weeks": {
                                day.isoformat(): number
                                for day, number in teaching_weeks(document.settings).items()
                            },
                            "series": [item.model_dump(mode="json") for item in document.series]
                            if admin
                            else [],
                        }
                    )
                    result.extend(
                        {
                            **event,
                            "calendar_id": calendar.id,
                            "promotion_id": calendar.promotion_id,
                            "year_id": year.id,
                            "school_year": year.school_year,
                            "session_minutes": document.settings.session_minutes,
                        }
                        for event in occurrences(document)
                    )

            members: dict[int, dict] = {}
            groups = []
            promotion_ids = {row.promotion_id for row in selected if row.promotion_id}
            if promotion_ids:
                roster = list(
                    await self.db.execute(
                        select(User, UserPromotion.promotion_id)
                        .join(UserPromotion)
                        .where(
                            UserPromotion.promotion_id.in_(promotion_ids),
                            User.is_bootstrap.is_(False),
                            (User.status != "disabled")
                            if read_archives
                            else (User.status == "active"),
                        )
                    )
                )
                role_map: dict[int, list[str]] = {}
                for user_id, code in await self.db.execute(
                    select(UserRole.user_id, Role.code)
                    .join(Role)
                    .where(UserRole.user_id.in_({user.id for user, _ in roster}))
                ):
                    role_map.setdefault(user_id, []).append(code)
                for user, promotion_id in roster:
                    if "user" not in role_map.get(user.id, []):
                        continue
                    if user.id not in members:
                        members[user.id] = {
                            **self._identity(user),
                            "roles": role_map.get(user.id, []),
                            "promotion_ids": [],
                        }
                    members[user.id]["promotion_ids"].append(promotion_id)
                assignments = list(
                    await self.db.scalars(
                        select(PromotionGroupMember).where(
                            PromotionGroupMember.promotion_id.in_(promotion_ids),
                            PromotionGroupMember.user_id.in_(members),
                        )
                    )
                )
                for member in members.values():
                    member["assignments"] = [
                        {
                            "promotion_id": item.promotion_id,
                            "kind": item.kind,
                            "number": item.group_number,
                        }
                        for item in assignments
                        if item.user_id == member["id"]
                    ]
                for group in await self.db.scalars(
                    select(PromotionGroup)
                    .where(PromotionGroup.promotion_id.in_(promotion_ids))
                    .order_by(PromotionGroup.kind, PromotionGroup.number)
                ):
                    groups.append(
                        {
                            "promotion_id": group.promotion_id,
                            "kind": group.kind,
                            "number": group.number,
                            "student_ids": [
                                item.user_id
                                for item in assignments
                                if item.promotion_id == group.promotion_id
                                and item.kind == group.kind
                                and item.group_number == group.number
                            ],
                        }
                    )
            if promotion_ids:
                custom_members = list(
                    await self.db.scalars(
                        select(PromotionCustomGroupMember).where(
                            PromotionCustomGroupMember.promotion_id.in_(promotion_ids),
                            PromotionCustomGroupMember.user_id.in_(members),
                        )
                    )
                )
                for group in await self.db.scalars(
                    select(PromotionCustomGroup)
                    .where(
                        PromotionCustomGroup.promotion_id.in_(promotion_ids),
                        True if read_archives else PromotionCustomGroup.is_active.is_(True),
                    )
                    .order_by(PromotionCustomGroup.name)
                ):
                    student_ids = [
                        item.user_id for item in custom_members if item.group_id == group.id
                    ]
                    groups.append(
                        {
                            "promotion_id": group.promotion_id,
                            "kind": "custom",
                            "number": group.id,
                            "name": group.name,
                            "is_active": group.is_active,
                            "student_ids": student_ids,
                        }
                    )
                    for pupil in student_ids:
                        members[pupil]["assignments"].append(
                            {
                                "promotion_id": group.promotion_id,
                                "kind": "custom",
                                "number": group.id,
                            }
                        )
            if not admin:
                result = [
                    event
                    for event in result
                    if event.get("target_kind", "promotion") == "promotion"
                    or any(
                        student_receives(
                            event,
                            member["id"],
                            {
                                (item["kind"], item["number"])
                                for item in member.get("assignments", [])
                                if item["promotion_id"] == event["promotion_id"]
                            },
                        )
                        for member in members.values()
                        if event["promotion_id"] in member["promotion_ids"]
                    )
                ]
            events = await self._decorate(result, include_roles=True)
            warnings.extend(self._conflicts(events, groups, self.today()))
            from app.services.teacher_availability import (
                availability_settings,
                availability_warnings,
                effective_ranges,
            )

            explicit = {
                (row.user_id, row.school_year): row.ranges
                for row in await self.db.scalars(
                    select(TeacherAvailability).where(
                        TeacherAvailability.school_year.in_({item["school_year"] for item in years})
                    )
                )
            }
            availability = [
                {
                    "teacher_id": teacher,
                    "school_year": number,
                    "ranges": effective_ranges(
                        explicit.get((teacher, number)), availability_settings(number)
                    ),
                }
                for teacher, number in (
                    set(explicit)
                    | {
                        (teacher, event["school_year"])
                        for event in events
                        for teacher in assigned_teachers(event)
                    }
                )
                if teacher is not None
            ]

            warnings.extend(
                availability_warnings(
                    events,
                    {
                        (item["teacher_id"], item["school_year"]): item["ranges"]
                        for item in availability
                    },
                    self.today(),
                )
            )
            issues = [
                {
                    "code": f"promotion-{calendar.id}",
                    "severity": "critical",
                    "message": (
                        f"{calendar.name} : aucune promotion affectée. "
                        "La sauvegarde reste possible ; "
                        "affectez une promotion pour diffuser cet agenda."
                    ),
                }
                for calendar in selected
                if calendar.promotion_id is None
            ]
            unavailable = {
                event["teacher_id"]: event["teacher"]
                for event in individual_assignments(events)
                if not event["teacher_available"]
                and datetime.fromisoformat(event["end"]) > self.auth.clock()
            }
            issues.extend(
                {
                    "code": f"teacher-{identifier}",
                    "teacher_id": identifier,
                    "severity": "warning",
                    "message": (
                        f"{name} est archivé et reste affecté à des séances futures. "
                        "Remplacez cet enseignant dans les événements concernés."
                    ),
                }
                for identifier, name in unavailable.items()
            )

            commitments = (
                await self._teacher_commitments(
                    set(calendar_ids),
                    {item["school_year"] for item in years},
                    admin,
                    None
                    if admin
                    else {teacher for event in events for teacher in assigned_teachers(event)},
                )
                if years
                else []
            )
            from app.services.timetable_diagnostics import annual_diagnostics

            for item in years:
                related = [event for event in events if event["year_id"] == item["id"]]
                item["hours"], diagnostics = annual_diagnostics(
                    related,
                    documents[item["id"]].settings,
                    list(members.values()),
                    groups,
                    next(
                        calendar.promotion_id
                        for calendar in selected
                        if calendar.id == item["calendar_id"]
                    ),
                    self.today(),
                    documents[item["id"]].series,
                )
                issues.extend(diagnostics)
            return {
                "teacher_commitments": commitments,
                "years": years,
                "calendars": [
                    {
                        "id": calendar.id,
                        "name": calendar.name,
                        "promotion_id": calendar.promotion_id,
                        "revision": calendar.revision if admin else None,
                        "is_paused": calendar.is_paused,
                        "is_archived": calendar.is_archived,
                    }
                    for calendar in selected
                ],
                "events": events,
                "members": list(members.values()),
                "groups": groups,
                "warnings": list(dict.fromkeys(warnings))[:100],
                "availability": availability,
                "issues": issues,
            }

    async def _teacher_commitments(
        self,
        calendar_ids: set[int],
        school_years: set[int],
        include_private: bool,
        teacher_ids: set[int] | None,
    ) -> list[dict]:
        """Expose only external teacher booking identities and times for conflict previews.

        Parameters
        ----------
        calendar_ids, school_years
            Calendars already authorized by the board and their selected school years.
        include_private
            Include private preparations only for an authorized administrator.
        teacher_ids
            Restrict staff reads to teachers on their authorized board; administrators may
            preview any newly selected teacher without fetching private pupil recipients.

        Returns
        -------
        list[dict]
            Future booking times and calendar references, without titles, rooms or pupil data.
        """
        if teacher_ids == set():
            return []
        sources = [
            item
            for year in sorted(school_years)
            for item in await self.repo.teaching_documents(year, include_private=include_private)
            if item[0].calendar_id not in calendar_ids
        ]
        if not sources:
            return []
        names = {
            identifier: name
            for identifier, name in await self.db.execute(
                select(TimetableCalendar.id, TimetableCalendar.name).where(
                    TimetableCalendar.id.in_({year.calendar_id for year, _ in sources})
                )
            )
        }
        result = []
        today = self.today().isoformat()
        for year, document in sources:
            if teacher_ids is not None:
                document.series = [
                    source
                    for source in document.series
                    if set(source.teacher_ids).intersection(teacher_ids)
                    or any(
                        block and set(block.teacher_ids).intersection(teacher_ids)
                        for block in source.exceptions.values()
                    )
                ]
            for event in individual_assignments(occurrences(document)):
                if event["teacher_id"] is None or event["start"][:10] < today:
                    continue
                if teacher_ids is not None and event["teacher_id"] not in teacher_ids:
                    continue
                result.append(
                    {
                        **{
                            field: event[field]
                            for field in (
                                "series_id",
                                "conflict_key",
                                "source_date",
                                "teacher_id",
                                "start",
                                "end",
                            )
                        },
                        "calendar_id": year.calendar_id,
                        "year_id": year.id,
                        "calendar_label": names[year.calendar_id],
                    }
                )
        return result

    @staticmethod
    def _conflicts(
        events: list[dict], groups: list[dict] | None = None, today: date | None = None
    ) -> list[str]:
        """Warn about overlapping class, teacher and room use without blocking edits."""
        warnings = {}
        active = []
        audiences = {
            (group["promotion_id"], group["kind"], group["number"]): set(group["student_ids"])
            for group in groups or []
        }
        for event in sorted(events, key=lambda item: item["start"]):
            if (
                today is not None
                and datetime.fromisoformat(event["start"]).astimezone(PARIS).date() < today
            ):
                continue
            active = [other for other in active if other["end"] > event["start"]]
            room_halves = sum(
                other.get("room_id") == event.get("room_id")
                and other.get("target_kind") == "halves"
                for other in active
            )
            for other in active:
                for field, label in (
                    ("teacher_id", "enseignant"),
                    ("room_id", "salle"),
                    ("promotion_id", "classe"),
                ):
                    if field == "promotion_id" and not audiences_overlap(event, other, audiences):
                        continue
                    if (
                        field == "room_id"
                        and event.get("target_kind") == other.get("target_kind") == "halves"
                        and room_halves < 2
                    ):
                        continue
                    same_resource = (
                        bool(set(assigned_teachers(event)).intersection(assigned_teachers(other)))
                        if field == "teacher_id"
                        else event.get(field) is not None and event[field] == other[field]
                    )
                    if field == "promotion_id" and event.get("calendar_id") is not None:
                        same_resource = same_resource or event["calendar_id"] == other.get(
                            "calendar_id"
                        )
                    if same_resource:
                        identities = tuple(
                            sorted(
                                (
                                    str(
                                        event.get(
                                            "conflict_key", event.get("series_id", event.get("id"))
                                        )
                                    ),
                                    str(
                                        other.get(
                                            "conflict_key", other.get("series_id", other.get("id"))
                                        )
                                    ),
                                )
                            )
                        )
                        resources = (
                            set(assigned_teachers(event)).intersection(assigned_teachers(other))
                            if field == "teacher_id"
                            else [event[field]]
                        )
                        for identifier in resources:
                            teacher_name = (
                                next(
                                    (
                                        item["name"]
                                        for item in event.get("teachers", [])
                                        if item["id"] == identifier
                                    ),
                                    "",
                                )
                                if field == "teacher_id"
                                else ""
                            )
                            warnings.setdefault(
                                (field, identifier, identities),
                                f"Conflit de {label} le {event['start'][:10]} : "
                                f"{other['title']} / {event['title']}."
                                + (f" ({teacher_name})" if teacher_name else ""),
                            )
            active.append(event)
        return sorted(warnings.values())[:100]

    async def feed(self, token: str, *, outcome: dict | None = None) -> bytes:
        """Authorize by verifier and current membership, exporting only current publications."""
        calendar = Calendar()
        calendar.add("prodid", "-//Sophikron//Emploi du temps//FR")
        calendar.add("version", "2.0")
        if outcome is not None:
            outcome["ics_outcome"] = "refused"
        if not re.fullmatch(r"(?:[A-Za-z0-9_-]{43}|[A-Za-z0-9_-]{86})", token):
            return calendar.to_ical()
        async with self.db.begin():
            row = await self.db.scalar(
                select(TimetableSubscription).where(
                    TimetableSubscription.token_hash == token_digest(token)
                )
            )
            user = await self.db.get(User, row.user_id) if row else None
            if (
                user is None
                or not self.auth._active(user, self.auth.clock())
                or user.is_bootstrap
                or user.login_count == 0
                or row.revoked_at is not None
            ):
                return calendar.to_ical()
            now = self.auth.clock()
            limit = self.auth.settings.calendar_feed_limit_per_minute
            attempts, expiry = await self.auth.repo.reserve_attempt(
                self.auth.cipher.lookup("rate:calendar-feed", row.token_hash.hex()),
                limit,
                now,
                60,
            )
            if attempts > limit:
                raise AuthError(
                    429,
                    "Trop de demandes. Réessayez dans une minute.",
                    max(1, math.ceil((expiry - now).total_seconds())),
                )
            roles = await self.auth.repo.roles(user.id)
            promotions = await student_promotions(self.db, user.id)
            promotion_names = {promotion.id: promotion.identifier for promotion in promotions}
            if "user" in roles:
                if not promotions:
                    return calendar.to_ical()
                name = " / ".join(dict.fromkeys(promotion.identifier for promotion in promotions))
            else:
                settings = await self.db.get(SiteSettings, 1)
                name = settings.name if settings is not None else "Sophikron"
            calendar.add("x-wr-calname", name)
            from app.services.timetable_lifecycle import rollover

            # Acquire a possible lifecycle lock before the subscription update lock.
            await rollover(self.db, self.today())
            calendars = {
                calendar.id: calendar
                for calendar in await self.repo.calendars(
                    user.id,
                    include_undiffused="user" not in roles,
                    school_year=current_school_year(self.today()),
                )
            }
            if not calendars:
                return calendar.to_ical()
            # Also recheck the verifier in case an administrator just rotated or revoked it.
            requested = await self.db.execute(
                update(TimetableSubscription)
                .where(
                    TimetableSubscription.user_id == user.id,
                    TimetableSubscription.token_hash == token_digest(token),
                    TimetableSubscription.revoked_at.is_(None),
                )
                .values(last_requested_at=self.auth.clock())
            )
            if requested.rowcount == 0:
                return calendar.to_ical()
            events = []
            if calendars:
                assignments: dict[int, set[tuple[str, int]]] = {}
                promotion_ids = {calendar.promotion_id for calendar in calendars.values()}
                for promotion_id, kind, number in await self.db.execute(
                    select(
                        PromotionGroupMember.promotion_id,
                        PromotionGroupMember.kind,
                        PromotionGroupMember.group_number,
                    )
                    .where(
                        PromotionGroupMember.user_id == user.id,
                        PromotionGroupMember.promotion_id.in_(promotion_ids),
                    )
                    .union_all(
                        select(
                            PromotionCustomGroupMember.promotion_id,
                            literal("custom"),
                            PromotionCustomGroupMember.group_id,
                        ).where(
                            PromotionCustomGroupMember.user_id == user.id,
                            PromotionCustomGroupMember.promotion_id.in_(promotion_ids),
                        )
                    )
                ):
                    assignments.setdefault(promotion_id, set()).add((kind, number))
                annual_rows = list(
                    await self.db.scalars(
                        select(TimetableYear).where(
                            TimetableYear.calendar_id.in_(calendars),
                            TimetableYear.school_year == current_school_year(self.today()),
                        )
                    )
                )
                for year, document in (await self.repo.documents(annual_rows)).values():
                    memberships = assignments.get(calendars[year.calendar_id].promotion_id, set())
                    events.extend(
                        {
                            **event,
                            "updated_at": year.updated_at,
                            "promotion_label": promotion_names.get(
                                calendars[year.calendar_id].promotion_id, ""
                            ),
                        }
                        for event in occurrences(document)
                        if ("user" in roles and student_receives(event, user.id, memberships))
                        or ("user" not in roles and user.id in assigned_teachers(event))
                    )

            events = await self._decorate(events)
            for item in events:
                event = Event()
                event.add("uid", item["id"] + "@sophikron")
                event.add(
                    "dtstamp", item["updated_at"] or datetime(2000, 1, 1, tzinfo=timezone.utc)
                )
                event.add("last-modified", item["updated_at"])
                event.add("dtstart", datetime.fromisoformat(item["start"]).astimezone(timezone.utc))
                event.add("dtend", datetime.fromisoformat(item["end"]).astimezone(timezone.utc))
                summary, notes = calendar_event_text(item)
                event.add("summary", summary)
                if item["room"]:
                    event.add("location", item["room"])
                event.add("description", notes)
                calendar.add_component(event)
            result = calendar.to_ical()
            from sqlalchemy.dialects.postgresql import insert

            from app.models.statistics import CalendarUsageTotal

            statement = insert(CalendarUsageTotal).values(id=1, requests=1)
            await self.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[CalendarUsageTotal.id],
                    set_={"requests": CalendarUsageTotal.requests + 1},
                )
            )
        if outcome is not None:
            outcome["ics_outcome"] = "success"
        return result


def calendar_event_text(item: dict) -> tuple[str, str]:
    """Return an ICS title and audience-first notes from already-authorized labels."""
    kind = {"course": "Cours", "td": "TD", "tp": "TP", "kholle": "Khôlle"}[item["kind"]]
    subject = item["subject_label"] if item["subject_id"] is not None else item["title"]
    target = item.get("target_kind", "promotion")
    number = item.get("target_number")
    audience = {
        "promotion": "Classe entière",
        "halves": "Demi-groupe",
        "thirds": "Tiers de groupe",
        "kholles": "Groupe de khôlle",
        "custom": item.get("audience_label") or "Groupe personnalisé",
        "student": "Séance individuelle",
    }[target]
    if number and target in {"halves", "thirds"}:
        audience += " " + chr((64 if target == "halves" else 87) + number)
    elif number and target == "kholles":
        audience += f" {number:03d}"
    audience = " — ".join(filter(None, [item.get("promotion_label"), audience]))
    return f"{kind} - {subject.upper()}", "\n".join(filter(None, [audience, item["teacher"]]))


def student_receives(event: dict, user_id: int, memberships: set[tuple[str, int]]) -> bool:
    """Match one personal export to current promotion, group or individual membership."""
    kind = event.get("target_kind", "promotion")
    if kind == "promotion":
        return True
    if kind == "student":
        return event.get("target_user_id") == user_id
    return (kind, event.get("target_number")) in memberships


def audiences_overlap(left: dict, right: dict, groups: dict[tuple, set[int]]) -> bool:
    """Compare current recipients before reporting a class scheduling conflict.

    Parameters
    ----------
    left, right
        Authorized event dictionaries from the same timetable board.
    groups
        Current group membership sets keyed by promotion, kind and number.

    Returns
    -------
    bool
        Whether the audiences intersect, conservatively true for unknown cross-partitions.
    """
    left_kind, right_kind = (
        left.get("target_kind", "promotion"),
        right.get("target_kind", "promotion"),
    )
    if "promotion" in {left_kind, right_kind}:
        return True
    if left_kind == right_kind and left_kind != "custom":
        field = "target_user_id" if left_kind == "student" else "target_number"
        return left.get(field) == right.get(field)

    def recipients(event: dict, kind: str) -> set[int] | None:
        """Resolve known recipient sets without treating an unknown group as an empty class."""
        if kind == "student":
            return {event["target_user_id"]}
        return groups.get((event.get("promotion_id"), kind, event.get("target_number")))

    first, second = recipients(left, left_kind), recipients(right, right_kind)
    return bool(first & second) if first is not None and second is not None else True
