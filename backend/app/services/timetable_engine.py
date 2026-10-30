"""Pure school-calendar arithmetic shared by live previews and personal subscriptions."""

from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.schemas.timetable import (
    SeriesData,
    SeriesFields,
    SessionFields,
    YearDocument,
    YearSettings,
)
from app.services.errors import AuthError

PARIS = ZoneInfo("Europe/Paris")


def current_school_year(day: date) -> int:
    """Return the academic label starting September 1 of the supplied local date."""
    return day.year - (day.month < 9)


def daily_slots(settings: YearSettings) -> list[tuple[int, int]]:
    """Return half-session spans with fresh phases at self opening and closing.

    Parameters
    ----------
    settings
        Validated daily bounds and breaks; one half-session uses integer seconds.

    Returns
    -------
    list[tuple[int, int]]
        Wall-clock spans; a half-session may itself straddle a pause without consuming it.
    """
    half = settings.session_minutes * 30
    boundaries = sorted(
        {settings.day_start, settings.lunch_start, settings.lunch_end, settings.day_end}
    )
    result = []
    for beginning, ending in zip(boundaries, boundaries[1:], strict=False):
        windows = []
        cursor = beginning
        for pause in sorted(settings.breaks, key=lambda item: item.start):
            left, right = max(beginning, pause.start), min(ending, pause.end)
            if left >= right:
                continue
            if cursor < left:
                windows.append((cursor, left))
            cursor = right
        if cursor < ending:
            windows.append((cursor, ending))

        def wall_time(
            offset: int,
            phase_windows: list[tuple[int, int]],
            phase_end: int,
            *,
            ending_slot: bool = False,
        ) -> int:
            """Map teaching seconds inside this phase to exact wall-clock boundaries."""
            for start, end in phase_windows:
                length = end - start
                if offset < length or (ending_slot and offset == length):
                    return start + offset
                offset -= length
            return phase_end

        total = sum(end - start for start, end in windows)
        result.extend(
            (
                wall_time(offset, windows, ending),
                wall_time(offset + half, windows, ending, ending_slot=True),
            )
            for offset in range(0, total - half + 1, half)
        )
    return result


def teaching_day(day: date, settings: YearSettings) -> bool:
    """Return whether a date is inside the year, open and outside inclusive holidays."""
    return (
        settings.start <= day <= settings.end
        and day.weekday() < (6 if settings.saturday else 5)
        and not any(holiday.start <= day <= holiday.end for holiday in settings.holidays)
    )


def teaching_weeks(settings: YearSettings) -> dict[date, int]:
    """Number weeks with at least one teaching day; full holiday weeks pause all cycles."""
    result: dict[date, int] = {}
    day = settings.start
    while day <= settings.end:
        monday = day - timedelta(days=day.weekday())
        if teaching_day(day, settings) and monday not in result:
            result[monday] = len(result) + 1
        day += timedelta(days=1)
    return result


def series_dates(
    series: SeriesData, settings: YearSettings, *, weeks: dict[date, int] | None = None
) -> list[date]:
    """Expand a bounded series on teaching-week phases, preserving vacation alternation."""
    if series.interval == 0:
        return [series.starts_on] if teaching_day(series.starts_on, settings) else []
    if weeks is None:
        weeks = teaching_weeks(settings)
    anchor = series.starts_on - timedelta(days=series.starts_on.weekday())
    # Retain the original anchor when new holidays hide its first occurrence or
    # the administrator moves the calendar's start date beyond it.
    cycle_weeks = (
        weeks
        if series.starts_on >= settings.start
        else teaching_weeks(settings.model_copy(update={"start": series.starts_on}))
    )
    anchor_number = sum(monday < anchor for monday in cycle_weeks) + 1
    stop = min(series.until or settings.end, settings.end)
    result = []
    day = series.starts_on
    while day <= stop:
        monday = day - timedelta(days=day.weekday())
        phase_matches = (cycle_weeks.get(monday, 0) - anchor_number) % series.interval == 0
        if teaching_day(day, settings) and phase_matches:
            result.append(day)
        day += timedelta(days=7)
    return result


def segments(
    block: SessionFields, settings: YearSettings, *, slots: list[tuple[int, int]] | None = None
) -> list[tuple[int, int]]:
    """Use exact free-time boundaries or merge selected teaching slots without counting gaps."""
    if block.start_time is not None:
        if not settings.day_start <= block.start_time < block.end_time <= settings.day_end:
            raise AuthError(422, "La séance doit rester dans les horaires d’ouverture.")
        return [(block.start_time, block.end_time)]
    if slots is None:
        slots = daily_slots(settings)
    end = block.start_slot + block.duration_slots
    if block.start_slot >= len(slots) or end > len(slots):
        raise AuthError(422, "Ce bloc dépasse les créneaux disponibles de la journée.")
    result: list[tuple[int, int]] = []
    for start, stop in slots[block.start_slot : end]:
        pieces = []
        for pause in sorted(settings.breaks, key=lambda item: item.start):
            if pause.end <= start or pause.start >= stop:
                continue
            if start < pause.start:
                pieces.append((start, pause.start))
            start = min(pause.end, stop)
        if start < stop:
            pieces.append((start, stop))
        for left, right in pieces:
            if result and result[-1][1] == left:
                result[-1] = (result[-1][0], right)
            else:
                result.append((left, right))
    return result


