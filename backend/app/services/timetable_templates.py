"""Effective weekly versions that retain past occurrences and independent exceptions."""

from datetime import date, datetime, time, timedelta
from uuid import uuid4

from sqlalchemy import delete, select

from app.models import TimetableCalendar, TimetableSeries, TimetableTemplateVersion, TimetableYear
from app.schemas.timetable import (
    BlockFields,
    SeriesData,
    SessionFields,
    TemplateBlock,
    TemplateSave,
    YearDocument,
    YearSettings,
)
from app.services.auth import AuthService, UserContext
from app.services.errors import AuthError
from app.services.timetable import TimetableService
from app.services.timetable_engine import (
    PARIS,
    segments,
    series_dates,
    teaching_day,
    teaching_weeks,
    validate_series,
)


def template_blocks(document: YearDocument, on: date) -> list[TemplateBlock]:
    """Recover the effective legacy weekly organization without including dated-only events."""
    selected: dict[str, SeriesData] = {}
    for series in sorted(document.series, key=lambda item: item.starts_on):
        if (
            not series.interval
            or series.kind == "kholle"
            or series.target_kind not in {"promotion", "halves", "thirds"}
        ):
            continue
        key = series.template_key or series.lineage
        if series.until is not None and series.until < on:
            continue
        if key not in selected or series.starts_on <= on:
            selected[key] = series
    weeks = teaching_weeks(document.settings)
    return [
        TemplateBlock(
            **{field: getattr(series, field) for field in SessionFields.model_fields},
            key=key,
            weekday=series.starts_on.weekday(),
            interval=series.interval,
            phase=series.cycle_phase
            or (
                (weeks.get(series.starts_on - timedelta(days=series.starts_on.weekday()), 1) - 1)
                % series.interval
                + 1
            ),
        )
        for key, series in selected.items()
    ]


def template_series(
    block: TemplateBlock, settings: YearSettings, effective: date
) -> SeriesData | None:
    """Place a pattern on its first eligible date without shifting its global cycle phase."""
    day = max(settings.start, effective)
    day += timedelta(days=(block.weekday - day.weekday()) % 7)
    weeks = teaching_weeks(settings)
    while day <= settings.end:
        monday = day - timedelta(days=day.weekday())
        if teaching_day(day, settings) and (weeks[monday] - 1) % block.interval + 1 == block.phase:
            return SeriesData(
                **{field: getattr(block, field) for field in SessionFields.model_fields},
                starts_on=day,
                until=settings.end,
                interval=block.interval,
                cycle_phase=block.phase,
                id=uuid4().hex,
                lineage=block.key,
                template_key=block.key,
            )
        day += timedelta(weeks=1)
    return None


