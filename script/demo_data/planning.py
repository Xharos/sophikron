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
    """Place double sessions first, then odd remainders late in the week.

    Parameters
    ----------
    settings
        Per-year class counts, weekly pedagogical hours and shared rooms.
    staff
        Specialists with their explicit class assignment or shared teaching scope.

    Returns
    -------
    list[Lesson]
        Collision-free individual sessions, merged into double blocks when exported.
    """
    tasks = []
    for calendar in settings.calendar_indexes():
        cohort = settings.classes()[calendar].identifier
        for subject, kinds in {
            **settings.weekly_hours,
            **(
                {"german": {"course": settings.german_option_hours}}
                if settings.german_option_hours
                else {}
            ),
        }.items():
            pool = [
                p.email
                for p in staff
                if p.role == "teacher" and subject in p.subjects and p.promotion in (None, cohort)
            ]
            for kind, hours in kinds.items():
                for length in [2] * (hours // 2) + [1] * (hours % 2):
                    tasks.append((calendar, subject, kind, length, pool))
    # Shared teachers have the tightest inter-class constraints.
    tasks.sort(key=lambda t: (-t[3], t[1] not in {"english", "french", "german"}, t[0]))
    result = []
    for calendar, subject, kind, length, pool in tasks:
        paired = kind == "tp" and subject in settings.half_group_tp_subjects
        candidates = []
        for day in range(5):
            for period in range(len(PERIODS) - length + 1):
                if length == 2 and period == 3:  # Never bridge the self window.
                    continue
                for teacher in pool:
                    for room in settings.rooms:
                        bundle = []
                        targets = (1, 2) if paired else (None,)
                        for target in targets:
                            possible = []
                            for first in (
                                [period] if target != 2 else range(len(PERIODS) - length + 1)
                            ):
                                if length == 2 and first == 3:
                                    continue
                                if all(
                                    available(
                                        result + bundle,
                                        calendar,
                                        day,
                                        first + offset,
                                        target or 3,
                                        [teacher],
                                        (room,),
                                    )
                                    is not None
                                    for offset in range(length)
                                ):
                                    possible.append(first)
                            if not possible:
                                break
                            first = possible[0]
                            bundle.extend(
                                Lesson(
                                    calendar,
                                    subject,
                                    kind,
                                    day,
                                    first + offset,
                                    teacher,
                                    room,
                                    "halves"
                                    if paired
                                    else ("custom" if subject == "german" else "promotion"),
                                    target,
                                )
                                for offset in range(length)
                            )
                        if len(bundle) == length * len(targets):
                            load = sum(
                                lesson.calendar_index == calendar and lesson.weekday == day
                                for lesson in result
                            )
                            score = (load, day, period) if length == 2 else (-day, -period, load)
                            candidates.append((score, bundle))
        if not candidates:
            raise SeedError(
                f"Impossible de placer {subject} pour {settings.classes()[calendar].identifier}. "
                "Ajoutez des salles ou réduisez les volumes."
            )
        result.extend(min(candidates, key=lambda item: item[0])[1])
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
