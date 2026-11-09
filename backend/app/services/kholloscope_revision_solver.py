"""Repair real future group sessions while preserving the annual published entitlement."""

import threading
import time
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from datetime import date, timedelta

from app.schemas.kholloscope_generation import GenerationRules
from app.services.kholloscope_solver import (
    GenerationError,
    candidates,
    free_lunch,
    overlaps,
    solve_choices,
)

FIELDS = ("day", "start", "end", "room_id", "teacher_id")


def revised_entitlement(snapshot: dict, baseline: list[dict], boundary: str) -> list[dict]:
    """Keep acquired volumes and extend future cadence to newly active groups only."""
    retired = set(snapshot.get("retired_groups", []))
    result = [
        deepcopy(s)
        for s in baseline
        if s["day"] < boundary or f"{s['calendar_id']}:{s['group']}" not in retired
    ]
    for entry in snapshot.get("added_groups", []):
        calendar, group = entry["calendar_id"], entry["group"]
        references = {}
        for session in baseline:
            if session["calendar_id"] == calendar:
                subject = session["subject_id"]
                references[subject] = min(
                    references.get(subject, session["group"]), session["group"]
                )
        if not references:
            raise GenerationError("Aucune cadence publiée disponible pour le nouveau groupe.")
        for session in baseline:
            if (
                session["calendar_id"] == calendar
                and session["group"] == references[session["subject_id"]]
                and session["day"] >= boundary
            ):
                result.append(
                    {
                        **deepcopy(session),
                        "id": f"new-{calendar}-{group}-{session['id']}",
                        "group": group,
                        "track": group,
                    }
                )
    return result


def revision_subjects(snapshot: dict) -> list[int]:
    """Read the selected subjects, including legacy single-subject branches."""
    return snapshot.get("subject_ids", [snapshot["subject_id"]])


def retained_session(snapshot: dict, session: dict) -> bool:
    """Retain all history and only active groups after the effective boundary."""
    return session["day"] < snapshot["effective_on"] or (
        f"{session['calendar_id']}:{session['group']}" not in snapshot.get("retired_groups", [])
    )


def revision_changes(snapshot: dict, annual: list[dict]) -> list[dict]:
    """Describe edits and future-only removals while rejecting removal of history."""
    before = {s["id"]: s for s in snapshot["live_sessions"]}
    after = {s["id"]: s for s in annual}
    changes = [
        {"before": before.get(s["id"]), "after": s}
        for s in annual
        if s["id"] not in before or any(s[k] != before[s["id"]][k] for k in FIELDS)
    ]
    for identifier, session in before.items():
        if identifier not in after:
            if retained_session(snapshot, session):
                raise GenerationError("Une séance conservée ne peut pas être supprimée.")
            changes.append({"before": session, "after": None})
    return changes


def in_revision_period(snapshot: dict, day: str) -> bool:
    """Return whether a civil date belongs to the half-open replacement period."""
    return day >= snapshot["effective_on"] and (
        not snapshot.get("return_on") or day < snapshot["return_on"]
    )


def entitlement(sessions: list[dict]) -> Counter:
    """Count pedagogical sessions by calendar, actual group and subject."""
    return Counter((s["calendar_id"], s["group"], s["subject_id"]) for s in sessions)


