"""Parameterized timetable persistence inside service-owned transactions."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Promotion,
    TimetableCalendar,
    TimetableSeries,
    TimetableYear,
    UserPromotion,
)
from app.schemas.timetable import SeriesData, YearDocument, YearSettings


class TimetableRepository:
    """Load annual documents and limit agendas to current promotion membership."""

    def __init__(self, db: AsyncSession) -> None:
        """Use the request's existing transaction-bound session."""
        self.db = db

    async def calendars(
        self,
        user_id: int | None,
        *,
        archives: bool = False,
        include_undiffused: bool = False,
        school_year: int | None = None,
    ) -> list[TimetableCalendar]:
        """Return all admin agendas or only agendas in the caller's active promotions."""
        statement = (
            select(TimetableCalendar)
            .where(TimetableCalendar.is_archived.is_(False) if not archives else True)
            .order_by(TimetableCalendar.name)
        )
        if user_id is not None:
            statement = (
                statement.join(Promotion)
                .join(UserPromotion)
                .where(
                    UserPromotion.user_id == user_id,
                    Promotion.is_active.is_(True),
                    True if include_undiffused else TimetableCalendar.is_paused.is_(False),
                    TimetableCalendar.is_archived.is_(False),
                )
            )
        if school_year is not None:
            statement = statement.join(TimetableYear).where(
                TimetableYear.school_year == school_year
            )
        return list(await self.db.scalars(statement))

    async def years(self, calendar_id: int) -> list[TimetableYear]:
        """Return an agenda's annual configuration in school-year order."""
        return list(
            await self.db.scalars(
                select(TimetableYear)
                .where(TimetableYear.calendar_id == calendar_id)
                .order_by(TimetableYear.school_year.desc())
            )
        )

    async def document(self, year: TimetableYear) -> YearDocument:
        """Assemble the compact live annual document."""
        rows = await self.db.scalars(
            select(TimetableSeries)
            .where(TimetableSeries.year_id == year.id)
            .order_by(TimetableSeries.id)
        )
        return YearDocument(
            settings=YearSettings.model_validate(year.settings),
            series=[SeriesData.model_validate(row.data) for row in rows],
        )

    async def teaching_documents(
        self, school_year: int, *, include_private: bool
    ) -> list[tuple[TimetableYear, YearDocument]]:
        """Load annual teaching sources in bulk, excluding removed agendas.

        Parameters
        ----------
        school_year
            Requested year after staff authorization.
        include_private
            Whether an administrator may include calendars with diffusion switched off.

        Returns
        -------
        list[tuple[TimetableYear, YearDocument]]
            Live annual documents using at most two queries, regardless of agenda count.
        """
        years = list(
            await self.db.scalars(
                select(TimetableYear)
                .join(TimetableCalendar)
                .where(
                    TimetableCalendar.is_archived.is_(False),
                    TimetableCalendar.is_paused.is_(False) if not include_private else True,
                    TimetableYear.school_year == school_year,
                )
            )
        )
        return [(year, document) for year, document in (await self.documents(years)).values()]

    async def documents(
        self, years: list[TimetableYear]
    ) -> dict[int, tuple[TimetableYear, YearDocument]]:
        """Load all compact series in one query, independent of occurrence and calendar counts."""
        by_year: dict[int, list[SeriesData]] = {}
        if years:
            for row in await self.db.scalars(
                select(TimetableSeries).where(
                    TimetableSeries.year_id.in_([year.id for year in years])
                )
            ):
                by_year.setdefault(row.year_id, []).append(SeriesData.model_validate(row.data))
        return {
            year.id: (
                year,
                YearDocument(
                    settings=YearSettings.model_validate(year.settings),
                    series=by_year.get(year.id, []),
                ),
            )
            for year in years
        }

    async def store_series_many(self, year_id: int, series: list[SeriesData]) -> None:
        """Upsert changed series in bounded batches inside the caller's transaction.

        Parameters
        ----------
        year_id
            Authorized annual calendar identifier.
        series
            New or changed records; unchanged historical series are omitted.

        Returns
        -------
        None
            Records are written without committing the surrounding transaction.
        """
        for offset in range(0, len(series), 250):
            statement = insert(TimetableSeries).values(
                [
                    {
                        "id": item.id,
                        "year_id": year_id,
                        "subject_id": item.subject_id,
                        "teacher_id": item.teacher_id,
                        "room_id": item.room_id,
                        "data": item.model_dump(mode="json"),
                    }
                    for item in series[offset : offset + 250]
                ]
            )
            await self.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[TimetableSeries.id],
                    set_={
                        field: getattr(statement.excluded, field)
                        for field in ("subject_id", "teacher_id", "room_id", "data")
                    },
                )
            )
