"""Aggregate pupil occupancy without exposing rosters outside the backend."""

from collections import Counter, defaultdict
from datetime import datetime

from app.services.timetable_engine import PARIS


def _full_class_intervals(
    events: list[dict], pupils: set[int], groups: dict[tuple[str, int], set[int]]
) -> dict[str, list[tuple[int, int]]]:
    """Find dated intervals covering the entire roster, preserving overlaps and group intersections.

    Parameters
    ----------
    events
        Actual teaching segments from one calendar, including recurrence exceptions.
    pupils, groups
        Current pupil roster and group memberships; never returned to the caller.

    Returns
    -------
    dict[str, list[tuple[int, int]]]
        Disjoint full-class intervals keyed by local school date. Without a roster only
        an explicit whole-class event can prove complete occupancy.
    """
    bits = {identifier: 1 << index for index, identifier in enumerate(sorted(pupils))}
    complete = (1 << len(bits)) - 1 if bits else 1
    edges: dict[str, dict[int, Counter[int]]] = defaultdict(lambda: defaultdict(Counter))
    for event in events:
        kind = event.get("target_kind", "promotion")
        if kind == "promotion":
            mask = complete
        else:
            audience = (
                {event.get("target_user_id")}
                if kind == "student"
                else groups.get((kind, event.get("target_number")), set())
            )
            mask = sum(bits.get(identifier, 0) for identifier in audience)
        if not mask:
            continue
        start, end = (
            datetime.fromisoformat(event[field]).astimezone(PARIS) for field in ("start", "end")
        )
        day = start.date().isoformat()
        first, last = (
            value.hour * 3600 + value.minute * 60 + value.second for value in (start, end)
        )
        last += (end.date() - start.date()).days * 86400
        edges[day][first][mask] += 1
        edges[day][last][mask] -= 1
    result: dict[str, list[tuple[int, int]]] = {}
    for day, points in edges.items():
        active: Counter[int] = Counter()
        previous: int | None = None
        covered = 0
        intervals: list[tuple[int, int]] = []
        for instant, changes in sorted(points.items()):
            if previous is not None and previous < instant and covered == complete:
                if intervals and intervals[-1][1] == previous:
                    intervals[-1] = (intervals[-1][0], instant)
                else:
                    intervals.append((previous, instant))
            active.update(changes)
            covered = 0
            for mask, count in active.items():
                if count > 0:
                    covered |= mask
            previous = instant
        if intervals:
            result[day] = intervals
    return result


def fully_occupied_ranges(
    events: dict[int, list[dict]],
    pupils: dict[int, set[int]],
    groups: dict[int, dict[tuple[str, int], set[int]]],
) -> list[dict]:
    """Intersect calendars on actual dates, then union blocked slots onto the weekly pattern.

    Parameters
    ----------
    events
        All participating active calendars, including calendars with no events.
    pupils, groups
        Roster and audience memberships keyed by calendar ID.

    Returns
    -------
    list[dict]
        Weekday/start/end ranges where every calendar's pupils are simultaneously busy
        on at least one actual school date; no calendars means no blocked range.
    """
    if not events:
        return []
    edges: dict[str, Counter[int]] = defaultdict(Counter)
    for identifier, sessions in events.items():
        intervals = _full_class_intervals(
            sessions, pupils.get(identifier, set()), groups.get(identifier, {})
        )
        if not intervals:
            return []
        for day, ranges in intervals.items():
            for start, end in ranges:
                edges[day][start] += 1
                edges[day][end] -= 1
    blocked = []
    for day, points in edges.items():
        active = 0
        previous: int | None = None
        for instant, change in sorted(points.items()):
            if previous is not None and previous < instant and active == len(events):
                blocked.append(
                    {
                        "weekday": datetime.fromisoformat(day).weekday(),
                        "start": previous,
                        "end": instant,
                    }
                )
            active += change
            previous = instant
    merged: list[dict] = []
    for item in sorted(blocked, key=lambda value: (value["weekday"], value["start"], value["end"])):
        if (
            merged
            and merged[-1]["weekday"] == item["weekday"]
            and merged[-1]["end"] >= item["start"]
        ):
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
        else:
            merged.append(item)
    return merged
