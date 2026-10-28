"""Pure school-calendar arithmetic shared by previews and published subscriptions."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.timetable import SeriesData, SessionFields, YearDocument, YearSettings
from app.services.errors import AuthError

PARIS = ZoneInfo("Europe/Paris")


def daily_slots(settings: YearSettings) -> list[tuple[int, int]]:
    """Return complete half-session spans measured exclusively in teaching seconds.

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
    pauses = sorted(settings.breaks, key=lambda item: item.start)
    windows = []
    cursor = settings.day_start
    for pause in pauses:
        windows.append((cursor, pause.start))
        cursor = pause.end
    windows.append((cursor, settings.day_end))
    windows = [(start, end) for start, end in windows if end > start]

    def wall_time(offset: int, *, ending: bool = False) -> int:
        """Map teaching seconds to wall time, choosing the correct side of a pause."""
        for start, end in windows:
            length = end - start
            if offset < length or (ending and offset == length):
                return start + offset
            offset -= length
        return settings.day_end

    total = sum(end - start for start, end in windows)
    return [
        (wall_time(offset), wall_time(offset + half, ending=True))
        for offset in range(0, total - half + 1, half)
    ]


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
    if anchor not in weeks:
        return []
    stop = min(series.until or settings.end, settings.end)
    result = []
    day = series.starts_on
    while day <= stop:
        monday = day - timedelta(days=day.weekday())
        phase_matches = (
            (weeks.get(monday, 0) - 1) % series.interval + 1 == series.cycle_phase
            if series.cycle_phase
            else (weeks.get(monday, 0) - weeks[anchor]) % series.interval == 0
        )
        if teaching_day(day, settings) and phase_matches:
            result.append(day)
        day += timedelta(days=7)
    return result


def segments(
    block: SessionFields, settings: YearSettings, *, slots: list[tuple[int, int]] | None = None
) -> list[tuple[int, int]]:
    """Consume teaching half-slots, merging adjacent slots and splitting at pauses."""
    if slots is None:
        slots = daily_slots(settings)
    end = block.start_slot + block.duration_slots
    if block.start_slot >= len(slots) or end > len(slots):
        raise AuthError(422, "Ce bloc dépasse les créneaux disponibles de la journée.")
    start, stop = slots[block.start_slot][0], slots[end - 1][1]
    result: list[tuple[int, int]] = []
    for pause in sorted(settings.breaks, key=lambda item: item.start):
        if pause.end <= start or pause.start >= stop:
            continue
        if start < pause.start:
            result.append((start, pause.start))
        start = pause.end
    if start < stop:
        result.append((start, stop))
    return result


def validate_series(series: SeriesData, settings: YearSettings) -> None:
    """Refuse blocks outside open dates or slots and invalid exception source dates."""
    if not teaching_day(series.starts_on, settings):
        raise AuthError(422, "Choisissez un jour de cours hors vacances, dans l’année scolaire.")
    if series.until is not None and not series.starts_on <= series.until <= settings.end:
        raise AuthError(422, "La fin de répétition doit rester dans l’année scolaire.")
    segments(series, settings)
    dates = set(series_dates(series, settings))
    for source, replacement in series.exceptions.items():
        if source not in dates:
            raise AuthError(422, "Une exception ne correspond plus à sa série. Ajustez-la d’abord.")
        if replacement:
            if not teaching_day(replacement.starts_on, settings):
                raise AuthError(422, "Une occurrence déplacée doit rester sur un jour de cours.")
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
            uid = (
                series.first_uid
                if source == series.starts_on and series.first_uid
                else series.lineage
            )
            for index, (start, end) in enumerate(segments(block, document.settings, slots=slots)):
                base = datetime.combine(day, time(), PARIS)
                result.append(
                    {
                        "id": f"{uid}-{(series.uid_date or source).isoformat()}-{index}",
                        "series_id": series.id,
                        "conflict_key": series.template_key or series.lineage,
                        "template_key": series.template_key,
                        "is_exception": source in series.exceptions,
                        "source_date": source.isoformat(),
                        "start": (base + timedelta(seconds=start)).isoformat(),
                        "end": (base + timedelta(seconds=end)).isoformat(),
                        "start_slot": block.start_slot,
                        "duration_slots": block.duration_slots,
                        "subject_id": block.subject_id,
                        "teacher_id": block.teacher_id,
                        "room_id": block.room_id,
                        "kind": block.kind,
                        "title": block.title,
                        "target_kind": block.target_kind,
                        "target_number": block.target_number,
                        "target_user_id": block.target_user_id,
                    }
                )
    return sorted(result, key=lambda item: (item["start"], item["id"]))


def cycle_warnings(document: YearDocument) -> list[str]:
    """Report incomplete teaching cycles without dropping or changing any occurrence."""
    count = len(teaching_weeks(document.settings))
    return [
        f"{count} semaines de cours : cycle de {interval} semaines incomplet en fin d’année. "
        "Vérifiez la dernière semaine et les exceptions."
        for interval in sorted(
            {series.interval for series in document.series if series.interval > 1}
        )
        if count % interval
    ]