def apply_template(
    document: YearDocument, data: TemplateSave, *, adopt_legacy: bool
) -> YearDocument:
    """Replace future ordinary occurrences, retaining earlier dates, overrides and cancellations.

    Parameters
    ----------
    document
        Existing annual draft; never mutated in place.
    data
        Complete new weekly version and its effective civil date.
    adopt_legacy
        Adopt pre-workspace recurring series only during the first versioned edit.

    Returns
    -------
    YearDocument
        A complete draft with stable occurrence UIDs and all independent dated events.
    """
    if data.effective_on is None and data.effective_at is None:
        raise ValueError("Resolve immediate activation before applying a weekly template.")
    effective = data.effective_on or data.effective_at.astimezone(PARIS).date()
    instant = data.effective_at.astimezone(PARIS) if data.effective_at else None
    seconds = instant.hour * 3600 + instant.minute * 60 + instant.second if instant else 0
    output = []
    completed: list[SeriesData] = []
    ongoing: list[BlockFields] = []
    ongoing_uids: dict[str, str | None] = {}
    weeks = teaching_weeks(document.settings)
    retained: dict[str, list[tuple[date, BlockFields | None]]] = {}
    for original in document.series:
        source = original.model_copy(deep=True)
        if (
            source.kind == "kholle"
            or source.target_kind not in {"promotion", "halves", "thirds"}
            or (not source.template_key and not (adopt_legacy and source.interval))
        ):
            if source.kind == "kholle" or source.target_kind in {"kholles", "student"}:
                source.template_key = None
            output.append(source)
            continue
        key = source.template_key or source.lineage
        source.template_key = key
        future = [(day, value) for day, value in source.exceptions.items() if day >= effective]
        retained.setdefault(key, []).extend(future)
        source.exceptions = {
            day: value for day, value in source.exceptions.items() if day < effective
        }
        if seconds and effective in series_dates(original, document.settings, weeks=weeks):
            boundary = original.exceptions.get(effective, original)
            retain_exception = boundary is None
            if boundary is not None:
                actual_day = boundary.starts_on if effective in original.exceptions else effective
                spans = segments(boundary, document.settings)
                ending = datetime.combine(actual_day, time(), PARIS) + timedelta(
                    seconds=spans[-1][1]
                )
                if ending <= instant:
                    completed.append(
                        SeriesData(
                            **{
                                field: getattr(boundary, field)
                                for field in SessionFields.model_fields
                            },
                            starts_on=actual_day,
                            interval=0,
                            id=uuid4().hex,
                            lineage=key,
                            template_key=key,
                            uid_date=original.uid_date or effective,
                            first_uid=original.first_uid
                            if effective == original.starts_on
                            else None,
                        )
                    )
                elif actual_day == effective:
                    ongoing.append(boundary)
                    ongoing_uids[key] = (
                        original.first_uid if effective == original.starts_on else None
                    )
                else:
                    retain_exception = True
            if not retain_exception:
                retained[key] = [(day, value) for day, value in retained[key] if day != effective]
        if source.starts_on < effective:
            source.until = min(source.until or document.settings.end, effective - timedelta(days=1))
            output.append(source)
    new_boundary: list[SeriesData] = []
    for block in data.blocks:
        replacement = template_series(block, document.settings, effective)
        if replacement is None:
            continue
        available = set(series_dates(replacement, document.settings, weeks=weeks))
        remaining = []
        for day, override in retained.get(block.key, []):
            if day in available:
                replacement.exceptions[day] = override
            else:
                remaining.append((day, override))
        retained[block.key] = remaining
        if seconds and replacement.starts_on == effective:
            override = replacement.exceptions.get(effective, replacement)
            if override is None or override.starts_on != effective:
                output.append(replacement)
                continue
            spans = segments(replacement, document.settings)
            if spans[-1][1] <= seconds and not any(
                boundary_overlap(replacement, old, document.settings) for old in ongoing
            ):
                replacement.exceptions[effective] = None
            else:
                replacement.exceptions.pop(effective, None)
                new_boundary.append(replacement)
        output.append(replacement)
    for old in completed:
        if not any(
            new.starts_on == old.starts_on and boundary_overlap(old, new, document.settings)
            for new in new_boundary
        ):
            output.append(old)
    for new in new_boundary:
        if new.template_key in ongoing_uids:
            new.first_uid = ongoing_uids[new.template_key]
        elif any(old.template_key == new.template_key and old in output for old in completed):
            new.first_uid = uuid4().hex
    for key, exceptions in retained.items():
        for source_date, override in exceptions:
            if override is not None:
                output.append(
                    SeriesData(
                        **override.model_dump(),
                        id=uuid4().hex,
                        lineage=key,
                        interval=0,
                        uid_date=source_date,
                    )
                )
    if len(output) > 5000:
        raise AuthError(422, "Limite de séries et d’exceptions de cette année atteinte.")
    result = YearDocument(settings=document.settings, series=output)
    for series in result.series:
        validate_series(series, result.settings)
    return result


def boundary_overlap(left: SessionFields, right: SessionFields, settings: YearSettings) -> bool:
    """Return whether transition-day sessions share recipients and a teaching interval.

    Parameters
    ----------
    left, right
        Sessions whose civil date has already been matched.
    settings
        Daily slot and recess configuration.

    Returns
    -------
    bool
        False for distinct groups of one partition, otherwise true on a temporal overlap.
    """
    if left.target_kind == right.target_kind and left.target_kind in {"halves", "thirds"}:
        if left.target_number != right.target_number:
            return False
    return any(
        start < other_end and other_start < end
        for start, end in segments(left, settings)
        for other_start, other_end in segments(right, settings)
    )


