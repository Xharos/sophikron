"""Room/year catalogues and reversible annual calendar archival."""

from uuid import uuid4

from sqlalchemy import select

from app.models import (
    TeacherAvailability,
    TimetableCalendar,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableYear,
)
from app.schemas.timetable import (
    CalendarRestore,
    PreferencesSave,
    RoomSave,
    SchoolYearCreate,
    Version,
)
from app.services.activity import record_event
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.timetable import TimetableService
from app.services.timetable_engine import current_school_year
from app.services.timetable_lifecycle import rollover


class TimetableConfigurationService:
    """Manage immutable year labels, shared rooms and read-only calendar archives."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse the timetable authorization and request-owned transaction resources."""
        self.core = TimetableService(auth)
        self.auth = auth
        self.db = auth.db

    async def read(self, actor: UserContext) -> dict:
        """Return rooms and immutable academic-year labels only to permanent administrators."""
        async with self.db.begin():
            await self.core.authorize(actor, write=True)
            preferences = await rollover(self.db, self.core.today())
            return {
                "today": self.core.today().isoformat(),
                "preferences": {
                    "auto_archive": preferences.auto_archive,
                    "revision": preferences.revision,
                },
                "years": await self.core.common_years(),
                "rooms": [
                    {"id": room.id, "name": room.name, "revision": room.revision}
                    for room in await self.db.scalars(
                        select(TimetableRoom)
                        .where(TimetableRoom.is_active.is_(True))
                        .order_by(TimetableRoom.name)
                    )
                ],
            }

    async def create_school_year(self, actor: UserContext, data: SchoolYearCreate) -> dict:
        """Create an unused academic label; no common calendar settings are stored."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            if data.school_year < current_school_year(self.core.today()):
                raise AuthError(422, "Une année scolaire passée ne peut pas être créée.")
            if await self.db.get(TimetableSchoolYear, data.school_year):
                raise AuthError(409, "Cette année scolaire existe déjà.")
            row = TimetableSchoolYear(
                school_year=data.school_year, used=False, revision=uuid4().hex
            )
            self.db.add(row)
            await record_event(
                self.db,
                "timetable.school_year_created",
                actor.id,
                data={"school_year": row.school_year},
            )
            return {"school_year": row.school_year, "revision": row.revision}

    async def preferences(self, actor: UserContext, data: PreferencesSave) -> dict:
        """Save the policy and immediately catch up when automatic archival is enabled."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            row = await rollover(self.db, self.core.today())
            if row.revision != data.expected_revision:
                raise AuthError(409, "Ces réglages ont changé. Rechargez la page.")
            if data.auto_archive and not row.auto_archive:
                row.last_rollover_year = None
            row.auto_archive, row.revision = data.auto_archive, uuid4().hex
            await rollover(self.db, self.core.today())
            await record_event(
                self.db,
                "timetable.preferences_updated",
                actor.id,
                data={"auto_archive": row.auto_archive},
            )
            return {"auto_archive": row.auto_archive, "revision": row.revision}

    async def delete_school_year(self, actor: UserContext, school_year: int, data: Version) -> dict:
        """Delete only a never-used label under the same lifecycle lock as calendar creation."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            row = await self.db.get(TimetableSchoolYear, school_year)
            if row is None:
                raise AuthError(404, "Année scolaire introuvable.")
            if row.revision != data.expected_revision:
                raise AuthError(409, "L’année a changé. Rechargez la page.")
            availability = await self.db.scalar(
                select(TeacherAvailability.user_id)
                .where(TeacherAvailability.school_year == school_year)
                .limit(1)
            )
            calendar = await self.db.scalar(
                select(TimetableYear.id).where(TimetableYear.school_year == school_year).limit(1)
            )
            if row.used or availability is not None or calendar is not None:
                raise AuthError(409, "Une année déjà utilisée ne peut plus être supprimée.")
            await self.db.delete(row)
            await record_event(
                self.db,
                "timetable.school_year_deleted",
                actor.id,
                data={"school_year": school_year},
            )
            return {"school_year": school_year}

    async def room(
        self,
        actor: UserContext,
        identifier: int,
        data: RoomSave | None,
        expected_revision: str | None = None,
    ) -> dict:
        """Rename or retire a room without erasing references in existing sessions."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            room = await self.db.get(TimetableRoom, identifier)
            revision = data.expected_revision if data else expected_revision
            if room is None or not room.is_active:
                raise AuthError(404, "Salle introuvable.")
            if room.revision != revision:
                raise AuthError(409, "Cette salle a changé. Rechargez le catalogue.")
            if data:
                name = " ".join(data.name.split())
                if not name or len(name.casefold()) > 80:
                    raise AuthError(422, "Nom de salle invalide.")
                other = await self.db.scalar(
                    select(TimetableRoom).where(
                        TimetableRoom.name_key == name.casefold(), TimetableRoom.id != room.id
                    )
                )
                if other:
                    raise AuthError(409, "Une salle porte déjà ce nom.")
                room.name, room.name_key = name, name.casefold()
            else:
                room.is_active = False
            room.revision = uuid4().hex
            await record_event(
                self.db,
                "timetable.room_saved" if data else "timetable.room_deleted",
                actor.id,
                data={"title": room.name},
            )
            return {"id": room.id, "revision": room.revision}

    async def archive(self, actor: UserContext, identifier: int, data: Version) -> dict:
        """Stop all diffusion and make a retained calendar permanently read-only until restored."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            calendar = await self.core._calendar(identifier, actor, write=True)
            if calendar.revision != data.expected_revision:
                raise AuthError(409, "Le calendrier a changé. Rechargez la liste.")
            self.core.require_live_confirmation(calendar, data.confirmed_live)
            calendar.is_archived, calendar.is_paused = True, True
            calendar.revision = uuid4().hex
            for year in await self.core.repo.years(calendar.id):
                await self.core._changed(actor, year, "archived")
            return {"id": calendar.id, "revision": calendar.revision}

    async def restore(self, actor: UserContext, identifier: int, data: CalendarRestore) -> dict:
        """Restore without broadcasting, optionally detaching a conflicting promotion."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            calendar = await self.db.get(TimetableCalendar, identifier)
            if calendar is None or not calendar.is_archived:
                raise AuthError(404, "Archive introuvable.")
            if calendar.revision != data.expected_revision:
                raise AuthError(409, "L’archive a changé. Rechargez la liste.")
            if calendar.promotion_id is not None and not data.detach_promotion:
                conflict = await self.db.scalar(
                    select(TimetableCalendar.id).where(
                        TimetableCalendar.promotion_id == calendar.promotion_id,
                        TimetableCalendar.is_archived.is_(False),
                    )
                )
                if conflict is not None:
                    raise AuthError(
                        409,
                        "Cette promotion possède un calendrier actif. Réactivez sans promotion.",
                    )
            if data.detach_promotion:
                calendar.promotion_id = None
            calendar.is_archived, calendar.is_paused = False, True
            calendar.revision = uuid4().hex
            for year in await self.core.repo.years(calendar.id):
                await self.core._changed(actor, year, "restored")
            return {"id": calendar.id, "revision": calendar.revision}
