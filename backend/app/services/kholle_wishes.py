"""Administrator-owned annual commitments, independent of timetable availability."""

import hashlib
import json
from fractions import Fraction
from uuid import uuid4

from sqlalchemy import select

from app.models import (
    KholleWish,
    KholloscopeWorkflow,
    Role,
    Subject,
    TeacherSubject,
    TimetableSchoolYear,
    User,
    UserRole,
)
from app.schemas.kholle import KholleWishesSave
from app.schemas.timetable import YearSettings
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.kholle import KholleService, kholle_weeks
from app.services.kholloscope_service import service_cycles


class KholleWishesService(KholleService):
    """Version the complete visible roster and save its wishes in one transaction."""

    async def _state(self, year: TimetableSchoolYear) -> dict:
        """Batch-load eligible staff and wishes, preserving hidden historical assignments.

        Parameters
        ----------
        year
            Existing academic label, locked by the caller for writes.

        Returns
        -------
        dict
            Subject rows, unassigned staff and a revision covering data and eligibility.
        """
        staff_roles: dict[int, list[str]] = {}
        for user_id, role in await self.db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role)
            .where(Role.code.in_(["teacher", "kholleur"]))
        ):
            staff_roles.setdefault(user_id, []).append(role)
        users = list(
            await self.db.scalars(
                select(User).where(
                    User.id.in_(staff_roles),
                    User.is_bootstrap.is_(False),
                    User.status != "disabled",
                )
            )
        )
        people = {
            user.id: {
                **self._identity(user),
                "first_name": self.auth.cipher.decrypt(
                    user.id, "first_name", user.first_name_encrypted
                )
                or "",
                "last_name": self.auth.cipher.decrypt(
                    user.id, "last_name", user.last_name_encrypted
                )
                or "",
                "roles": sorted(staff_roles[user.id]),
            }
            for user in users
        }
        assignments: dict[int, list[int]] = {}
        for user_id, subject_id in await self.db.execute(
            select(TeacherSubject.user_id, TeacherSubject.subject_id)
            .join(Subject)
            .where(TeacherSubject.user_id.in_(people), Subject.is_active.is_(True))
        ):
            assignments.setdefault(subject_id, []).append(user_id)
        calendars = []
        for calendar in await self.active_calendars(year.school_year):
            if not calendar.kholle_settings:
                continue
            annual = (await self.repo.years(calendar.id))[0]
            cfg = calendar.kholle_settings
            weeks = sum(
                w["eligible"] and cfg["start"] <= w["start"] <= cfg["end"]
                for w in kholle_weeks(
                    YearSettings.model_validate(annual.settings), year.school_year
                )
            )
            calendars.append({"weeks": weeks, "settings": cfg})
        cycles = service_cycles(calendars)
        workflow = await self.db.get(KholloscopeWorkflow, year.school_year)
        saved_cycles = (workflow.data if workflow else {}).get("wish_cycles", {})
        wishes = {
            (row.user_id, row.subject_id): row.sessions
            for row in await self.db.scalars(
                select(KholleWish).where(KholleWish.school_year == year.school_year)
            )
        }
        subjects = [
            {
                "id": subject.id,
                "name": subject.name,
                "icon": subject.icon,
                "color": subject.color,
                "staff": sorted(
                    [
                        {**people[user_id], "sessions": wishes.get((user_id, subject.id))}
                        for user_id in assignments.get(subject.id, [])
                    ],
                    key=lambda person: (
                        person["last_name"].casefold(),
                        person["first_name"].casefold(),
                        person["id"],
                    ),
                ),
            }
            for subject in await self.db.scalars(
                select(Subject)
                .where(Subject.is_active.is_(True))
                .order_by(Subject.name, Subject.id)
            )
        ]
        for subject in subjects:
            previous = saved_cycles.get(str(subject["id"]), 2)
            period = cycles.get(subject["id"], previous)
            subject["cycle_weeks"] = period
            subject["previous_cycle_weeks"] = previous
            for person in subject["staff"]:
                if person["sessions"] is not None:
                    value = Fraction(person["sessions"] * period, previous)
                    person["sessions"] = int(value) if value.denominator == 1 else None
        published = await self.repo.published_kholloscope(year.school_year)
        if published and published.result:
            from app.services.kholloscope_versions import effective_metadata

            effective = effective_metadata(published.result, self.today())
            for subject in subjects:
                values = effective.get("revision_wishes", {}).get(str(subject["id"]), {})
                for person in subject["staff"]:
                    if str(person["id"]) in values:
                        person["sessions"] = values[str(person["id"])]
        assigned = {
            identifier for identifiers in assignments.values() for identifier in identifiers
        }
        unassigned = sorted(
            [person for identifier, person in people.items() if identifier not in assigned],
            key=lambda person: person["name"].casefold(),
        )
        payload = {"school_year": year.school_year, "subjects": subjects, "unassigned": unassigned}
        revision = hashlib.sha256(
            json.dumps([year.revision, payload], sort_keys=True).encode()
        ).hexdigest()
        return {**payload, "revision": revision}

    async def read(self, actor: UserContext, school_year: int) -> dict:
        """Return annual wishes only after independently checking administrator access."""
        async with self.db.begin():
            await self.authorize(actor)
            year = await self.db.get(TimetableSchoolYear, school_year)
            if year is None:
                raise AuthError(404, "Année scolaire introuvable.")
            return await self._state(year)

    async def save(self, actor: UserContext, school_year: int, data: KholleWishesSave) -> dict:
        """Atomically replace visible wishes and reject stale rosters or invalid eligibility.

        Parameters
        ----------
        actor, school_year, data
            Current administrator, target label and complete observed roster submission.

        Returns
        -------
        dict
            Refreshed annual wishes and revision after the entire save succeeds.
        """
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            await self.require_unpublished_kholloscope(school_year)
            year = await self.db.get(TimetableSchoolYear, school_year, with_for_update=True)
            if year is None:
                raise AuthError(404, "Année scolaire introuvable.")
            state = await self._state(year)
            if state["revision"] != data.expected_revision:
                raise AuthError(
                    409, "Les souhaits ou les intervenants ont changé. Rechargez la page."
                )
            allowed = {
                (person["id"], subject["id"])
                for subject in state["subjects"]
                for person in subject["staff"]
            }
            if {(entry.user_id, entry.subject_id) for entry in data.entries} != allowed:
                raise AuthError(
                    422, "Renseignez la liste complète des intervenants et matières autorisés."
                )
            existing = {
                (row.user_id, row.subject_id): row
                for row in await self.db.scalars(
                    select(KholleWish).where(KholleWish.school_year == school_year)
                )
            }
            for entry in data.entries:
                row = existing.get((entry.user_id, entry.subject_id))
                if entry.sessions is None:
                    if row is not None:
                        await self.db.delete(row)
                elif row is None:
                    self.db.add(
                        KholleWish(
                            school_year=school_year,
                            user_id=entry.user_id,
                            subject_id=entry.subject_id,
                            sessions=entry.sessions,
                        )
                    )
                else:
                    row.sessions = entry.sessions
            workflow = await self.db.get(KholloscopeWorkflow, school_year)
            stored = dict(workflow.data) if workflow else {}
            stored["wish_cycles"] = {str(s["id"]): s["cycle_weeks"] for s in state["subjects"]}
            if workflow is None:
                self.db.add(
                    KholloscopeWorkflow(school_year=school_year, data=stored, revision=uuid4().hex)
                )
            else:
                workflow.data, workflow.revision = stored, uuid4().hex
            year.used = True
            year.revision = uuid4().hex
            await self.db.flush()
            return await self._state(year)
