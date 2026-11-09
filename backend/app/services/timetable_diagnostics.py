"""Annual pupil hours, partition balance and continuous lunch availability."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from app.schemas.timetable import SeriesData, YearSettings
from app.services.timetable_engine import teaching_day, teaching_weeks


def kholle_diagnostics(
    events: list[dict],
    settings: YearSettings,
    requirements: dict | None,
    groups: list[dict],
    promotion_id: int | None,
    school_year: int,
) -> list[dict]:
    """Compare actual group kholles with annual targets and eligible fortnight cadences.

    Parameters
    ----------
    events, settings, requirements
        Live expanded sessions, calendar rules and configured pedagogical minute targets.
    groups, promotion_id, school_year
        Authorized group metadata and annual context.

    Returns
    -------
    list[dict]
        Nonblocking per-group volume and alternating-cycle warnings after live edits.
    """
    if not requirements:
        return []
    from app.services.kholle import kholle_weeks

    numbers = sorted(
        {
            g["number"]
            for g in groups
            if g["kind"] == "kholles" and g["promotion_id"] == promotion_id
        }
    )
    weeks = [
        w["start"]
        for w in kholle_weeks(settings, school_year)
        if w["eligible"] and requirements["start"] <= w["start"] <= requirements["end"]
    ]
    totals, cycles, weekly = defaultdict(float), defaultdict(float), defaultdict(float)
    issues = []
    for event in events:
        if event["kind"] != "kholle":
            continue
        targets = (
            numbers
            if event.get("target_kind") == "promotion"
            else ([event.get("target_number")] if event.get("target_kind") == "kholles" else [])
        )
        start, end = (datetime.fromisoformat(event[key]) for key in ("start", "end"))
        minutes = (end - start).total_seconds() / settings.session_minutes
        monday = (start.date() - timedelta(days=start.weekday())).isoformat()
        for group in targets:
            totals[group, event["subject_id"]] += minutes
            if monday in weeks:
                cycles[group, event["subject_id"], weeks.index(monday) // 2] += minutes
                weekly[group, event["subject_id"], monday] += minutes
    for subject in requirements["subjects"]:
        identifier, expected = subject["subject_id"], subject["minutes"]
        label = (
            next(
                (
                    e.get("subject_label", e.get("title"))
                    for e in events
                    if e["subject_id"] == identifier
                ),
                f"Matière {identifier}",
            )
            or f"Matière {identifier}"
        )
        cadence = expected * 2 / len(weeks) if weeks else 0
        for group in numbers:
            actual = totals[group, identifier]
            natural_partial_cycle = (
                len(weeks) % 2 == 1
                and abs(cadence - 60) < 1e-5
                and min(abs(actual - expected - 30), abs(actual - expected + 30)) < 1e-5
            )
            if abs(actual - expected) > 1e-5 and not natural_partial_cycle:
                issues.append(
                    {
                        "code": f"kholle-volume-{identifier}-{group}",
                        "severity": "warning",
                        "subject_id": identifier,
                        "kind": "kholle",
                        "message": f"Groupe {group} · {label} : {actual / 60:.2f} h de khôlle "
                        f"sur l’année, {expected / 60:.2f} h attendues.",
                    }
                )
            if cadence <= 0 or abs(cadence / 60 - round(cadence / 60)) > 1e-7:
                continue
            every_week = abs(cadence / 120 - round(cadence / 120)) < 1e-7
            irregular = (
                [
                    week
                    for week in weeks
                    if abs(weekly[group, identifier, week] - cadence / 2) > 1e-5
                ]
                if every_week
                else [
                    weeks[cycle * 2]
                    for cycle in range(len(weeks) // 2)
                    if abs(cycles[group, identifier, cycle] - cadence) > 1e-5
                ]
            )
            unit = "semaine(s)" if every_week else "cycle(s) A/B"
            if irregular:
                issues.append(
                    {
                        "code": f"kholle-alternation-{identifier}-{group}",
                        "severity": "warning",
                        "subject_id": identifier,
                        "kind": "kholle",
                        "message": f"Groupe {group} · {label} : alternance à vérifier sur "
                        f"{len(irregular)} {unit} (début : {', '.join(irregular[:6])}). "
                        "Vérifiez les déplacements et rattrapages.",
                    }
                )
    return issues


def recipients(event: dict, pupils: set[int], groups: dict[tuple[str, int], set[int]]) -> set[int]:
    """Resolve a session's current pupil audience without additional database reads."""
    kind = event.get("target_kind", "promotion")
    if kind == "promotion":
        return pupils
    if kind == "student":
        return pupils.intersection({event.get("target_user_id")})
    return pupils.intersection(groups.get((kind, event.get("target_number")), set()))