class TimetableTemplateService:
    """Read pattern history and atomically append administrator-owned weekly versions."""

    def __init__(self, auth: AuthService) -> None:
        """Share the timetable service's request resources and lifecycle lock."""
        self.auth = auth
        self.db = auth.db
        self.core = TimetableService(auth)

    async def read(self, actor: UserContext, identifier: int) -> dict:
        """Expose an editable pattern and its immutable version dates to administrators only."""
        async with self.db.begin():
            await self.core.authorize(actor, write=True)
            year = await self.db.get(TimetableYear, identifier)
            if year is None:
                raise AuthError(404, "Année scolaire introuvable.")
            calendar = await self.db.get(TimetableCalendar, year.calendar_id)
            if calendar is None or calendar.is_deleted:
                raise AuthError(404, "Agenda introuvable.")
            versions = list(
                await self.db.scalars(
                    select(TimetableTemplateVersion)
                    .where(TimetableTemplateVersion.year_id == year.id)
                    .order_by(TimetableTemplateVersion.number)
                )
            )
            document = await self.core.repo.document(year)
            blocks = (
                [
                    block
                    for block in versions[-1].blocks
                    if block.get("kind") != "kholle"
                    and block.get("target_kind", "promotion") in {"promotion", "halves", "thirds"}
                ]
                if versions
                else [
                    block.model_dump(mode="json")
                    for block in template_blocks(
                        document, max(document.settings.start, self.core.today())
                    )
                ]
            )
            return {
                "revision": year.revision,
                "blocks": blocks,
                "versions": [
                    {
                        "number": version.number,
                        "effective_on": version.effective_on.isoformat(),
                        "effective_at": (
                            version.effective_at
                            or datetime.combine(version.effective_on, time(), PARIS)
                        ).isoformat(),
                    }
                    for version in versions
                ],
            }

    async def save(self, actor: UserContext, identifier: int, data: TemplateSave) -> dict:
        """Append a dated version and rebuild affected future occurrences atomically."""
        async with self.db.begin():
            year = await self.core._year(identifier, actor, data)
            calendar = await self.db.get(TimetableCalendar, year.calendar_id)
            if calendar.is_deleted:
                raise AuthError(404, "Agenda introuvable.")
            document = await self.core.repo.document(year)
            versions = list(
                await self.db.scalars(
                    select(TimetableTemplateVersion)
                    .where(TimetableTemplateVersion.year_id == year.id)
                    .order_by(TimetableTemplateVersion.number)
                )
            )
            previous_blocks = (
                [
                    TemplateBlock.model_validate(block)
                    for block in versions[-1].blocks
                    if block.get("kind") != "kholle"
                    and block.get("target_kind", "promotion") in {"promotion", "halves", "thirds"}
                ]
                if versions
                else template_blocks(document, max(document.settings.start, self.core.today()))
            )
            if {block.key: block.model_dump() for block in data.blocks} == {
                block.key: block.model_dump() for block in previous_blocks
            }:
                return {
                    "revision": year.revision,
                    "number": versions[-1].number if versions else None,
                    "changed": False,
                }
            now = self.auth.clock().astimezone(PARIS)
            effective_at = (
                data.effective_at.astimezone(PARIS)
                if data.effective_at
                else datetime.combine(data.effective_on, time(), PARIS)
                if data.effective_on
                else max(now, datetime.combine(document.settings.start, time(), PARIS))
            )
            effective_on = effective_at.date()
            if not document.settings.start <= effective_on <= document.settings.end:
                raise AuthError(422, "La date d’effet doit rester dans l’année scolaire.")
            if effective_at < now and not data.acknowledge_history:
                raise AuthError(
                    422,
                    "Confirmez l’application rétroactive : les séances de l’historique "
                    "seront remplacées à partir de cette date.",
                )
            for block in data.blocks:
                if block.weekday == 5 and not document.settings.saturday:
                    raise AuthError(422, "Le samedi est fermé dans les réglages communs.")
                previous = next((item for item in previous_blocks if item.key == block.key), None)
                await self.core._references(
                    block,
                    calendar,
                    allow_unavailable_teacher=bool(
                        previous and previous.teacher_id == block.teacher_id
                    ),
                )
                candidate = template_series(block, document.settings, effective_on)
                if candidate:
                    validate_series(candidate, document.settings)
            number = versions[-1].number + 1 if versions else 1
            if (
                not versions
                and any(series.interval for series in document.series)
                and effective_at > datetime.combine(document.settings.start, time(), PARIS)
            ):
                baseline = template_blocks(document, document.settings.start)
                self.db.add(
                    TimetableTemplateVersion(
                        year_id=year.id,
                        number=1,
                        effective_on=document.settings.start,
                        effective_at=datetime.combine(document.settings.start, time(), PARIS),
                        created_at=self.auth.clock(),
                        blocks=[block.model_dump(mode="json") for block in baseline],
                    )
                )
                number = 2
            updated = apply_template(
                document,
                data.model_copy(
                    update={"effective_on": effective_on, "effective_at": effective_at}
                ),
                adopt_legacy=not versions,
            )
            retained = {series.id for series in updated.series}
            await self.db.execute(
                delete(TimetableSeries).where(
                    TimetableSeries.year_id == year.id, TimetableSeries.id.not_in(retained)
                )
            )
            existing = {series.id: series.model_dump(mode="json") for series in document.series}
            await self.core.repo.store_series_many(
                year.id,
                [
                    series
                    for series in updated.series
                    if existing.get(series.id) != series.model_dump(mode="json")
                ],
            )
            self.db.add(
                TimetableTemplateVersion(
                    year_id=year.id,
                    number=number,
                    effective_on=effective_on,
                    effective_at=effective_at,
                    created_at=self.auth.clock(),
                    blocks=[block.model_dump(mode="json") for block in data.blocks],
                )
            )
            response = await self.core._changed(actor, year)
            return {
                **response,
                "number": number,
                "changed": True,
                "effective_at": effective_at.isoformat(),
            }