def validate_series(series: SeriesData, settings: YearSettings, *, existing: bool = False) -> None:
    """Refuse blocks outside open dates or slots and invalid exception source dates."""
    if not existing and not teaching_day(series.starts_on, settings):
        raise AuthError(422, "Choisissez un jour de cours hors vacances, dans l’année scolaire.")
    if (
        not existing
        and series.until is not None
        and not series.starts_on <= series.until <= settings.end
    ):
        raise AuthError(422, "La fin de répétition doit rester dans l’année scolaire.")
    segments(series, settings)
    for replacement in series.exceptions.values():
        if replacement:
            segments(replacement, settings)


def occurrences(document: YearDocument) -> list[dict]:
    """Expand stable dated segments without serializing member names or subscription secrets."""
    result = []
    weeks = teaching_weeks(document.settings)
    slots = daily_slots(document.settings)
    for series in document.series:
        for source in series_dates(series, document.settings, weeks=weeks):
            block = series.exceptions.get(source, series)
            if block is None:
                continue
            day = block.starts_on if source in series.exceptions else source
            if not teaching_day(day, document.settings):
                continue
            for index, (start, end) in enumerate(segments(block, document.settings, slots=slots)):
                base = datetime.combine(day, time(), PARIS)
                result.append(
                    {
                        "id": (
                            f"{series.uid_lineage or series.lineage}-"
                            f"{series.uid_date or source}-{index}"
                        )
                        if source == series.starts_on
                        else f"{series.lineage}-{source}-{index}",
                        "series_id": series.id,
                        "conflict_key": series.lineage,
                        "is_exception": source in series.exceptions,
                        "source_date": source.isoformat(),
                        "start": (base + timedelta(seconds=start)).isoformat(),
                        "end": (base + timedelta(seconds=end)).isoformat(),
                        "start_slot": block.start_slot,
                        "duration_slots": block.duration_slots,
                        "start_time": block.start_time,
                        "end_time": block.end_time,
                        "subject_id": block.subject_id,
                        "teacher_id": block.teacher_id,
                        "teacher_ids": block.teacher_ids,
                        "room_id": block.room_id,
                        "kind": block.kind,
                        "title": block.title,
                        "target_kind": block.target_kind,
                        "target_number": block.target_number,
                        "target_user_id": block.target_user_id,
                    }
                )
    return sorted(result, key=lambda item: (item["start"], item["id"]))


def apply_event_change(
    document: YearDocument,
    series_id: str | None,
    occurrence: date | None,
    scope: str,
    block: SeriesFields | None,
) -> YearDocument:
    """Apply the same validated change to an isolated preview or a document awaiting persistence.

    Parameters
    ----------
    document
        Current compact annual document; never mutated by this function.
    series_id, occurrence, scope, block
        Validated proposal: null series creates, null block cancels, future splits the series.

    Returns
    -------
    YearDocument
        A new document preserving earlier occurrences and separately mapped future exceptions.
    """
    result = document.model_copy(deep=True)
    if block is not None:
        if not teaching_day(block.starts_on, document.settings):
            raise AuthError(422, "Choisissez une date ouverte, hors vacances.")
        segments(block, document.settings)
    if series_id is None:
        if block is None:
            raise AuthError(422, "Une nouvelle séance doit contenir un événement.")
        key = uuid4().hex
        new = SeriesData(**block.model_dump(), id=key, lineage=key)
        validate_series(new, document.settings)
        result.series.append(new)
    else:
        source = next((item for item in result.series if item.id == series_id), None)
        if source is None or occurrence not in series_dates(source, document.settings):
            raise AuthError(404, "Occurrence introuvable.")
        if source.interval == 0:
            if block is None:
                result.series.remove(source)
            else:
                updated = SeriesData(
                    **block.model_dump(),
                    id=source.id,
                    lineage=source.lineage,
                    uid_lineage=source.uid_lineage,
                    uid_date=source.uid_date,
                )
                validate_series(updated, document.settings)
                result.series[result.series.index(source)] = updated
        elif scope == "one":
            source.exceptions[occurrence] = None
            if block is not None:
                key = uuid4().hex
                fields = block.model_dump()
                fields.update(interval=0, until=None)
                detached = SeriesData(
                    **fields, id=key, lineage=key, uid_lineage=source.lineage, uid_date=occurrence
                )
                validate_series(detached, document.settings)
                result.series.append(detached)
            if len(source.exceptions) > 100:
                raise AuthError(422, "Limite de 100 exceptions par série atteinte.")
            validate_series(source, document.settings, existing=True)
        else:
            future = {day: value for day, value in source.exceptions.items() if day > occurrence}
            if block is not None:
                key = uuid4().hex
                new = SeriesData(**block.model_dump(), id=key, lineage=source.lineage)
                if occurrence == source.starts_on:
                    new.uid_lineage, new.uid_date = source.uid_lineage, source.uid_date
                shift = block.starts_on - occurrence
                for day, replacement in future.items():
                    new.exceptions[day + shift] = replacement
                validate_series(new, document.settings)
                result.series.append(new)
            source.exceptions = {
                day: value for day, value in source.exceptions.items() if day < occurrence
            }
            if occurrence == source.starts_on:
                result.series.remove(source)
            else:
                source.until = occurrence - timedelta(days=1)
    if len(result.series) > 5000:
        raise AuthError(422, "Limite de 5000 séries par calendrier atteinte.")
    return result
