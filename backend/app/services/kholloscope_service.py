"""Deterministic A/B service shared by preparation and the placement solver."""

from fractions import Fraction
from math import lcm


def service_cycles(calendars: list[dict]) -> dict[int, int]:
    """Compute exact per-subject commitment periods from configured rates.

    Parameters
    ----------
    calendars
        Calendar rows with a teaching-week count and subject minute requirements.

    Returns
    -------
    dict[int, int]
        Smallest exact reference periods, retaining two weeks for weekly/fortnightly service.
    """
    periods: dict[int, int] = {}
    for calendar in calendars:
        weeks = calendar["weeks"]
        count = len(weeks) if isinstance(weeks, list) else weeks
        if not count:
            continue
        for subject in calendar["settings"]["subjects"]:
            if subject["minutes"] <= 0:
                continue
            period = Fraction(subject["minutes"], 60 * count).denominator
            identifier = subject["subject_id"]
            periods[identifier] = lcm(periods.get(identifier, 1), period)
    return {key: 2 if value <= 2 else value for key, value in periods.items()}


def occurrence_phases(minutes: int, weeks: int, horizon: int) -> list[int]:
    """Space reference occurrences evenly, anchoring sparse sessions near each wave's end.

    Parameters
    ----------
    minutes, weeks, horizon
        Annual pedagogical minutes, eligible weeks and common exact reference length.

    Returns
    -------
    list[int]
        Zero-based reference week indices, with floor/ceil gaps for noninteger intervals.
    """
    count = Fraction(minutes * horizon, 60 * weeks)
    if count.denominator != 1:
        raise ValueError("The reference horizon must cover the exact cadence.")
    total = int(count)
    if total == 0:
        return []
    if horizon <= 2 or total >= horizon or horizon == total * 2:
        return [index * horizon // total for index in range(total)]
    return [(index + 1) * horizon // total - 1 for index in range(total)]


def balanced_service(subjects: list[dict]) -> list[dict]:
    """Split exact fortnight commitments without sending every odd remainder into B.

    Parameters
    ----------
    subjects
        Subject/staff rows with stable numeric identifiers and optional session commitments.

    Returns
    -------
    list[dict]
        Copies in their original display order, with sessions_a/sessions_b. Each complete
        subject and the overall service differ by at most one session between A and B.
        Numeric identifiers break ties independently of names, rooms and search settings.
    """
    allocation: dict[tuple[int, int], tuple[int | None, int | None]] = {}
    total_a, total_b = 0, 0
    for subject in sorted(subjects, key=lambda row: row["id"]):
        people = subject["staff"]
        if any(person["sessions"] is None for person in people):
            for person in people:
                allocation[subject["id"], person["id"]] = (None, None)
            continue
        count = sum(person["sessions"] for person in people)
        target_a = count // 2 + int(count % 2 and total_a < total_b)
        extra = target_a - sum(person["sessions"] // 2 for person in people)
        odd = sorted((p["id"] for p in people if p["sessions"] % 2), reverse=True)
        rounded_up = set(odd[:extra])
        for person in people:
            a = person["sessions"] // 2 + int(person["id"] in rounded_up)
            b = person["sessions"] - a
            allocation[subject["id"], person["id"]] = (a, b)
        total_a += target_a
        total_b += count - target_a
    return [
        {
            **subject,
            "staff": [
                {
                    **person,
                    "sessions_a": allocation[subject["id"], person["id"]][0],
                    "sessions_b": allocation[subject["id"], person["id"]][1],
                }
                for person in subject["staff"]
            ],
        }
        for subject in subjects
    ]
