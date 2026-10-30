"""Pure weekly planning with paired labs and shared teacher/room collision checks."""

from dataclasses import dataclass

from .configuration import SeedError, Settings
from .identities import Person

# Full pedagogical sessions; none uses the self window or a recess.
PERIODS = (28800, 32100, 36600, 39900, 50400, 53700, 58200, 61500, 64800)


@dataclass(frozen=True)
class Lesson:
    """Keep a dated recurrence's references symbolic until API objects have been created."""

    calendar_index: int
    subject: str
    kind: str
    weekday: int
    period: int
    teacher: str
    room: str
    target_kind: str = "promotion"
    target_number: int | None = None


def build_plan(settings: Settings, staff: list[Person]) -> list[Lesson]:
    """Spread weekly hours over five days and keep both halves' labs on identical dates."""
    result: list[Lesson] = []
    loads: dict[tuple, float] = {}
    for calendar in settings.filled_calendar_indexes:
        for subject, kinds in settings.weekly_hours.items():
            pool = [
                person.email
                for person in staff
                if person.role == "teacher" and subject in person.subjects
            ]
            if sum(kinds.values()) and not pool:
                raise SeedError(f"Aucun professeur pour {subject}.")
            for kind, hours in kinds.items():
                for _ in range(hours):
                    paired = kind == "tp" and subject in settings.half_group_tp_subjects
                    placements = []
                    for day in range(5):
                        for period in range(len(PERIODS)):
                            first = available(
                                result,
                                calendar,
                                day,
                                period,
                                1 if paired else 3,
                                pool,
                                settings.rooms,
                            )
                            if first is None:
                                continue
                            teacher, room = first
                            bundle = [
                                Lesson(
                                    calendar,
                                    subject,
                                    kind,
                                    day,
                                    period,
                                    teacher,
                                    room,
                                    "halves" if paired else "promotion",
                                    1 if paired else None,
                                )
                            ]
                            if paired:
                                second = available(
                                    [*result, *bundle],
                                    calendar,
                                    day,
                                    period,
                                    2,
                                    pool,
                                    settings.rooms,
                                )
                                second_period = period
                                if second is None:
                                    second_period = next(
                                        (
                                            candidate
                                            for candidate in range(len(PERIODS))
                                            if available(
                                                [*result, *bundle],
                                                calendar,
                                                day,
                                                candidate,
                                                2,
                                                pool,
                                                settings.rooms,
                                            )
                                            is not None
                                        ),
                                        -1,
                                    )
                                    second = (
                                        available(
                                            [*result, *bundle],
                                            calendar,
                                            day,
                                            second_period,
                                            2,
                                            pool,
                                            settings.rooms,
                                        )
                                        if second_period >= 0
                                        else None
                                    )
                                if second is None:
                                    continue
                                bundle.append(
                                    Lesson(
                                        calendar,
                                        subject,
                                        kind,
                                        day,
                                        second_period,
                                        *second,
                                        "halves",
                                        2,
                                    )
                                )
                            score = (
                                loads.get((calendar, subject, day), 0),
                                loads.get((calendar, day), 0),
                                period,
                                day,
                            )
                            placements.append((score, bundle))
                    if not placements:
                        raise SeedError(
                            "Impossible de placer ces volumes sans conflit ; "
                            "réduisez les volumes ou ajoutez des professeurs/salles."
                        )
                    _, chosen = min(placements, key=lambda item: item[0])
                    result.extend(chosen)
                    day = chosen[0].weekday
                    loads[(calendar, subject, day)] = loads.get((calendar, subject, day), 0) + 1
                    loads[(calendar, day)] = loads.get((calendar, day), 0) + 1
        if settings.german_option_hours:
            pool = [
                person.email
                for person in staff
                if person.role == "teacher" and "german" in person.subjects
            ]
            for _ in range(settings.german_option_hours):
                match = next(
                    (
                        (day, period, chosen)
                        for day in range(5)
                        for period in range(len(PERIODS))
                        if (
                            chosen := available(
                                result, calendar, day, period, 3, pool, settings.rooms
                            )
                        )
                        is not None
                    ),
                    None,
                )
                if match is None:
                    raise SeedError("Impossible de placer l’option allemand.")
                day, period, chosen = match
                result.append(Lesson(calendar, "german", "course", day, period, *chosen, "custom"))
    return result


def available(
    lessons: list[Lesson],
    calendar: int,
    day: int,
    period: int,
    mask: int,
    teachers: list[str],
    rooms: tuple[str, ...],
) -> tuple[str, str] | None:
    """Return a free teacher/room pair while respecting full-class and half-class audiences."""
    occupied = [lesson for lesson in lessons if lesson.weekday == day and lesson.period == period]
    if any(
        lesson.calendar_index == calendar
        and mask & (lesson.target_number if lesson.target_kind == "halves" else 3)
        for lesson in occupied
    ):
        return None
    for teacher in sorted(
        teachers, key=lambda email: sum(lesson.teacher == email for lesson in lessons)
    ):
        if any(lesson.teacher == teacher for lesson in occupied):
            continue
        room = next(
            (room for room in rooms if not any(lesson.room == room for lesson in occupied)),
            None,
        )
        if room is not None:
            return teacher, room
    return None