def largest_gap(intervals: list[tuple[int, int]], start: int, end: int) -> int:
    """Return the longest continuous free interval after merging intersecting bookings."""
    cursor, longest = start, 0
    for left, right in sorted(intervals):
        left, right = max(left, start), min(right, end)
        if left >= right:
            continue
        longest = max(longest, left - cursor)
        cursor = max(cursor, right)
    return max(longest, end - cursor)


def annual_diagnostics(
    events: list[dict],
    settings: YearSettings,
    members: list[dict],
    groups: list[dict],
    promotion_id: int | None,
    today: date,
    series: list[SeriesData] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Compute real annual hours and meal/balance issues from already-loaded occurrences.

    Parameters
    ----------
    events, settings
        Actual expanded segments and this calendar's immutable daily grid.
    members, groups, promotion_id
        Authorized roster; absent promotions use symbolic halves and thirds for totals.
    today
        First date for actionable lunch diagnostics; totals include the complete year.
    series
        Complete calendar blocks, including hidden occurrences, for option detection.

    Returns
    -------
    tuple[list[dict], list[dict]]
        Subject/type totals and weekly means, followed by structured nonblocking issues.
    """
    pupils = {
        member["id"]
        for member in members
        if "user" in member["roles"] and promotion_id in member["promotion_ids"]
    }
    partitions = {
        (group["kind"], group["number"]): set(group["student_ids"])
        for group in groups
        if group["promotion_id"] == promotion_id
    }
    audience_blocks = (
        (
            (block.subject_id, block.target_kind, block.target_number)
            for source in series
            for block in (source, *source.exceptions.values())
            if block is not None
        )
        if series is not None
        else (
            (event["subject_id"], event.get("target_kind", "promotion"), event.get("target_number"))
            for event in events
        )
    )
    subject_audiences: dict[int, set[str]] = defaultdict(set)
    option_pupils: dict[int, set[int]] = defaultdict(set)
    for subject_id, kind, number in audience_blocks:
        if subject_id is None:
            continue
        subject_audiences[subject_id].add(kind)
        if kind == "custom":
            option_pupils[subject_id].update(
                pupils.intersection(partitions.get((kind, number), set()))
            )
    option_subjects = {
        subject_id for subject_id, kinds in subject_audiences.items() if kinds == {"custom"}
    }
    totals: dict[int | None, dict] = {}
    loads: dict[tuple, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    bookings: dict[tuple[date, int], list[tuple[int, int]]] = defaultdict(list)
    active_days: set[date] = set()
    missing: set[tuple[str, int | None]] = set()
    divisor = settings.session_minutes if 55 <= settings.session_minutes <= 65 else 60
    for event in events:
        beginning, ending = (datetime.fromisoformat(event[key]) for key in ("start", "end"))
        day = beginning.date()
        duration = (ending - beginning).total_seconds() / (60 * divisor)
        audience = recipients(event, pupils, partitions)
        kind = event.get("target_kind", "promotion")
        if promotion_id is not None and kind != "promotion" and not audience:
            missing.add((kind, event.get("target_number")))
        if pupils:
            counted_pupils = (
                option_pupils[event["subject_id"]]
                if event["subject_id"] in option_subjects
                else pupils
            )
            factor = len(audience) / len(counted_pupils) if counted_pupils else 0.0
        else:
            factor = {"halves": 0.5, "thirds": 1 / 3}.get(kind, 1)
        row = totals.setdefault(
            event["subject_id"],
            {
                "subject_id": event["subject_id"],
                "course": 0.0,
                "td": 0.0,
                "tp": 0.0,
                "kholle": 0.0,
                "total": 0.0,
            },
        )
        row[event["kind"]] += duration * factor
        row["total"] += duration * factor
        if kind in {"halves", "thirds"}:
            loads[(event["subject_id"], event["kind"], kind)][event["target_number"]] += duration
        if day >= today:
            active_days.add(day)
            for pupil in audience:
                bookings[(day, pupil)].append(
                    (
                        beginning.hour * 3600 + beginning.minute * 60 + beginning.second,
                        ending.hour * 3600 + ending.minute * 60 + ending.second,
                    )
                )
    weeks = len(teaching_weeks(settings))
    result = []
    for row in totals.values():
        result.append(
            {
                **row,
                "weekly": {
                    key: value / weeks if weeks else 0.0
                    for key, value in row.items()
                    if key != "subject_id"
                },
            }
        )
    family_labels = {
        "halves": "demi-groupe",
        "thirds": "tiers de groupe",
        "kholles": "groupe de khôlle",
        "student": "élève individuel",
        "custom": "groupe personnalisé",
    }
    type_labels = {"course": "cours", "td": "TD", "tp": "TP", "kholle": "khôlles"}
    issues = [
        {
            "code": f"missing-{kind}-{number}",
            "severity": "warning",
            "message": f"Destinataires absents : {family_labels[kind]} {number or ''}. "
            "Vérifiez les groupes et les événements après réaffectation.",
        }
        for kind, number in sorted(missing, key=str)
    ]
    for (subject_id, kind, partition), values in loads.items():
        numbers = range(1, 3 if partition == "halves" else 4)
        hours = [values[number] for number in numbers]
        if max(hours) - min(hours) > 1e-6:
            cycles = sorted(
                {
                    item.interval
                    for item in series or []
                    if item.subject_id == subject_id
                    and item.kind == kind
                    and item.target_kind == partition
                    and item.interval > 1
                    and weeks % item.interval
                }
            )
            issues.append(
                {
                    "code": f"balance-{subject_id}-{kind}-{partition}",
                    "severity": "warning",
                    "message": next(
                        (
                            event.get("subject_label", f"Matière {subject_id}")
                            for event in events
                            if event["subject_id"] == subject_id
                        ),
                        "Sans matière",
                    )
                    + f" : déséquilibre annuel en {type_labels[kind]} entre "
                    + family_labels[partition]
                    + "s ("
                    + " / ".join(
                        f"{chr((64 if partition == 'halves' else 87) + index)} : {value:.2f} h"
                        for index, value in enumerate(hours, 1)
                    )
                    + ").",
                    "subject_id": subject_id,
                    "cycles": cycles,
                    "family": partition,
                    "kind": kind,
                    "groups": [
                        {
                            "label": chr((64 if partition == "halves" else 87) + index),
                            "hours": value,
                        }
                        for index, value in enumerate(hours, 1)
                    ],
                }
            )
    for day in sorted(active_days):
        if not teaching_day(day, settings):
            continue
        affected = [
            pupil
            for pupil in pupils
            if largest_gap(
                bookings[(day, pupil)],
                settings.lunch_start,
                settings.lunch_end,
            )
            < settings.session_minutes * 60
        ]
        if affected:
            issues.append(
                {
                    "code": f"lunch-{day}",
                    "severity": "critical",
                    "message": f"Repas le {day.isoformat()} : {len(affected)} élève(s) sans "
                    f"{settings.session_minutes} minutes consécutives libres pendant le self.",
                    "date": day.isoformat(),
                }
            )
    return sorted(result, key=lambda row: -row["total"]), issues
