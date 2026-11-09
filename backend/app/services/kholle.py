"""Administrator-only kholle configuration and available-week arithmetic."""

from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import func, select

from app.models import (
    KholloscopeWorkflow,
    Promotion,
    PromotionGroup,
    PromotionPartition,
    Subject,
    TimetableCalendar,
    TimetableSchoolYear,
)
from app.repositories.groups import active_kholle_group
from app.schemas.kholle import KholleSave
from app.schemas.timetable import YearSettings
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.timetable import TimetableService
from app.services.timetable_engine import teaching_day, teaching_weeks


def kholle_weeks(settings: YearSettings, school_year: int) -> list[dict]:
    """Return dated teaching-week labels and count available weekdays.

    Parameters
    ----------
    settings
        Current calendar bounds and inclusive holiday exclusions.
    school_year
        Academic label bounding selectable Mondays and Fridays.

    Returns
    -------
    list[dict]
        Weeks with at least one teaching day; eligible weeks have three weekdays.
    """
    result = []
    for monday, number in teaching_weeks(settings).items():
        friday = monday + timedelta(days=4)
        if friday < date(school_year, 9, 1) or monday > date(school_year + 1, 8, 31):
            continue
        days = sum(teaching_day(monday + timedelta(days=i), settings) for i in range(5))
        result.append(
            {
                "start": monday.isoformat(),
                "end": friday.isoformat(),
                "number": number,
                "days": days,
                "eligible": days >= 3,
            }
        )
    return result