def future_service(total: int, wishes: list[dict]) -> dict[str, int]:
    """Allocate the remaining sessions proportionally using deterministic largest remainders.

    Parameters
    ----------
    total, wishes
        Required remaining whole sessions and nonnegative cycle commitments.

    Returns
    -------
    dict[str, int]
        Exact whole-session future totals, including zero commitments.
    """
    weight = sum(w["sessions"] for w in wishes)
    if total and not weight:
        raise GenerationError("Aucun service disponible pour les séances restantes.")
    result = {str(w["user_id"]): total * w["sessions"] // max(1, weight) for w in wishes}
    order = sorted(wishes, key=lambda w: (-(total * w["sessions"] % max(1, weight)), w["user_id"]))
    for wish in order[: total - sum(result.values())]:
        result[str(wish["user_id"])] += 1
    return result


def group_bookings(snapshot: dict, task: dict) -> dict:
    """Include shared-pupil courses in the conservative promotion occupancy filter."""
    pupils = set(snapshot["group_pupils"].get(f"{task['calendar_id']}:{task['group']}", []))
    return {
        **snapshot,
        "bookings": {
            day: [
                {**e, "calendar_id": task["calendar_id"]}
                if pupils.intersection(e.get("pupils", []))
                else e
                for e in events
            ]
            for day, events in snapshot["bookings"].items()
        },
    }


def revision_tasks(snapshot: dict) -> list[dict]:
    """Retain live future tasks and add only missing annual entitlements per real group."""
    boundary, subjects = snapshot["effective_on"], revision_subjects(snapshot)
    live = [s for s in snapshot["live_sessions"] if retained_session(snapshot, s)]
    expected, actual = entitlement(snapshot["entitlement"]), entitlement(live)
    if any(actual[key] > expected[key] for key in actual):
        raise GenerationError(
            "Le planning contient un excédent annuel. Corrigez-le avant la révision."
        )
    tasks = [deepcopy(s) for s in live if s["day"] >= boundary]
    for key, target in expected.items():
        missing = target - actual[key]
        if missing and key[2] not in subjects:
            raise GenerationError(
                "Une autre matière présente un déficit annuel : révision bloquée."
            )
        sources = [
            s
            for s in snapshot["entitlement"]
            if (s["calendar_id"], s["group"], s["subject_id"]) == key
        ]
        for index in range(missing):
            source = deepcopy(sources[-1 - index])
            source.update(id=f"added-{key[0]}-{key[1]}-{key[2]}-{index}", added=True)
            tasks.append(source)
    if len(tasks) > 20000:
        raise GenerationError("Limite technique de 20 000 séances atteinte.", "failed")
    return tasks


def revision_options(snapshot: dict, task: dict, rules: GenerationRules) -> list[dict]:
    """Prefer the exact live slot; permit additions and explicitly authorized same-week moves."""
    subject = task["subject_id"]
    if subject not in revision_subjects(snapshot) or (
        not task.get("added") and not in_revision_period(snapshot, task["day"])
    ):
        return [{key: task[key] for key in FIELDS}]
    calendar = next(c for c in snapshot["calendars"] if c["id"] == task["calendar_id"])
    cfg = {**calendar, "subject_id": subject}
    context = group_bookings(snapshot, task)
    teachers = [int(t) for t, count in snapshot["future_service"][str(subject)].items() if count]
    original = date.fromisoformat(task["day"])
    monday = original - timedelta(days=original.weekday())
    days = [original]
    if task.get("added"):
        days = [
            date.fromisoformat(w["start"]) + timedelta(days=d)
            for w in calendar["weeks"]
            if w["start"] >= snapshot["effective_on"]
            for d in range(6)
        ]
    elif snapshot["allow_moves"]:
        days = [monday + timedelta(days=d) for d in range(6)]
    options = []
    for day in days:
        if not (
            in_revision_period(snapshot, day.isoformat())
            and calendar["period_start"] <= day.isoformat() <= calendar["period_end"]
        ):
            continue
        for teacher in teachers:
            for option in candidates(context, cfg, teacher, day):
                moved = any(option[k] != task[k] for k in ("day", "start", "end"))
                if not task.get("added") and not snapshot["allow_moves"] and moved:
                    continue
                # One displaced session outweighs every teacher/room change in the branch.
                option["cost"] = (
                    int(moved and not task.get("added")) * (len(snapshot["live_sessions"]) + 1) * 10
                    + int(option["teacher_id"] != task["teacher_id"]) * 3
                    + int(option["room_id"] != task["room_id"])
                )
                options.append(option)
    return options


def validate_revision(snapshot: dict, sessions: list[dict], rules: GenerationRules) -> list[dict]:
    """Independently reject quota loss, frozen edits, conflicts, invalid resources and meals.

    Parameters
    ----------
    snapshot, sessions, rules
        Immutable live baseline, complete future proposal and bounded constraints.

    Returns
    -------
    list[dict]
        Full annual sessions with acquired history preserved verbatim.
    """
    tasks = revision_tasks(snapshot)
    if Counter(s["id"] for s in sessions) != Counter(s["id"] for s in tasks):
        raise GenerationError("La proposition ne couvre pas exactement les séances attendues.")
    sources = {s["id"]: s for s in tasks}
    for session in sessions:
        if snapshot.get("subject_ids") and session["teacher_id"] not in {
            p["id"] for subject in snapshot["subjects"] for p in subject["staff"]
        }:
            raise GenerationError("Un intervenant archivé ne peut pas assurer une séance future.")
        source = sources[session["id"]]
        if any(session[k] != source[k] for k in ("calendar_id", "group", "track", "subject_id")):
            raise GenerationError("La révision ne peut pas changer les groupes ou les matières.")
        if session["day"] < snapshot["effective_on"]:
            raise GenerationError("Une séance précède la prise d'effet.")
        if not any(
            all(o[k] == session[k] for k in FIELDS)
            for o in revision_options(snapshot, source, rules)
        ):
            raise GenerationError(
                "Une séance modifie un créneau figé ou utilise une ressource indisponible."
            )
    for subject in revision_subjects(snapshot):
        counts = Counter(
            s["teacher_id"]
            for s in sessions
            if s["subject_id"] == subject and in_revision_period(snapshot, s["day"])
        )
        if any(counts[int(t)] != n for t, n in snapshot["future_service"][str(subject)].items()):
            raise GenerationError("Le service futur n'est pas respecté.")
    history = [s for s in snapshot["live_sessions"] if s["day"] < snapshot["effective_on"]]
    annual = history + sessions
    if entitlement(annual) != entitlement(snapshot["entitlement"]):
        raise GenerationError("Le volume annuel de chaque groupe n'est pas couvert exactement.")
    by_day = {}
    for session in sessions:
        by_day.setdefault(session["day"], []).append(session)
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    for day, rows in by_day.items():
        resources = {}
        for i, s in enumerate(rows):
            pupils = set(snapshot["group_pupils"].get(f"{s['calendar_id']}:{s['group']}", []))
            for other in rows[i + 1 :]:
                shared = pupils.intersection(
                    snapshot["group_pupils"].get(f"{other['calendar_id']}:{other['group']}", [])
                )
                if overlaps(s["start"], s["end"], other["start"], other["end"]) and (
                    s["teacher_id"] == other["teacher_id"]
                    or shared
                    or (s["calendar_id"], s["group"]) == (other["calendar_id"], other["group"])
                ):
                    raise GenerationError("Chevauchement d'intervenant ou d'élèves.")
            room = s["room_id"]
            simultaneous = sum(
                o["room_id"] == room and o["start"] <= s["start"] < o["end"] for o in rows
            )
            existing = sum(
                o["room_id"] == room and o["start"] <= s["start"] < o["end"]
                for o in snapshot["bookings"].get(day, [])
            )
            if simultaneous + existing > snapshot["capacities"].get(str(room), 0):
                raise GenerationError("Capacité simultanée de salle dépassée.")
            resources.setdefault((s["calendar_id"], s["group"]), []).append(s)
        for (calendar, group), group_rows in resources.items():
            cfg = calendars[calendar]["settings"]
            if len(group_rows) > rules.max_per_day:
                raise GenerationError("Trop de khôlles le même jour pour un groupe.")
            pupils = set(snapshot["group_pupils"].get(f"{calendar}:{group}", []))
            busy = [(s["start"], s["end"]) for s in group_rows]
            busy += [
                (e["start"], e["end"])
                for e in snapshot["bookings"].get(day, [])
                if e["calendar_id"] == calendar or pupils.intersection(e.get("pupils", []))
            ]
            busy += [
                (s["start"], s["end"])
                for s in rows
                if s["calendar_id"] != calendar
                and pupils.intersection(
                    snapshot["group_pupils"].get(f"{s['calendar_id']}:{s['group']}", [])
                )
            ]
            if not free_lunch(
                busy,
                cfg.get("lunch_start", 43200),
                cfg.get("lunch_end", 50400),
                cfg["session_minutes"] * 60,
            ):
                raise GenerationError("Pause repas des élèves insuffisante.")
        if rules.teacher_lunch:
            for teacher in {s["teacher_id"] for s in rows}:
                busy = [(s["start"], s["end"]) for s in rows if s["teacher_id"] == teacher]
                busy += [
                    (e["start"], e["end"])
                    for e in snapshot["bookings"].get(day, [])
                    if teacher in e["teachers"]
                ]
                if not free_lunch(busy, 43200, 50400, rules.teacher_lunch_minutes * 60):
                    raise GenerationError("Pause repas d'un intervenant insuffisante.")
    return annual


def generate_revision(
    snapshot: dict, options: dict, log: Callable[[str], None], stop: threading.Event
) -> dict:
    """Compute one complete branch; never return a publishable partial repair."""
    rules = GenerationRules.from_saved_options(options)
    deadline = time.monotonic() + rules.time_limit
    log("Révision : passé acquis, groupes conservés, autres matières figées.")
    tasks = revision_tasks(snapshot)
    choices, total = [], 0
    fixed = {**snapshot, "allow_moves": False}
    for task in tasks:
        if stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        options_for_task = revision_options(fixed, task, rules)
        choices.append(options_for_task)
        total += len(options_for_task)
        if total > 250000:
            raise GenerationError("Limite technique de combinaisons atteinte.", "failed")
    blocked = {i for i, options_for_task in enumerate(choices) if not options_for_task}
    stages = [set()]
    if snapshot["allow_moves"]:
        if blocked:
            stages.append(blocked)
        stages.append(
            {i for i, task in enumerate(tasks) if task["subject_id"] in revision_subjects(snapshot)}
        )
    for stage, movable in enumerate(stages):
        if stage:
            log(
                "Créneaux figés incompatibles : ouverture des déplacements autorisés, "
                "dans la même semaine."
            )
            expanded, total = [], 0
            for i, task in enumerate(tasks):
                if stop.is_set():
                    raise GenerationError("Calcul annulé.", "cancelled")
                allowed = revision_options(snapshot, task, rules) if i in movable else choices[i]
                total += len(allowed)
                if total > 250000:
                    raise GenerationError("Limite technique de combinaisons atteinte.", "failed")
                expanded.append(allowed)
            choices = expanded
        try:
            sessions = solve_choices(
                snapshot, tasks, choices, rules, log, stop, deadline, template=False
            )
            break
        except GenerationError as error:
            if error.status != "infeasible" or stage == len(stages) - 1:
                raise
    annual = validate_revision(snapshot, sessions, rules)
    changes = revision_changes(snapshot, annual)
    quotas = []
    acquired = entitlement(
        [s for s in snapshot["live_sessions"] if s["day"] < snapshot["effective_on"]]
    )
    for (calendar, group, subject), total in sorted(entitlement(annual).items()):
        quotas.append(
            {
                "calendar_id": calendar,
                "group": group,
                "subject_id": subject,
                "acquired": acquired[calendar, group, subject],
                "total": total,
                "remaining": total - acquired[calendar, group, subject],
            }
        )
    log(
        f"Révision complète : {len(changes)} séances modifiées ou ajoutées ; "
        "volumes annuels vérifiés."
    )
    return {"sessions": sessions, "changes": changes, "quotas": quotas, "merged": False}
