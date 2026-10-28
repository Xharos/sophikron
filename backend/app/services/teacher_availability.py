"""Annual staff availability, private teaching calendars and non-blocking availability warnings."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select

from app.models import (
    Promotion,
    PromotionCustomGroupMember,
    PromotionGroupMember,
    Role,
    Subject,
    TeacherAvailability,
    TeacherSubject,
    TimetableCalendar,
    TimetableSchoolYear,
    User,
    UserPromotion,
    UserRole,
)
from app.schemas.teacher_availability import AvailabilitySave
from app.schemas.timetable import YearSettings
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.timetable import TimetableService
from app.services.timetable_engine import PARIS, daily_slots, occurrences
from app.services.timetable_occupancy import fully_occupied_ranges


def availability_settings(school_year: int) -> YearSettings:
    """Provide a fixed staff grid independent of every promotion calendar and its pauses."""
    return YearSettings(
        start=date(school_year, 9, 1),
        end=date(school_year + 1, 8, 31),
        day_start=28800,
        day_end=68400,
        session_minutes=60,
        breaks=[],
        saturday=True,
    )


def open_ranges(settings: YearSettings) -> list[dict]:
    """Return every open weekday interval, excluding breaks and disabled Saturdays.

    Parameters
    ----------
    settings
        Current annual opening rules.

    Returns
    -------
    list[dict]
        Available weekday intervals, including any final partial session.
    """
    return [
        {"weekday": weekday, "start": 28800, "end": 43200 if weekday == 5 else 68400}
        for weekday in range(6)
    ]


def effective_ranges(ranges: list[dict] | None, settings: YearSettings) -> list[dict]:
    """Intersect explicit availability with current opening rules and merge touching intervals.

    Parameters
    ----------
    ranges
        Stored weekly pattern, or None for full availability.
    settings
        Current annual opening rules; changes clip stored patterns without deleting them.

    Returns
    -------
    list[dict]
        Sorted, disjoint available intervals.
    """
    opening = open_ranges(settings)
    if ranges is None:
        return opening
    pieces = sorted(
        (
            allowed["weekday"],
            max(item["start"], allowed["start"]),
            min(item["end"], allowed["end"]),
        )
        for item in ranges
        for allowed in opening
        if item["weekday"] == allowed["weekday"]
        and max(item["start"], allowed["start"]) < min(item["end"], allowed["end"])
    )
    result: list[dict] = []
    for weekday, start, end in pieces:
        if result and result[-1]["weekday"] == weekday and result[-1]["end"] >= start:
            result[-1]["end"] = max(result[-1]["end"], end)
        else:
            result.append({"weekday": weekday, "start": start, "end": end})
    return result


def availability_warnings(
    events: list[dict], patterns: dict[tuple[int, int], list[dict]], today: date
) -> list[str]:
    """Warn once per recurring assignment outside availability, ignoring past Paris dates.

    Parameters
    ----------
    events
        Decorated teaching segments with school_year and stable conflict_key fields.
    patterns
        Effective explicit intervals keyed by teacher and school year; missing means unrestricted.
    today
        Injectable current school date.

    Returns
    -------
    list[str]
        One warning per teacher and recurring assignment, naming its first conflicting date.
    """
    warnings: dict[tuple, str] = {}
    for event in sorted(events, key=lambda item: item["start"]):
        start, end = (
            datetime.fromisoformat(event[field]).astimezone(PARIS) for field in ("start", "end")
        )
        ranges = patterns.get((event["teacher_id"], event["school_year"]))
        if start.date() < today or ranges is None:
            continue
        seconds = start.hour * 3600 + start.minute * 60 + start.second
        stop = seconds + int((end - start).total_seconds())
        if any(
            item["weekday"] == start.weekday() and item["start"] <= seconds and stop <= item["end"]
            for item in ranges
        ):
            continue
        key = (event["teacher_id"], event.get("conflict_key", event["series_id"]))
        warnings.setdefault(
            key,
            f"Disponibilité de {event['teacher']} : {event['title']} hors plage disponible "
            f"le {start.date().isoformat()} (première occurrence concernée).",
        )
    return list(warnings.values())


def teaching_audience_label(event: dict) -> str:
    """Describe a teaching audience without returning recipient or pupil identifiers.

    Parameters
    ----------
    event
        Authorized session with its validated audience kind and optional group number.

    Returns
    -------
    str
        Public group description; individual sessions never include a pupil's name.
    """
    kind, number = event.get("target_kind", "promotion"), event.get("target_number")
    if kind == "custom":
        return event.get("audience_label", "Groupe personnalisé")
    if kind == "halves":
        return f"Demi-groupe {chr(64 + number)}" if number else "Demi-groupe"
    if kind == "thirds":
        return f"Tiers de groupe {chr(87 + number)}" if number else "Tiers de groupe"
    if kind == "kholles":
        return f"Groupe de khôlle {number:03d}" if number else "Groupe de khôlle"
    return "Séance individuelle" if kind == "student" else "Classe entière"


class TeacherAvailabilityService:
    """Expose only teaching identities and sessions; students never enter this workspace."""

    def __init__(self, auth: AuthService) -> None:
        """Share the authenticated request session and established timetable authorization."""
        self.auth = auth
        self.db = auth.db
        self.timetable = TimetableService(auth)

    async def teachers(self) -> list[dict]:
        """Read active teaching staff and subject folders without pupil or account details."""
        users = list(
            await self.db.scalars(
                select(User).where(
                    User.is_bootstrap.is_(False),
                    User.status != "disabled",
                    select(UserRole.user_id)
                    .join(Role)
                    .where(UserRole.user_id == User.id, Role.code.in_(["teacher", "kholleur"]))
                    .exists(),
                )
            )
        )
        subjects: dict[int, list[int]] = {}
        for user_id, subject_id in await self.db.execute(
            select(TeacherSubject.user_id, TeacherSubject.subject_id)
            .join(Subject)
            .where(
                TeacherSubject.user_id.in_([user.id for user in users]), Subject.is_active.is_(True)
            )
        ):
            subjects.setdefault(user_id, []).append(subject_id)
        return [
            {**self.timetable._identity(user), "subject_ids": sorted(subjects.get(user.id, []))}
            for user in users
        ]

    async def catalog(self, actor: UserContext) -> dict:
        """Return annual rules and teaching identities after checking staff access."""
        async with self.db.begin():
            admin = await self.timetable.authorize(actor)
            years = list(
                await self.db.scalars(
                    select(TimetableSchoolYear).order_by(TimetableSchoolYear.school_year.desc())
                )
            )
            return {
                "administrator": admin,
                "today": self.timetable.today().isoformat(),
                "teachers": await self.teachers(),
                "subjects": [
                    {"id": row.id, "name": row.name, "color": row.color}
                    for row in await self.db.scalars(
                        select(Subject).where(Subject.is_active.is_(True))
                    )
                ],
                "years": [
                    {
                        "school_year": row.school_year,
                        "settings": availability_settings(row.school_year).model_dump(mode="json"),
                        "slots": daily_slots(availability_settings(row.school_year)),
                    }
                    for row in years
                ],
            }

    async def board(
        self,
        actor: UserContext,
        school_year: int,
        teacher_ids: list[int],
        *,
        include_occupancy: bool = False,
    ) -> dict:
        """Combine teaching assignments without exposing pupil rosters or include_privates to staff.

        Parameters
        ----------
        actor
            Authenticated teaching member or administrator.
        school_year
            Configured annual pattern to consult.
        teacher_ids
            Explicitly selected teachers; no automatic multi-teacher overlay.
        include_occupancy
            Calculate aggregate pupil occupancy only for the availability view.

        Returns
        -------
        dict
            Availability and live assignments; administrators also see private preparations.
        """
        async with self.db.begin():
            admin = await self.timetable.authorize(actor)
            common = await self.db.get(TimetableSchoolYear, school_year)
            if common is None:
                raise AuthError(404, "Configurez d’abord les règles de cette année scolaire.")
            teachers = await self.teachers()
            if not set(teacher_ids).issubset({item["id"] for item in teachers}):
                raise AuthError(404, "Enseignant introuvable.")
            settings = availability_settings(school_year)
            patterns = {
                row.user_id: row
                for row in await self.db.scalars(
                    select(TeacherAvailability).where(
                        TeacherAvailability.school_year == school_year,
                        TeacherAvailability.user_id.in_(teacher_ids),
                    )
                )
            }
            events = []
            documents = await self.timetable.repo.teaching_documents(
                school_year, include_private=admin
            )
            calendar_rows = (
                list(
                    await self.db.execute(
                        select(
                            TimetableCalendar,
                            Promotion.identifier,
                            Promotion.year,
                            Promotion.is_active,
                        )
                        .outerjoin(Promotion, Promotion.id == TimetableCalendar.promotion_id)
                        .where(
                            TimetableCalendar.id.in_({year.calendar_id for year, _ in documents})
                        )
                    )
                )
                if documents
                else []
            )
            labels = {
                calendar.id: f"{promotion} {promotion_year}" if promotion else calendar.name
                for calendar, promotion, promotion_year, _ in calendar_rows
            }
            calendar_names = {calendar.id: calendar.name for calendar, _, _, _ in calendar_rows}
            participating = {
                calendar.id: calendar.promotion_id
                for calendar, _, _, active in calendar_rows
                if not calendar.is_paused and active is not False
            }
            occupancy_events: dict[int, list[dict]] = {}
            for year, document in documents:
                if include_occupancy:
                    generated = occurrences(document)
                    if year.calendar_id in participating:
                        occupancy_events[year.calendar_id] = generated
                else:
                    generated = None
                # Include exception replacements assigning a different teacher as well.
                document.series = [
                    series
                    for series in document.series
                    if series.teacher_id in teacher_ids
                    or any(
                        block and block.teacher_id in teacher_ids
                        for block in series.exceptions.values()
                    )
                ]
                events.extend(
                    {
                        **event,
                        "calendar_id": year.calendar_id,
                        "year_id": year.id,
                        "promotion_id": None,
                        "school_year": school_year,
                        "session_minutes": document.settings.session_minutes,
                    }
                    for event in (generated if generated is not None else occurrences(document))
                    if event["teacher_id"] in teacher_ids
                )
            occupied = (
                await self._occupied_ranges(occupancy_events, participating, settings)
                if include_occupancy
                else []
            )
            decorated = await self.timetable._decorate(events)
            # This workspace never returns pupil IDs, audience details or unassigned sessions.
            private_fields = {"target_kind", "target_number", "target_user_id"}
            return {
                "occupied_ranges": occupied,
                "availability": [
                    {
                        "teacher_id": identifier,
                        "revision": patterns[identifier].revision
                        if identifier in patterns
                        else None,
                        "default": identifier not in patterns,
                        "ranges": effective_ranges(
                            patterns[identifier].ranges if identifier in patterns else None,
                            settings,
                        ),
                    }
                    for identifier in teacher_ids
                ],
                "events": [
                    {
                        **{key: value for key, value in event.items() if key not in private_fields},
                        "audience_label": teaching_audience_label(event),
                        "calendar_label": (
                            f"{calendar_names[event['calendar_id']]} · "
                            f"{labels[event['calendar_id']]}"
                            if calendar_names[event["calendar_id"]] != labels[event["calendar_id"]]
                            else labels[event["calendar_id"]]
                        ),
                    }
                    for event in decorated
                ],
            }

    async def _occupied_ranges(
        self,
        events: dict[int, list[dict]],
        promotions: dict[int, int | None],
        settings: YearSettings,
    ) -> list[dict]:
        """Batch-load internal pupil memberships and expose only clipped weekly coverage.

        Parameters
        ----------
        events, promotions
            Authorized active sources and their optional promotion IDs.
        settings
            School opening rules; pauses and closed days remain outside coverage.

        Returns
        -------
        list[dict]
            Anonymous weekday/start/end ranges, independent of the selected teacher.
        """
        if not events or any(not sessions for sessions in events.values()):
            return []
        promotion_ids = {
            promotions[identifier] for identifier in events if promotions[identifier] is not None
        }
        rosters: dict[int, set[int]] = {}
        if promotion_ids:
            for promotion_id, user_id in await self.db.execute(
                select(UserPromotion.promotion_id, UserPromotion.user_id)
                .join(User, User.id == UserPromotion.user_id)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    UserPromotion.promotion_id.in_(promotion_ids),
                    Role.code == "user",
                    User.status != "disabled",
                    User.is_bootstrap.is_(False),
                )
            ):
                rosters.setdefault(promotion_id, set()).add(user_id)
        memberships: dict[int, dict[tuple[str, int], set[int]]] = {}
        if rosters:
            for row in await self.db.scalars(
                select(PromotionGroupMember).where(PromotionGroupMember.promotion_id.in_(rosters))
            ):
                memberships.setdefault(row.promotion_id, {}).setdefault(
                    (row.kind, row.group_number), set()
                ).add(row.user_id)
            for row in await self.db.scalars(
                select(PromotionCustomGroupMember).where(
                    PromotionCustomGroupMember.promotion_id.in_(rosters)
                )
            ):
                memberships.setdefault(row.promotion_id, {}).setdefault(
                    ("custom", row.group_id), set()
                ).add(row.user_id)
        ranges = fully_occupied_ranges(
            events,
            {identifier: rosters.get(promotions[identifier], set()) for identifier in events},
            {identifier: memberships.get(promotions[identifier], {}) for identifier in events},
        )
        return effective_ranges(ranges, settings)

    async def save(
        self, actor: UserContext, school_year: int, teacher_id: int, data: AvailabilitySave
    ) -> dict:
        """Replace one admin-owned pattern atomically, rejecting stale revisions and invalid hours.

        Parameters
        ----------
        actor
            Administrator who may write availability.
        school_year, teacher_id
            Annual teaching pattern identity.
        data
            Observed revision and replacement ranges, or null to restore opening hours.

        Returns
        -------
        dict
            New revision; null after restoring the implicit default.
        """
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.timetable.authorize(actor, write=True)
            common = await self.db.get(TimetableSchoolYear, school_year, with_for_update=True)
            if common is None:
                raise AuthError(404, "Année scolaire introuvable.")
            if teacher_id not in {item["id"] for item in await self.teachers()}:
                raise AuthError(404, "Enseignant introuvable.")
            row = await self.db.get(
                TeacherAvailability, (teacher_id, school_year), with_for_update=True
            )
            if (row.revision if row else None) != data.expected_revision:
                raise AuthError(
                    409, "Les disponibilités ont changé. Rechargez-les avant de continuer."
                )
            common.used = True
            if data.ranges is None:
                if row:
                    await self.db.delete(row)
                return {"revision": None}
            settings = availability_settings(school_year)
            if any(
                item.start < 28800 or item.end > (43200 if item.weekday == 5 else 68400)
                for item in data.ranges
            ):
                raise AuthError(
                    422, "Les disponibilités doivent rester dans les horaires d’ouverture."
                )
            if row is None:
                row = TeacherAvailability(user_id=teacher_id, school_year=school_year)
                self.db.add(row)
            row.ranges = effective_ranges([item.model_dump() for item in data.ranges], settings)
            row.revision = uuid4().hex
            return {"revision": row.revision}