class KholleService(TimetableService):
    """Keep settings on the calendar and derive load from its current promotion."""

    async def authorize(self, actor: UserContext, *, write: bool = False) -> bool:
        """Require explicit kholloscope capabilities and retain the current admin-only gate."""
        current = await self.auth._actor(actor)
        permissions = set(await self.auth.repo.permissions(actor.id))
        roles = await self.auth.repo.roles(actor.id)
        required = {"kholloscope.read"} | ({"kholloscope.write"} if write else set())
        if current.is_bootstrap or "admin" not in roles or not required <= permissions:
            raise AuthError(403, "Vous n’avez pas accès au kholloscope.")
        return await super().authorize(actor, write=write)

    async def active_calendars(self, school_year: int) -> list[TimetableCalendar]:
        """Keep active promotion agendas and unassigned calendars needing configuration."""
        active = set(
            await self.db.scalars(select(Promotion.id).where(Promotion.is_active.is_(True)))
        )
        return [
            c
            for c in await self.repo.calendars(None, school_year=school_year)
            if c.promotion_id is None or c.promotion_id in active
        ]

    async def overview(self, actor: UserContext, school_year: int | None = None) -> dict:
        """Return prerequisites or statistics only for the selected academic year."""
        async with self.db.begin():
            return await self._overview(actor, school_year)

    async def _overview(self, actor: UserContext, school_year: int | None) -> dict:
        """Read annual requirements inside the caller-owned transaction."""
        await self.authorize(actor)
        years = list(
            await self.db.scalars(
                select(TimetableSchoolYear.school_year).order_by(
                    TimetableSchoolYear.created_at.desc(),
                    TimetableSchoolYear.school_year.desc(),
                )
            )
        )
        selected = school_year if school_year is not None else next(iter(years), None)
        if school_year is not None and school_year not in years:
            raise AuthError(422, "Année scolaire introuvable.")
        context = {"years": years, "school_year": selected}
        calendars = await self.active_calendars(selected) if selected is not None else []
        errors = []
        if not calendars:
            errors.append("Créer un calendrier en premier.")
        errors.extend(
            f"Affecter le calendrier {c.id} à une promo."
            for c in calendars
            if c.promotion_id is None
        )
        errors.extend(
            f"Saisir les khôlles du calendrier {c.id}." for c in calendars if not c.kholle_settings
        )
        if errors:
            return {**context, "errors": errors, "calendars": []}
        items = []
        for calendar in calendars:
            year = (await self.repo.years(calendar.id))[0]
            settings = calendar.kholle_settings
            weeks = sum(
                w["eligible"] and settings["start"] <= w["start"] <= settings["end"]
                for w in kholle_weeks(YearSettings.model_validate(year.settings), year.school_year)
            )
            groups = await self.db.scalar(
                select(func.count())
                .select_from(PromotionGroup)
                .where(
                    PromotionGroup.promotion_id == calendar.promotion_id,
                    PromotionGroup.kind == "kholles",
                    active_kholle_group(),
                )
            )
            size = await self.db.scalar(
                select(PromotionPartition.target_size).where(
                    PromotionPartition.promotion_id == calendar.promotion_id,
                    PromotionPartition.kind == "kholles",
                )
            )
            subjects = []
            for entry in settings["subjects"]:
                subject = await self.db.get(Subject, entry["subject_id"])
                subjects.append(
                    {
                        **entry,
                        "name": subject.name if subject else "Matière retirée",
                        "icon": subject.icon if subject else "book",
                        "color": subject.color if subject else "#808080",
                    }
                )
            items.append(
                {
                    "id": calendar.id,
                    "name": calendar.name,
                    "settings": {**settings, "subjects": subjects},
                    "weeks": weeks,
                    "group_count": groups,
                    "group_size": size,
                }
            )
        return {**context, "errors": [], "calendars": items}

    async def read(self, actor: UserContext, identifier: int) -> dict:
        """Read private configuration and current group count as an administrator."""
        async with self.db.begin():
            calendar = await self._calendar(identifier, actor, write=False)
            if calendar.promotion_id is None:
                raise AuthError(422, "Affectez une promotion avant de configurer les khôlles.")
            year = (await self.repo.years(identifier))[0]
            count = await self.db.scalar(
                select(func.count())
                .select_from(PromotionGroup)
                .where(
                    PromotionGroup.promotion_id == calendar.promotion_id,
                    PromotionGroup.kind == "kholles",
                    active_kholle_group(),
                )
            )
            return {
                "settings": calendar.kholle_settings,
                "published": bool(await self.repo.published_kholloscope(year.school_year)),
                "revision": calendar.revision,
                "year_revision": year.revision,
                "group_count": count,
                "group_size": await self.db.scalar(
                    select(PromotionPartition.target_size).where(
                        PromotionPartition.promotion_id == calendar.promotion_id,
                        PromotionPartition.kind == "kholles",
                    )
                ),
                "weeks": kholle_weeks(YearSettings.model_validate(year.settings), year.school_year),
            }

    async def save(self, actor: UserContext, identifier: int, data: KholleSave) -> dict:
        """Validate references, dates and optimistic revisions before an atomic save."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self._calendar(identifier, actor, write=True)
            calendar = await self.db.scalar(
                select(TimetableCalendar)
                .where(TimetableCalendar.id == identifier)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            year = (await self.repo.years(identifier))[0]
            if (
                calendar.revision != data.expected_revision
                or year.revision != data.expected_year_revision
            ):
                raise AuthError(409, "L’agenda a changé. Fermez puis rouvrez les réglages.")
            await self.require_unpublished_kholloscope(year.school_year)
            if calendar.promotion_id is None:
                raise AuthError(422, "Affectez une promotion avant de configurer les khôlles.")
            weeks = kholle_weeks(YearSettings.model_validate(year.settings), year.school_year)
            start, end = data.settings.start.isoformat(), data.settings.end.isoformat()
            if (
                not any(w["start"] == start for w in weeks)
                or not any(w["end"] == end for w in weeks)
                or not any(w["eligible"] and start <= w["start"] <= end for w in weeks)
            ):
                raise AuthError(
                    422, "La période doit contenir des semaines disponibles du calendrier."
                )
            ids = {item.subject_id for item in data.settings.subjects}
            valid = set(
                await self.db.scalars(
                    select(Subject.id).where(Subject.id.in_(ids), Subject.is_active.is_(True))
                )
            )
            if ids != valid:
                raise AuthError(422, "Sélectionnez des matières actives du catalogue.")
            settings = data.settings.model_dump(mode="json")
            settings["subjects"].sort(key=lambda item: item["subject_id"])
            existing = calendar.kholle_settings
            if existing is not None:
                existing = {
                    **existing,
                    "subjects": sorted(existing["subjects"], key=lambda item: item["subject_id"]),
                }
            if existing == settings:
                return {"revision": calendar.revision}
            workflow = await self.db.get(
                KholloscopeWorkflow, year.school_year, with_for_update=True
            )
            if workflow is not None:
                # Retain old confirmations to distinguish stale steps from untouched steps.
                workflow.revision = uuid4().hex
            calendar.kholle_settings = settings
            calendar.revision = uuid4().hex
            return {"revision": calendar.revision}
