"""Private timetable authorization, draft publication and personal calendar feeds."""

import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from icalendar import Calendar, Event
from sqlalchemy import delete, select

from app.core.security import new_token, token_digest
from app.models import (
    Promotion,
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
    TimetableTemplateVersion,
    TimetableYear,
    User,
    UserPromotion,
    UserRole,
)
from app.repositories.timetable import TimetableRepository
from app.schemas.timetable import (
    CalendarSave,
    OccurrenceEdit,
    SeriesData,
    SeriesFields,
    SessionFields,
    Version,
    YearCreate,
    YearDocument,
    YearSettings,
)
from app.services.activity import record_event
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.timetable_engine import (
    PARIS,
    cycle_warnings,
    daily_slots,
    occurrences,
    series_dates,
    teaching_day,
    teaching_weeks,
    validate_series,
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
        return admin

    async def _calendar(
        self, identifier: int, actor: UserContext, *, write: bool
    ) -> TimetableCalendar:
        """Hide unrelated calendars after checking current staff scope."""
        admin = await self.authorize(actor, write=write)
        calendars = await self.repo.calendars(None if admin else actor.id)
        calendar = next((row for row in calendars if row.id == identifier), None)
        if calendar is None:
            raise AuthError(404, "Agenda introuvable.")
        return calendar

    async def _year(self, identifier: int, actor: UserContext, version: Version) -> TimetableYear:
        """Lock drafts after authorization and reject stale editing revisions."""
        await self.auth._lifecycle_lock()
        await self.authorize(actor, write=True)
        row = await self.db.scalar(
            select(TimetableYear).where(TimetableYear.id == identifier).with_for_update()
        )
        if row is None:
            raise AuthError(404, "Année scolaire introuvable.")
        calendar = await self.db.get(TimetableCalendar, row.calendar_id)
        if calendar is None or calendar.is_deleted:
            raise AuthError(404, "Agenda introuvable.")
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
            else:
                valid = await self.db.get(
                    PromotionGroup, (calendar.promotion_id, block.target_kind, block.target_number)
                )
            if not valid:
                raise AuthError(
                    422, "Ce destinataire n’appartient plus à la promotion de l’agenda."
                )

    async def common_years(self) -> list[dict]:
        """Describe common settings without discarding conflicting legacy configurations."""
        rows = list(
            await self.db.scalars(
                select(TimetableSchoolYear).order_by(TimetableSchoolYear.school_year.desc())
            )
        )
        result = []
        for row in rows:
            alternatives = []
            if row.settings is None:
                for year, name in await self.db.execute(
                    select(TimetableYear, TimetableCalendar.name)
                    .join(TimetableCalendar)
                    .where(
                        TimetableYear.school_year == row.school_year,
                        TimetableCalendar.is_deleted.is_(False),
                    )
                ):
                    alternatives.append({"name": name, "settings": year.settings})
            result.append(
                {
                    "school_year": row.school_year,
                    "settings": row.settings,
                    "revision": row.revision,
                    "alternatives": alternatives,
                }
            )
        return result

    async def catalog(self, actor: UserContext) -> dict:
        """Return minimal calendar and member metadata inside the caller's current scope."""
        async with self.db.begin():
            admin = await self.authorize(actor)
            calendars = await self.repo.calendars(None if admin else actor.id)
            items = []
            for calendar in calendars:
                years = await self.repo.years(calendar.id)
                visible = []
                for year in years:
                    published = (
                        YearDocument.model_validate(year.published) if year.published else None
                    )
                    if admin or (
                        published
                        and published.settings.start <= self.today() <= published.settings.end
                    ):
                        visible.append(
                            {
                                "id": year.id,
                                "school_year": year.school_year,
                                "revision": year.revision if admin else None,
                            }
                        )
                items.append(
                    {
                        "id": calendar.id,
                        "name": calendar.name,
                        "promotion_id": calendar.promotion_id,
                        "revision": calendar.revision if admin else None,
                        "is_paused": calendar.is_paused,
                        "years": visible,
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
                            User.status != "disabled",
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
        """Create or reassign a reusable agenda under the account lifecycle lock."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            if not data.name.strip():
                raise AuthError(422, "Donnez un nom à l’agenda.")
            if data.promotion_id is not None:
                promotion = await self.db.get(Promotion, data.promotion_id)
                if promotion is None or not promotion.is_active:
                    raise AuthError(422, "Choisissez une promotion active.")
            row = await self.db.get(TimetableCalendar, identifier) if identifier else None
            if identifier and (
                row is None or row.is_deleted or row.revision != data.expected_revision
            ):
                raise AuthError(409, "L’agenda a changé ou n’existe plus.")
            if row is None:
                row = TimetableCalendar()
                self.db.add(row)
            row.name, row.promotion_id = data.name.strip(), data.promotion_id
            row.is_paused = data.is_paused
            row.revision = uuid4().hex
            await self.db.flush()
            await record_event(
                self.db,
                "timetable.changed",
                actor_user_id=actor.id,
                resource_type="timetable",
                resource_id=row.id,
            )
            return {"id": row.id, "revision": row.revision}

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
            return {"id": row.id, "name": row.name, "revision": row.revision}

    async def create_year(self, actor: UserContext, calendar_id: int, data: YearCreate) -> dict:
        """Prepare an annual draft and automatically reuse recurring patterns without exceptions."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            calendar = await self._calendar(calendar_id, actor, write=True)
            years = await self.repo.years(calendar.id)
            if any(row.school_year == data.settings.start.year for row in years):
                raise AuthError(409, "Cette année scolaire existe déjà dans cet agenda.")
            if not daily_slots(data.settings):
                raise AuthError(422, "Aucun demi-créneau complet dans cette grille.")
            shared = await self.db.get(TimetableSchoolYear, data.settings.start.year)
            if shared and shared.settings != data.settings.model_dump(mode="json"):
                raise AuthError(409, "Utilisez les réglages communs de cette année scolaire.")
            if shared is None:
                shared = TimetableSchoolYear(
                    school_year=data.settings.start.year,
                    settings=data.settings.model_dump(mode="json"),
                    revision=uuid4().hex,
                )
                self.db.add(shared)
                await self.db.flush()
            year = TimetableYear(
                calendar_id=calendar.id,
                school_year=data.settings.start.year,
                starts_on=data.settings.start,
                ends_on=data.settings.end,
                settings=data.settings.model_dump(mode="json"),
                revision=uuid4().hex,
            )
            self.db.add(year)
            await self.db.flush()
            previous = next((row for row in years if row.school_year < year.school_year), None)
            skipped = 0
            if data.copy_previous and previous:
                document = await self.repo.document(previous)
                latest = await self.db.scalar(
                    select(TimetableTemplateVersion)
                    .where(TimetableTemplateVersion.year_id == previous.id)
                    .order_by(TimetableTemplateVersion.number.desc())
                    .limit(1)
                )
                if latest:
                    from app.schemas.timetable import TemplateBlock
                    from app.services.timetable_templates import template_series

                    for value in latest.blocks:
                        block = TemplateBlock.model_validate(value)
                        if block.kind == "kholle" or block.target_kind not in {
                            "promotion",
                            "halves",
                            "thirds",
                        }:
                            skipped += 1
                            continue
                        block.key = uuid4().hex
                        copied = template_series(block, data.settings, data.settings.start)
                        if copied:
                            validate_series(copied, data.settings)
                            await self.repo.store_series(year.id, copied)
                    document.series = []
                old_weeks = teaching_weeks(document.settings)
                new_weeks = list(teaching_weeks(data.settings))
                for source in document.series:
                    if not source.interval:
                        continue
                    monday = source.starts_on - timedelta(days=source.starts_on.weekday())
                    index = old_weeks.get(monday, 1) - 1
                    if index >= len(new_weeks):
                        skipped += 1
                        continue
                    first = new_weeks[index] + timedelta(days=source.starts_on.weekday())
                    while first <= data.settings.end and not teaching_day(first, data.settings):
                        first += timedelta(weeks=source.interval)
                    if first > data.settings.end:
                        skipped += 1
                        continue
                    until = data.settings.end if source.until else None
                    if source.until and source.until < document.settings.end:
                        stop_index = max(0, sum(day <= source.until for day in old_weeks) - 1)
                        until = min(
                            new_weeks[min(stop_index, len(new_weeks) - 1)] + timedelta(days=6),
                            data.settings.end,
                        )
                    identifier = uuid4().hex
                    copied = source.model_copy(
                        update={
                            "id": identifier,
                            "lineage": identifier,
                            "starts_on": first,
                            "until": until,
                            "exceptions": {},
                        }
                    )
                    validate_series(copied, data.settings)
                    await self.repo.store_series(year.id, copied)
            await record_event(
                self.db,
                "timetable.changed",
                actor_user_id=actor.id,
                resource_type="timetable",
                resource_id=calendar.id,
            )
            return {"id": year.id, "revision": year.revision, "skipped": skipped}

    async def save_settings(
        self, actor: UserContext, identifier: int, version: Version, settings: YearSettings
    ) -> dict:
        """Validate every retained block before accepting a changed draft grid or holiday set."""
        async with self.db.begin():
            year = await self._year(identifier, actor, version)
            if settings.start.year != year.school_year or not daily_slots(settings):
                raise AuthError(422, "Gardez l’année de rentrée et au moins un demi-créneau.")
            affected = list(
                await self.db.scalars(
                    select(TimetableYear).where(TimetableYear.school_year == year.school_year)
                )
            )
            for item in affected:
                document = await self.repo.document(item)
                for series in document.series:
                    validate_series(series, settings)
            shared = await self.db.get(TimetableSchoolYear, year.school_year)
            shared.settings, shared.revision = settings.model_dump(mode="json"), uuid4().hex
            for item in affected:
                item.settings = shared.settings
                item.starts_on, item.ends_on = settings.start, settings.end
                await self._changed(actor, item)
            return {"revision": year.revision}

    async def _changed(self, actor: UserContext, year: TimetableYear) -> dict:
        """Advance the draft revision and journal a successful mutation in its transaction."""
        year.revision = uuid4().hex
        await record_event(
            self.db,
            "timetable.changed",
            actor_user_id=actor.id,
            resource_type="timetable",
            resource_id=year.calendar_id,
        )
        return {"revision": year.revision}

    async def add_series(
        self, actor: UserContext, identifier: int, version: Version, block: SeriesFields
    ) -> dict:
        """Create one validated series without modifying the published snapshot."""
        async with self.db.begin():
            year = await self._year(identifier, actor, version)
            calendar = await self.db.get(TimetableCalendar, year.calendar_id)
            document = await self.repo.document(year)
            if len(document.series) >= 5000:
                raise AuthError(422, "Limite de 5000 séries par année atteinte.")
            await self._references(block, calendar)
            key = uuid4().hex
            series = SeriesData(**block.model_dump(), id=key, lineage=key)
            validate_series(series, document.settings)
            await self.repo.store_series(year.id, series)
            return await self._changed(actor, year)

    async def edit_occurrence(
        self, actor: UserContext, identifier: int, series_id: str, data: OccurrenceEdit
    ) -> dict:
        """Replace/cancel one occurrence or split a series, retaining independent exceptions."""
        async with self.db.begin():
            year = await self._year(identifier, actor, data)
            document = await self.repo.document(year)
            source = next((item for item in document.series if item.id == series_id), None)
            if source is None or data.occurrence not in series_dates(source, document.settings):
                raise AuthError(404, "Occurrence introuvable.")
            if source.template_key is not None and data.scope != "one":
                raise AuthError(
                    422,
                    "Modifiez cette occurrence seulement ou ouvrez l’édition de la semaine type.",
                )
            if data.block:
                calendar = await self.db.get(TimetableCalendar, year.calendar_id)
                await self._references(data.block, calendar)
            if data.scope == "one":
                replacement = data.block
                exceptions = {**source.exceptions, data.occurrence: replacement}
                if len(exceptions) > 100:
                    raise AuthError(422, "Limite de 100 exceptions par série atteinte.")
                source = source.model_copy(update={"exceptions": exceptions})
                validate_series(source, document.settings)
                await self.repo.store_series(year.id, source)
            else:
                future = {
                    day: value for day, value in source.exceptions.items() if day >= data.occurrence
                }
                source.exceptions = {
                    day: value for day, value in source.exceptions.items() if day < data.occurrence
                }
                if data.block:
                    key = uuid4().hex
                    new = SeriesData(
                        **data.block.model_dump(),
                        id=key,
                        lineage=source.lineage,
                        exceptions=future,
                        template_key=source.template_key,
                        uid_date=source.uid_date if not data.block.interval else None,
                        first_uid=source.first_uid
                        if data.block.starts_on == source.starts_on
                        else None,
                    )
                    validate_series(new, document.settings)
                    if len(document.series) >= 5000:
                        raise AuthError(422, "Limite de 5000 séries par année atteinte.")
                    await self.repo.store_series(year.id, new)
                if data.occurrence == source.starts_on:
                    await self.db.execute(
                        delete(TimetableSeries).where(TimetableSeries.id == source.id)
                    )
                else:
                    source.until = data.occurrence - timedelta(days=1)
                    await self.repo.store_series(year.id, source)
            return await self._changed(actor, year)

    async def publish(self, actor: UserContext, identifier: int, version: Version) -> dict:
        """Atomically replace only this year's public-to-members snapshot after validation."""
        async with self.db.begin():
            year = await self._year(identifier, actor, version)
            document = await self.repo.document(year)
            calendar = await self.db.get(TimetableCalendar, year.calendar_id)
            if calendar.is_paused or calendar.is_deleted:
                raise AuthError(409, "Cet agenda est en pause. Réactivez-le pour publier.")
            if calendar.promotion_id is None:
                raise AuthError(422, "Affectez cet agenda à une promotion avant publication.")
            for other in await self.repo.years(calendar.id):
                if other.id == year.id or other.published is None:
                    continue
                previous = YearDocument.model_validate(other.published).settings
                if (
                    previous.start <= document.settings.end
                    and document.settings.start <= previous.end
                ):
                    raise AuthError(
                        422, "Deux années publiées du même agenda ne peuvent se chevaucher."
                    )
            for series in document.series:
                validate_series(series, document.settings)
                dates = series_dates(series, document.settings)
                await self._references(
                    series,
                    calendar,
                    historical=bool(dates and max(dates) < self.today()),
                    allow_unavailable_teacher=True,
                )
                for replacement in series.exceptions.values():
                    if replacement:
                        await self._references(
                            replacement,
                            calendar,
                            historical=replacement.starts_on < self.today(),
                            allow_unavailable_teacher=True,
                        )
            year.published = document.model_dump(mode="json")
            year.published_revision = year.revision
            year.published_at = self.auth.clock()
            await record_event(
                self.db,
                "timetable.published",
                actor_user_id=actor.id,
                resource_type="timetable",
                resource_id=year.calendar_id,
            )
            return {"revision": year.revision}

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
                select(User).where(User.id.in_({event["teacher_id"] for event in events}))
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
        return [
            {
                **event,
                "title": event["title"] or subjects[event["subject_id"]].name,
                "color": subjects[event["subject_id"]].color
                if event["subject_id"] is not None
                else "#64748B",
                "teacher": teachers[event["teacher_id"]]["name"]
                if event["teacher_id"] is not None
                else "",
                "teacher_available": teachers[event["teacher_id"]]["available"]
                if event["teacher_id"] is not None
                else True,
                **(
                    {"teacher_roles": sorted(teacher_roles.get(event["teacher_id"], []))}
                    if include_roles
                    else {}
                ),
                "room": rooms[event["room_id"]] if event["room_id"] is not None else "",
            }
            for event in events
        ]

    async def board(
        self, actor: UserContext, calendar_ids: list[int], school_year: int | None, draft: bool
    ) -> dict:
        """Read complete authorized promotions; staff receive only current published years."""
        async with self.db.begin():
            admin = await self.authorize(actor)
            if draft and not admin:
                raise AuthError(403, "Les brouillons sont réservés à l’administration.")
            allowed = await self.repo.calendars(None if admin else actor.id)
            if not set(calendar_ids).issubset({row.id for row in allowed}):
                raise AuthError(404, "Agenda introuvable.")
            selected = [row for row in allowed if row.id in calendar_ids]
            result, years, warnings = [], [], []
            documents = {}
            for calendar in selected:
                candidates = await self.repo.years(calendar.id)
                for year in candidates:
                    document = (
                        await self.repo.document(year)
                        if draft
                        else (
                            YearDocument.model_validate(year.published) if year.published else None
                        )
                    )
                    if document is None:
                        continue
                    if admin:
                        if school_year is not None and year.school_year != school_year:
                            continue
                    elif not document.settings.start <= self.today() <= document.settings.end:
                        continue
                    documents[year.id] = document
                    years.append(
                        {
                            "id": year.id,
                            "calendar_id": calendar.id,
                            "school_year": year.school_year,
                            "settings": document.settings.model_dump(mode="json"),
                            "revision": year.revision if admin else None,
                            "published_revision": year.published_revision if admin else None,
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
                    warnings.extend(cycle_warnings(document))
                    result.extend(
                        {
                            **event,
                            "calendar_id": calendar.id,
                            "promotion_id": calendar.promotion_id,
                            "year_id": year.id,
                            "school_year": year.school_year,
                        }
                        for event in occurrences(document)
                    )
                    break
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
                            User.status != "disabled",
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
            from app.services.teacher_availability import availability_warnings, effective_ranges

            settings_by_year = {
                item["school_year"]: YearSettings.model_validate(item["settings"]) for item in years
            }
            availability = [
                {
                    "teacher_id": row.user_id,
                    "school_year": row.school_year,
                    "ranges": effective_ranges(row.ranges, settings_by_year[row.school_year]),
                }
                for row in await self.db.scalars(
                    select(TeacherAvailability).where(
                        TeacherAvailability.user_id.in_({event["teacher_id"] for event in events}),
                        TeacherAvailability.school_year.in_(
                            {item["school_year"] for item in years}
                        ),
                    )
                )
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
                for event in events
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
                        "Remplacez cet enseignant dans la semaine type ou les événements concernés."
                    ),
                }
                for identifier, name in unavailable.items()
            )
            if years:
                from app.services.timetable_templates import template_blocks

                latest = await self.repo.latest_templates(set(documents)) if draft else {}
                for item in years:
                    version = latest.get(item["id"])
                    item["template_blocks"] = (
                        [
                            block
                            for block in version.blocks
                            if block.get("kind") != "kholle"
                            and block.get("target_kind", "promotion")
                            in {"promotion", "halves", "thirds"}
                        ]
                        if version
                        else [
                            block.model_dump(mode="json")
                            for block in template_blocks(
                                documents[item["id"]],
                                max(documents[item["id"]].settings.start, self.today()),
                            )
                        ]
                    )
            commitments = (
                await self._teacher_commitments(
                    set(calendar_ids),
                    {item["school_year"] for item in years},
                    draft,
                    None
                    if admin
                    else {
                        event["teacher_id"] for event in events if event["teacher_id"] is not None
                    },
                )
                if years
                else []
            )
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
        draft: bool,
        teacher_ids: set[int] | None,
    ) -> list[dict]:
        """Expose only external teacher booking identities and times for conflict previews.

        Parameters
        ----------
        calendar_ids, school_years
            Calendars already authorized by the board and their selected school years.
        draft
            Use preparations only for an authorized administrator requesting drafts.
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
            for item in await self.repo.teaching_documents(year, draft=draft)
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
                    if source.teacher_id in teacher_ids
                    or any(
                        block and block.teacher_id in teacher_ids
                        for block in source.exceptions.values()
                    )
                ]
            for event in occurrences(document):
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
                    same_resource = event.get(field) is not None and event[field] == other[field]
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
                        warnings.setdefault(
                            (field, event[field], identities),
                            f"Conflit de {label} le {event['start'][:10]} : "
                            f"{other['title']} / {event['title']}.",
                        )
            active.append(event)
        return sorted(warnings.values())[:100]

    async def subscription(self, actor: UserContext, *, generate: bool = False) -> dict:
        """Return status only, or rotate the member's sole verifier and reveal its token once."""
        async with self.db.begin():
            user = await self.auth._actor(actor)
            roles = await self.auth.repo.roles(user.id)
            if user.is_bootstrap or not {"user", "teacher", "kholleur"}.intersection(roles):
                raise AuthError(
                    403, "Cet abonnement est réservé aux élèves et à l’équipe enseignante."
                )
            row = await self.db.get(TimetableSubscription, user.id)
            if not generate:
                return {"exists": row is not None}
            token = new_token()
            if row is None:
                row = TimetableSubscription(user_id=user.id)
                self.db.add(row)
            row.token_hash, row.created_at = token_digest(token), self.auth.clock()
            return {"token": token}

    async def feed(self, token: str) -> bytes:
        """Authorize by verifier and current membership, exporting only current publications."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise AuthError(404, "Abonnement introuvable.")
        async with self.db.begin():
            row = await self.db.scalar(
                select(TimetableSubscription).where(
                    TimetableSubscription.token_hash == token_digest(token)
                )
            )
            user = await self.db.get(User, row.user_id) if row else None
            if user is None or not self.auth._active(user, self.auth.clock()) or user.is_bootstrap:
                raise AuthError(404, "Abonnement introuvable.")
            roles = await self.auth.repo.roles(user.id)
            if not {"user", "teacher", "kholleur"}.intersection(roles):
                raise AuthError(404, "Abonnement introuvable.")
            events = []
            calendars = {calendar.id: calendar for calendar in await self.repo.calendars(user.id)}
            if calendars:
                assignments: dict[int, set[tuple[str, int]]] = {}
                for item in await self.db.scalars(
                    select(PromotionGroupMember).where(
                        PromotionGroupMember.user_id == user.id,
                        PromotionGroupMember.promotion_id.in_(
                            {calendar.promotion_id for calendar in calendars.values()}
                        ),
                    )
                ):
                    assignments.setdefault(item.promotion_id, set()).add(
                        (item.kind, item.group_number)
                    )
                today = self.today().isoformat()
                publications = await self.db.scalars(
                    select(TimetableYear).where(
                        TimetableYear.calendar_id.in_(calendars),
                        TimetableYear.published.is_not(None),
                        TimetableYear.published["settings"]["start"].astext <= today,
                        TimetableYear.published["settings"]["end"].astext >= today,
                    )
                )
                for year in publications:
                    memberships = assignments.get(calendars[year.calendar_id].promotion_id, set())
                    document = YearDocument.model_validate(year.published)
                    events.extend(
                        {**event, "published_at": year.published_at}
                        for event in occurrences(document)
                        if ("user" in roles and student_receives(event, user.id, memberships))
                        or ("user" not in roles and event["teacher_id"] == user.id)
                    )
            events = await self._decorate(events)
            calendar = Calendar()
            calendar.add("prodid", "-//Sophikron//Emploi du temps//FR")
            calendar.add("version", "2.0")
            calendar.add("x-wr-calname", "Mon emploi du temps — Sophikron")
            for item in events:
                event = Event()
                event.add("uid", item["id"] + "@sophikron")
                event.add(
                    "dtstamp", item["published_at"] or datetime(2000, 1, 1, tzinfo=timezone.utc)
                )
                event.add("last-modified", item["published_at"])
                event.add("dtstart", datetime.fromisoformat(item["start"]).astimezone(timezone.utc))
                event.add("dtend", datetime.fromisoformat(item["end"]).astimezone(timezone.utc))
                event.add("summary", item["title"])
                if item["room"]:
                    event.add("location", item["room"])
                event.add(
                    "description", " — ".join(filter(None, [item["kind"].upper(), item["teacher"]]))
                )
                calendar.add_component(event)
            return calendar.to_ical()


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
    if left_kind == right_kind:
        field = "target_user_id" if left_kind == "student" else "target_number"
        return left.get(field) == right.get(field)

    def recipients(event: dict, kind: str) -> set[int] | None:
        """Resolve known recipient sets without treating an unknown group as an empty class."""
        if kind == "student":
            return {event["target_user_id"]}
        return groups.get((event.get("promotion_id"), kind, event.get("target_number")))

    first, second = recipients(left, left_kind), recipients(right, right_kind)
    return bool(first & second) if first is not None and second is not None else True
