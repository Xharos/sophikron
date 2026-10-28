"""Parameterized timetable persistence inside service-owned transactions."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Promotion,
    TimetableCalendar,
    TimetableSeries,
    TimetableTemplateVersion,
    TimetableYear,
    UserPromotion,
)
from app.schemas.timetable import SeriesData, YearDocument, YearSettings


class TimetableRepository:
    """Load annual documents and limit agendas to current promotion membership."""

    def __init__(self, db: AsyncSession) -> None:
        """Use the request's existing transaction-bound session."""
        self.db = db

    async def calendars(self, user_id: int | None) -> list[TimetableCalendar]:
        """Return all admin agendas or only agendas in the caller's active promotions."""
        statement = (
            select(TimetableCalendar)
            .where(TimetableCalendar.is_deleted.is_(False))
            .order_by(TimetableCalendar.name)
        )
        if user_id is not None:
            statement = (
                statement.join(Promotion)
                .join(UserPromotion)
                .where(UserPromotion.user_id == user_id, Promotion.is_active.is_(True))
            )
        return list(await self.db.scalars(statement))

    async def years(self, calendar_id: int) -> list[TimetableYear]:
        """Return an agenda's settings and publication records in school-year order."""
        return list(
            await self.db.scalars(
                select(TimetableYear)
                .where(TimetableYear.calendar_id == calendar_id)
                .order_by(TimetableYear.school_year.desc())
            )
        )

    async def document(self, year: TimetableYear) -> YearDocument:
        """Assemble the draft without mixing it with its last published snapshot."""
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
        self, school_year: int, *, draft: bool
    ) -> list[tuple[TimetableYear, YearDocument]]:
        """Load annual teaching sources in bulk, excluding removed agendas.

        Parameters
        ----------
        school_year
            Requested year after staff authorization.
        draft
            Whether the authorized administrator requested preparation documents.

        Returns
        -------
        list[tuple[TimetableYear, YearDocument]]
            Drafts or publications using at most two queries, regardless of agenda count.
        """
        years = list(
            await self.db.scalars(
                select(TimetableYear)
                .join(TimetableCalendar)
                .where(
                    TimetableCalendar.is_deleted.is_(False),
                    TimetableYear.school_year == school_year,
                )
            )
        )
        if not draft:
            return [
                (year, YearDocument.model_validate(year.published))
                for year in years
                if year.published is not None
            ]
        series_by_year: dict[int, list[SeriesData]] = {}
        for row in await self.db.scalars(
            select(TimetableSeries).where(TimetableSeries.year_id.in_([year.id for year in years]))
        ):
            series_by_year.setdefault(row.year_id, []).append(SeriesData.model_validate(row.data))
        return [
            (
                year,
                YearDocument(
                    settings=YearSettings.model_validate(year.settings),
                    series=series_by_year.get(year.id, []),
                ),
            )
            for year in years
        ]

    async def latest_templates(self, year_ids: set[int]) -> dict[int, TimetableTemplateVersion]:
        """Load the latest weekly version for each authorized year in one query.

        Parameters
        ----------
        year_ids
            Annual records already selected by the authorization service.

        Returns
        -------
        dict[int, TimetableTemplateVersion]
            Latest version per year; years without a version are absent.
        """
        latest = (
            select(
                TimetableTemplateVersion.year_id,
                func.max(TimetableTemplateVersion.number).label("number"),
            )
            .where(TimetableTemplateVersion.year_id.in_(year_ids))
            .group_by(TimetableTemplateVersion.year_id)
            .subquery()
        )
        rows = await self.db.scalars(
            select(TimetableTemplateVersion).join(
                latest,
                (TimetableTemplateVersion.year_id == latest.c.year_id)
                & (TimetableTemplateVersion.number == latest.c.number),
            )
        )
        return {version.year_id: version for version in rows}

    async def store_series(self, year_id: int, series: SeriesData) -> None:
        """Insert or replace one normalized series and its bounded exception document."""
        row = await self.db.get(TimetableSeries, series.id)
        if row is None:
            row = TimetableSeries(id=series.id, year_id=year_id)
            self.db.add(row)
        row.subject_id = series.subject_id
        row.teacher_id = series.teacher_id
        row.room_id = series.room_id
        row.data = series.model_dump(mode="json")
        await self.db.flush()

    async def store_series_many(self, year_id: int, series: list[SeriesData]) -> None:
        """Upsert changed series in bounded batches inside the caller's transaction.

        Parameters
        ----------
        year_id
            Authorized annual draft identifier.
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
