"""Establishment-wide calendar settings and reversible catalogue operations."""

from uuid import uuid4

from sqlalchemy import select

from app.models import TimetableRoom, TimetableSchoolYear, TimetableYear
from app.schemas.timetable import CommonSettingsSave, RoomSave
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.timetable import TimetableService
from app.services.timetable_engine import daily_slots, validate_series


class TimetableConfigurationService:
    """Apply common drafts atomically while leaving published annual snapshots untouched."""

    def __init__(self, auth: AuthService) -> None:
        """Reuse the timetable authorization and request-owned transaction resources."""
        self.core = TimetableService(auth)
        self.auth = auth
        self.db = auth.db

    async def read(self, actor: UserContext) -> dict:
        """Return shared settings and legacy alternatives only to permanent administrators."""
        async with self.db.begin():
            await self.core.authorize(actor, write=True)
            return {
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

    async def save(self, actor: UserContext, data: CommonSettingsSave) -> dict:
        """Validate all affected agenda drafts before changing their shared annual settings."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.core.authorize(actor, write=True)
            row = await self.db.get(TimetableSchoolYear, data.settings.start.year)
            if (row.revision if row else None) != data.expected_revision:
                raise AuthError(409, "Les réglages communs ont changé. Rechargez la page.")
            if not daily_slots(data.settings):
                raise AuthError(422, "Aucun demi-créneau complet dans cette journée.")
            years = list(
                await self.db.scalars(
                    select(TimetableYear).where(
                        TimetableYear.school_year == data.settings.start.year
                    )
                )
            )
            for year in years:
                document = await self.core.repo.document(year)
                for series in document.series:
                    validate_series(series, data.settings)
            if row is None:
                row = TimetableSchoolYear(school_year=data.settings.start.year)
                self.db.add(row)
            row.settings = data.settings.model_dump(mode="json")
            row.revision = uuid4().hex
            for year in years:
                year.settings = row.settings
                year.starts_on, year.ends_on = data.settings.start, data.settings.end
                await self.core._changed(actor, year)
            return {"revision": row.revision}

    async def room(
        self,
        actor: UserContext,
        identifier: int,
        data: RoomSave | None,
        expected_revision: str | None = None,
    ) -> dict:
        """Rename or retire a room without erasing references in existing publications."""
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
            return {"id": room.id, "revision": room.revision}

    async def delete_calendar(self, actor: UserContext, identifier: int, revision: str) -> dict:
        """Remove an agenda from consultation and feeds while retaining its stored history."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            calendar = await self.core._calendar(identifier, actor, write=True)
            if calendar.revision != revision:
                raise AuthError(409, "L’agenda a changé. Rechargez la liste.")
            calendar.is_deleted = True
            calendar.revision = uuid4().hex
            return {"id": calendar.id}
