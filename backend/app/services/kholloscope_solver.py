"""Pure CP-SAT placement on anonymous tracks, followed by bounded annual recovery.

No real group or pupil membership is accepted by this module. A track is only a witness that
each promotion can cover its volumes and alternate subjects before later group assignment.
"""

import math
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta

from ortools.sat.python import cp_model

from app.schemas.kholloscope_generation import GenerationRules
from app.schemas.timetable import YearSettings
from app.services.kholloscope_service import balanced_service, occurrence_phases, service_cycles
from app.services.timetable_engine import daily_slots, teaching_day

DAY = 86400


class GenerationError(Exception):
    """Carry a safe, actionable generation diagnostic and a solver outcome."""

    def __init__(self, message: str, status: str = "infeasible") -> None:
        """Keep the public message separate from unexpected server failures."""
        super().__init__(message)
        self.status = status


def overlaps(a: int, b: int, c: int, d: int) -> bool:
    """Treat touching endpoints as nonoverlapping, using exact integer seconds."""
    return a < d and c < b


def annual_quota(minutes: int, rounding: str) -> int | float:
    """Return the nominal session target; an unrounded target follows the reference cycle.

    Parameters
    ----------
    minutes, rounding
        Configured pedagogical minutes and the explicit annual rounding policy.

    Returns
    -------
    int | float
        Whole rounded sessions, or the exact nominal mean before dated cycle expansion.
    """
    if minutes % 60 == 0:
        return minutes // 60
    if rounding == "floor":
        return minutes // 60
    if rounding == "ceil":
        return math.ceil(minutes / 60)
    return minutes / 60


def ranges_for(snapshot: dict, teacher: int) -> list[dict]:
    """Use explicit yearly availability, including an explicitly unavailable empty pattern."""
    return snapshot["availability"].get(str(teacher), [])


def candidates(snapshot: dict, calendar: dict, teacher: int, day: date) -> list[dict]:
    """Filter availability AND all staff bookings, promotion courses and room occupancy.

    Promotion course audiences are conservatively treated as full-promotion occupancy; no
    real memberships are inspected. This can reject a shared subgroup slot, never invent one.
    """
    settings = YearSettings.model_validate(calendar["settings"])
    if not teaching_day(day, settings):
        return []
    events = snapshot["bookings"].get(day.isoformat(), [])
    duration = settings.session_minutes * 60
    rooms = snapshot["selected_rooms"].get(str(calendar["subject_id"]), [])
    result = []
    for start, _ in daily_slots(settings):
        end = start + duration
        if end > settings.day_end or any(
            overlaps(start, end, pause.start, pause.end) for pause in settings.breaks
        ):
            continue
        if not any(
            r["weekday"] == day.weekday() and r["start"] <= start and end <= r["end"]
            for r in ranges_for(snapshot, teacher)
        ):
            continue
        if any(
            overlaps(start, end, e["start"], e["end"])
            and (teacher in e["teachers"] or calendar["id"] == e["calendar_id"])
            for e in events
        ):
            continue
        for room in rooms:
            capacity = snapshot["capacities"].get(str(room), 0)
            occupied = [
                e
                for e in events
                if e["room_id"] == room and overlaps(start, end, e["start"], e["end"])
            ]
            if capacity <= 0 or any(e["kind"] != "kholle" for e in occupied):
                continue
            if len(occupied) >= capacity:
                continue
            result.append(
                {
                    "day": day.isoformat(),
                    "start": start,
                    "end": end,
                    "teacher_id": teacher,
                    "room_id": room,
                }
            )
    return result


def validate_cycle_service(snapshot: dict, tasks: list[dict]) -> None:
    """Reject contradictory fixed A/B commitments before building the placement model.

    Parameters
    ----------
    snapshot, tasks
        Exact staff commitments and required sessions for each anonymous group/subject.

    Returns
    -------
    None
        Raises an actionable generation diagnostic when service arithmetic is impossible.
    """
    tracks, required = defaultdict(int), defaultdict(int)
    for task in tasks:
        tracks[task["calendar_id"], task["track"]] += 1
        required[task["subject_id"]] += 1
    phase_a, phase_b = 0, 0
    horizon = snapshot.get("cycle_length", 2)
    for subject in balanced_service(snapshot["subjects"]):
        counts = [person["sessions"] for person in subject["staff"]]
        multiplier = horizon // subject.get("cycle_weeks", 2)
        if sum(counts) * multiplier != required[subject["id"]]:
            label = subject.get("name", f"Matière {subject['id']}")
            raise GenerationError(
                f"{label} : le Service prévoit {sum(counts)} séances sur le cycle A/B, "
                f"mais les groupes en demandent {required[subject['id']]}. "
                "Corrigez les souhaits de service avant de relancer."
            )
        phase_a += sum(person["sessions_a"] for person in subject["staff"])
        phase_b += sum(person["sessions_b"] for person in subject["staff"])
    if horizon != 2:
        return
    lower = sum(count // 2 for count in tracks.values())
    upper = sum((count + 1) // 2 for count in tracks.values())
    if not (lower <= phase_a <= upper and lower <= phase_b <= upper):
        needed = (
            f"exactement {lower} séances par semaine"
            if lower == upper
            else f"entre {lower} et {upper} séances par semaine"
        )
        raise GenerationError(
            f"Répartition A/B incompatible : le tableau Service impose {phase_a} séances "
            f"en semaine A et {phase_b} en semaine B, alors que les groupes demandent {needed}. "
            "Corrigez la répartition du Service ou les souhaits avant de relancer. "
            "Ajouter des salles ou des disponibilités ne résout pas ce déséquilibre."
        )


def template_preferences(
    model: cp_model.CpModel,
    tasks: list[dict],
    choices: list[list[dict]],
    decisions: list[list],
    stop: threading.Event | None = None,
) -> list:
    """Build successive stability, weekday balance and early/rotatable slot objectives.

    Parameters
    ----------
    model, tasks, choices, decisions
        Anonymous reference tasks, allowed placements and exact-one decision variables.
    stop
        Optional cancellation signal while constructing optimization constraints.

    Returns
    -------
    list
        Three objectives to minimize in order, retaining earlier achieved quality.
    """
    days, slots, times, subject_slots = (defaultdict(list) for _ in range(4))
    sizes = Counter(task["calendar_id"] for task in tasks)
    early = []
    for task, options, variables in zip(tasks, choices, decisions, strict=True):
        if stop is not None and stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        earliest = min(o["start"] for o in options)
        latest = max(o["start"] for o in options)
        for option, variable in zip(options, variables, strict=True):
            weekday = date.fromisoformat(option["day"]).weekday()
            phase = option["phase"]
            day = (task["calendar_id"], phase, weekday)
            days[day].append(variable)
            # Match neighbouring A/B phases even for a longer common reference cycle.
            base = (phase // 2, option["teacher_id"], weekday, option["start"], option["end"])
            slots[(*base, option["room_id"], phase % 2)].append(variable)
            times[(*base, phase % 2)].append(variable)
            subject_slots[
                task["calendar_id"],
                task["subject_id"],
                phase,
                weekday,
                option["start"],
                option["end"],
            ].append(variable)
            early.append(
                variable * ((option["start"] - earliest) * 1000 // max(1, latest - earliest))
            )
    stability = []
    for resources, weight in ((slots, 2 * len(tasks) + 1), (times, 1)):
        keys = sorted({key[:-1] for key in resources})
        for key in keys:
            delta = model.new_int_var(0, 1, "ab_slot_difference")
            model.add_abs_equality(delta, sum(resources[*key, 0]) - sum(resources[*key, 1]))
            stability.append(delta * weight)
    spread = []
    for (calendar, _phase, _weekday), variables in days.items():
        count = model.new_int_var(0, sizes[calendar], "weekday_load")
        model.add(count == sum(variables))
        square = model.new_int_var(0, sizes[calendar] ** 2, "weekday_load_square")
        model.add_multiplication_equality(square, [count, count])
        spread.append(square)
    footprints = []
    for variables in subject_slots.values():
        used = model.new_bool_var("subject_slot_used")
        model.add_max_equality(used, variables)
        footprints.append(used)
    # Both terms range from zero to approximately 1000 per session. Fewer subject
    # time footprints allow groups to exchange teacher/room pairs without moving time.
    return [sum(stability), sum(spread), sum(early) + 1000 * sum(footprints)]


def solve_choices(
    snapshot: dict,
    tasks: list[dict],
    choices: list[list[dict]],
    rules: GenerationRules,
    log: Callable[[str], None],
    stop: threading.Event,
    deadline: float,
    *,
    template: bool,
) -> list[dict]:
    """Solve exact task coverage, resource capacity, lunch and anonymous alternation.

    Parameters
    ----------
    snapshot, tasks, choices
        Authorized immutable inputs and allowed placements for each abstract session.
    rules, log, stop, deadline
        Bounded rules, safe progress sink, cancellation event and global monotonic deadline.
    template
        Enforce exact A/B staff commitments and balanced abstract weekly subject loads.

    Returns
    -------
    list[dict]
        A complete feasible placement, or an explicit diagnostic (never a partial success).
    """
    if stop.is_set():
        raise GenerationError("Calcul annulé.", "cancelled")
    if template:
        validate_cycle_service(snapshot, tasks)
    if sum(map(len, choices)) > 250000:
        raise GenerationError(
            "Limite technique de recherche atteinte : trop de combinaisons. "
            "Cela ne prouve pas que le calendrier est impossible.",
            "failed",
        )
    model = cp_model.CpModel()
    teacher_intervals, track_intervals, room_intervals = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    staff_counts, phase_counts, day_counts = defaultdict(list), defaultdict(list), defaultdict(list)
    track_day_intervals = defaultdict(list)
    room_demands = defaultdict(list)
    lunch_resources = {}
    decisions, costs = [], []
    offsets: dict[tuple, dict[int, object]] = defaultdict(dict)
    base = date.fromisoformat(snapshot["base_date"])
    for i, (task, options) in enumerate(zip(tasks, choices, strict=True)):
        if stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        if not options:
            raise GenerationError(
                f"Aucun créneau pour {task['id']} : "
                "vérifiez cours, disponibilités, salles et jours ouverts."
            )
        variables = []
        for j, option in enumerate(options):
            x = model.new_bool_var(f"x{i}_{j}")
            variables.append(x)
            if template and "offset" in option:
                key = (task["calendar_id"], task["subject_id"], task["track"])
                offset = option["offset"]
                if offset not in offsets[key]:
                    offsets[key][offset] = model.new_bool_var(f"offset_{key}_{offset}")
                model.add(x <= offsets[key][offset])
            day = date.fromisoformat(option["day"])
            begin = (day - base).days * DAY + option["start"]
            interval = model.new_optional_fixed_size_interval_var(
                begin, option["end"] - option["start"], x, f"i{i}_{j}"
            )
            teacher = option["teacher_id"]
            track = (task["calendar_id"], task["track"])
            teacher_intervals[teacher].append(interval)
            track_intervals[track].append(interval)
            if snapshot.get("revision_branch"):
                track_day_intervals[track, option["day"]].append(interval)
            room_intervals[option["room_id"]].append(interval)
            room_demands[option["room_id"]].append(1)
            if not (
                snapshot.get("revision_branch")
                and snapshot.get("return_on")
                and option["day"] >= snapshot["return_on"]
            ):
                staff_counts[teacher, task["subject_id"], option.get("phase", 0)].append(x)
            phase_counts[track, option.get("phase", 0)].append(x)
            day_counts[track, option["day"]].append(x)
            lunch_resources["teacher", teacher, option["day"]] = (teacher_intervals[teacher], None)
            lunch_resources["track", track, option["day"]] = (
                track_intervals[track],
                task["calendar_id"],
            )
            preference = snapshot["preferences"].get(str(teacher), {})
            cost = option.get("cost", 0)
            if preference.get("prefer_own_promotion", True) and preference.get("calendar_ids"):
                cost += 2 * (task["calendar_id"] not in preference["calendar_ids"])
            costs.append(cost * x)
            if not template and (option.get("cost") == 0 or len(options) == 1):
                model.add_hint(x, 1)
        model.add_exactly_one(variables)
        decisions.append(variables)
    for values in offsets.values():
        model.add_exactly_one(list(values.values()))
    for intervals in teacher_intervals.values():
        model.add_no_overlap(intervals)
    for intervals in track_intervals.values():
        model.add_no_overlap(intervals)
    if snapshot.get("revision_branch"):
        # Revision tasks already carry real group positions, including all frozen kholles.
        for subject, people in snapshot["future_service"].items():
            for teacher, total in people.items():
                model.add(sum(staff_counts[int(teacher), int(subject), 0]) == total)
        pupil_intervals = defaultdict(list)
        for ((calendar, group), day), intervals in track_day_intervals.items():
            pupils = snapshot["group_pupils"].get(f"{calendar}:{group}", [])
            for pupil in pupils:
                pupil_intervals[pupil, day].extend(intervals)
        for intervals in pupil_intervals.values():
            model.add_no_overlap(intervals)
        # Shared pupils must retain a meal across every promotion they attend.
        pupil_calendars = defaultdict(set)
        for key, pupils in snapshot["group_pupils"].items():
            calendar, _ = map(int, key.split(":"))
            for pupil in pupils:
                pupil_calendars[pupil].add(calendar)
        calendar_settings = {c["id"]: c["settings"] for c in snapshot["calendars"]}
        for (pupil, day_string), intervals in pupil_intervals.items():
            for calendar in pupil_calendars[pupil]:
                cfg = calendar_settings[calendar]
                duration = cfg["session_minutes"] * 60
                left, right = cfg.get("lunch_start", 43200), cfg.get("lunch_end", 50400)
                if right - left < duration:
                    raise GenerationError("La fenêtre de repas est trop courte.")
                offset = (date.fromisoformat(day_string) - base).days * DAY
                start = model.new_int_var(offset + left, offset + right - duration, "meal")
                meal = model.new_fixed_size_interval_var(start, duration, "pupil_meal")
                model.add_no_overlap([meal, *intervals])
                for event in snapshot["bookings"].get(day_string, []):
                    if pupil in event.get("pupils", []):
                        fixed = model.new_fixed_size_interval_var(
                            offset + event["start"], event["end"] - event["start"], "course"
                        )
                        model.add_no_overlap([meal, fixed])
    if snapshot.get("revision_branch"):
        for day, events in snapshot["bookings"].items():
            offset = (date.fromisoformat(day) - base).days * DAY
            for event in events:
                room = event["room_id"]
                if room not in room_intervals:
                    continue
                fixed = model.new_fixed_size_interval_var(
                    offset + event["start"], event["end"] - event["start"], "room_booking"
                )
                room_intervals[room].append(fixed)
                room_demands[room].append(
                    1 if event["kind"] == "kholle" else snapshot["capacities"][str(room)]
                )
    for room, intervals in room_intervals.items():
        model.add_cumulative(intervals, room_demands[room], snapshot["capacities"][str(room)])
    for values in day_counts.values():
        model.add(sum(values) <= rules.max_per_day)
    if template:
        horizon = snapshot.get("cycle_length", 2)
        for subject in balanced_service(snapshot["subjects"]):
            for staff in subject["staff"]:
                count = staff["sessions"] * (horizon // subject.get("cycle_weeks", 2))
                model.add(
                    sum(
                        sum(staff_counts[staff["id"], subject["id"], phase])
                        for phase in range(horizon)
                    )
                    == count
                )
                for phase in range(horizon if subject.get("cycle_weeks", 2) == 2 else 0):
                    total = sum(staff_counts[staff["id"], subject["id"], phase])
                    model.add(total == staff["sessions_a" if phase % 2 == 0 else "sessions_b"])
        totals = defaultdict(int)
        for task in tasks:
            totals[task["calendar_id"], task["track"]] += 1
        for track, count in totals.items():
            for phase in range(2 if horizon == 2 else 0):
                model.add(sum(phase_counts[track, phase]) >= count // 2)
                model.add(sum(phase_counts[track, phase]) <= (count + 1) // 2)
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    for (kind, key, day_string), (intervals, calendar_id) in lunch_resources.items():
        if kind == "teacher" and not rules.teacher_lunch:
            continue
        cfg = (
            calendars[calendar_id]["settings"]
            if calendar_id
            else {"lunch_start": 43200, "lunch_end": 50400}
        )
        duration = (
            rules.teacher_lunch_minutes * 60 if kind == "teacher" else cfg["session_minutes"] * 60
        )
        left, right = cfg.get("lunch_start", 43200), cfg.get("lunch_end", 50400)
        if right - left < duration:
            raise GenerationError("La fenêtre de repas est plus courte que la pause requise.")
        offset = (date.fromisoformat(day_string) - base).days * DAY
        start = model.new_int_var(offset + left, offset + right - duration, "meal")
        meal = model.new_fixed_size_interval_var(start, duration, "meal_interval")
        model.add_no_overlap([meal, *intervals])
        for event in snapshot["bookings"].get(day_string, []):
            if (kind == "teacher" and key in event["teachers"]) or (
                kind == "track" and event["calendar_id"] == calendar_id
            ):
                fixed = model.new_fixed_size_interval_var(
                    offset + event["start"], event["end"] - event["start"], "booking"
                )
                model.add_no_overlap([meal, fixed])
    objectives = [0 if template and not rules.optimize else sum(costs)]
    labels = ["adaptation annuelle" if not template else "faisabilité A/B"]
    if template and rules.optimize:
        objectives = template_preferences(model, tasks, choices, decisions, stop)
        # Promotion preferences are a tie-breaker at the shared early/rotation level.
        objectives[-1] = objectives[-1] * (1 + 2 * len(tasks)) + sum(costs)
        labels = ["stabilité A/B", "répartition hebdomadaire", "horaires précoces et rotation"]
    if rules.optimize or not template:
        model.minimize(objectives[0])
    solver = cp_model.CpSolver()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        phase = "du cycle de référence" if template else "de l’adaptation annuelle"
        raise GenerationError(f"Délai atteint avant la recherche {phase}.", "timeout")
    solver.parameters.max_time_in_seconds = remaining
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 2026
    solver.parameters.log_search_progress = True
    solver.parameters.log_to_stdout = False
    last_log = [0.0]

    def progress(line: str) -> None:
        """Rate-limit native solver progress without logging any personal account data."""
        now = time.monotonic()
        if now - last_log[0] > 1 and line.strip():
            log(line.strip()[:350])
            last_log[0] = now

    solver.log_callback = progress
    finished = threading.Event()

    def watch_cancel() -> None:
        """Stop the native search even when it produces no solution callbacks."""
        while not finished.wait(0.2):
            if stop.is_set():
                solver.stop_search()

    watcher = threading.Thread(target=watch_cancel, daemon=True)
    watcher.start()
    status = cp_model.UNKNOWN
    selected = None
    all_optimal = True
    weights = rules.time_distribution() if template and rules.optimize else (
        (sum(rules.time_distribution()[:3]), rules.time_annual_percent) if template else (100,)
    )
    try:
        for stage, objective in enumerate(objectives):
            if stop.is_set():
                raise GenerationError("Calcul annulé.", "cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                all_optimal = False
                break
            model.minimize(objective)
            # Recompute from actual remaining time, retaining the initial relative weights.
            budget = remaining * weights[stage] / sum(weights[stage:])
            stage_deadline = min(deadline, time.monotonic() + budget)
            solver.parameters.max_time_in_seconds = budget
            log(
                f"Recherche : {labels[stage]} ; "
                f"budget {solver.parameters.max_time_in_seconds:.1f} s."
            )
            status = solver.solve(model)
            if stop.is_set():
                raise GenerationError("Calcul annulé.", "cancelled")
            if (
                status == cp_model.UNKNOWN
                and selected is None
                and time.monotonic() < stage_deadline
            ):
                solver.parameters.max_time_in_seconds = stage_deadline - time.monotonic()
                status = solver.solve(model)
                if stop.is_set():
                    raise GenerationError("Calcul annulé.", "cancelled")
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                all_optimal = False
                break
            selected = [
                {
                    **task,
                    **next(o for o, x in zip(opts, xs, strict=True) if solver.boolean_value(x)),
                }
                for task, opts, xs in zip(tasks, choices, decisions, strict=True)
            ]
            optimum = status == cp_model.OPTIMAL
            all_optimal = all_optimal and optimum
            log(
                f"Critère {labels[stage]} : {solver.objective_value:.0f} ; "
                f"borne {solver.best_objective_bound:.0f} ; "
                f"{solver.wall_time:.2f} s ; "
                + ("optimum prouvé." if optimum else "solution réalisable.")
            )
            if stage + 1 < len(objectives):
                model.add(objective <= round(solver.objective_value))
                model.clear_hints()
                for xs in decisions:
                    for x in xs:
                        model.add_hint(x, int(solver.boolean_value(x)))
    finally:
        finished.set()
        watcher.join()
    if stop.is_set():
        raise GenerationError("Calcul annulé.", "cancelled")
    if selected is None:
        if status == cp_model.INFEASIBLE:
            raise GenerationError(
                "Contraintes incompatibles dans le périmètre de recherche : "
                "service exact, horaires, repas ou ressources. "
                "Élargissez les disponibilités ou les salles."
            )
        if status == cp_model.MODEL_INVALID:
            raise GenerationError("Modèle de contraintes invalide.", "failed")
        raise GenerationError(
            "Aucune solution complète trouvée dans le délai ; cela ne prouve pas l'impossibilité.",
            "timeout",
        )
    quality = "optimale" if rules.optimize and all_optimal else "réalisable"
    log(f"Solution {quality} ; {len(selected)} séances placées.")
    if rules.optimize and all_optimal:
        log("Tous les critères ont un optimum prouvé : arrêt avant le délai maximal autorisé.")
    return selected


def generate(
    snapshot: dict, options: dict, log: Callable[[str], None], stop: threading.Event
) -> dict:
    """Build a complete two-week template, then preserve exact volumes through annual recovery."""
    rules = GenerationRules.from_saved_options(options)
    deadline = time.monotonic() + rules.time_limit
    log("Préparation : groupes abstraits uniquement, aucune affectation réelle.")
    log(
        f"Budget maximal : {rules.time_limit} s. "
        "Un optimum prouvé peut arrêter la recherche plus tôt."
    )
    calendars = snapshot["calendars"]
    periods = service_cycles(
        [{"weeks": c["weeks"], "settings": {"subjects": c["requirements"]}} for c in calendars]
    )
    horizon = math.lcm(*periods.values()) if periods else 2
    if horizon > 60:
        raise GenerationError(
            "Cycle commun supérieur à 60 semaines : limite technique de recherche, "
            "sans conclusion d’impossibilité.",
            "failed",
        )
    snapshot = {
        **snapshot,
        "cycle_length": horizon,
        "subjects": [{**s, "cycle_weeks": periods.get(s["id"], 2)} for s in snapshot["subjects"]],
    }
    common = None
    for calendar in calendars:
        full = {w["start"] for w in calendar["weeks"] if w["days"] == 5}
        common = full if common is None else common & full
    pairs = sorted(
        day
        for day in common or []
        if (date.fromisoformat(day) + timedelta(days=7)).isoformat() in common
    )
    if not pairs:
        raise GenerationError("Aucune paire de semaines complètes communes aux promotions.")
    reference = date.fromisoformat(pairs[0])
    log(
        f"Cycle de référence : {reference.isoformat()} "
        f"et {(reference + timedelta(days=7)).isoformat()}."
    )
    tasks, choices, quotas = [], [], []
    subject_staff = {
        s["id"]: [p["id"] for p in s["staff"] if p["sessions"] > 0] for s in snapshot["subjects"]
    }
    cache = {}
    for calendar in calendars:
        if stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        if calendar["group_count"] <= 0:
            raise GenerationError("Une promotion n'a aucun groupe de khôlle.")
        for subject in calendar["requirements"]:
            minutes = subject["minutes"]
            if minutes == 0:
                continue
            phases = occurrence_phases(minutes, len(calendar["weeks"]), horizon)
            cadence = len(phases)
            interval = horizon / cadence
            possible_offsets = (
                range(2)
                if horizon == 2 or interval == 2
                else range(-min(2, max(0, int(interval) - 1)), 1)
            )
            quota = annual_quota(minutes, rules.rounding)
            quotas.append(
                {
                    "calendar_id": calendar["id"],
                    "subject_id": subject["subject_id"],
                    "sessions": quota,
                    "original_minutes": minutes,
                    "rounded": quota * 60 != minutes,
                    "cycle_based": rules.rounding == "none",
                }
            )
            for track in range(1, calendar["group_count"] + 1):
                for occurrence in range(cadence):
                    task = {
                        "id": f"{calendar['id']}-{subject['subject_id']}-{track}-{occurrence}",
                        "calendar_id": calendar["id"],
                        "subject_id": subject["subject_id"],
                        "track": track,
                    }
                    task_choices = []
                    for teacher in subject_staff.get(subject["subject_id"], []):
                        for offset in possible_offsets:
                            phase = phases[occurrence] + offset
                            if horizon == 2:
                                phase %= horizon
                            if not 0 <= phase < horizon:
                                continue
                            if rules.rounding == "ceil":
                                available = sum(
                                    0
                                    <= ((p + offset) % horizon if horizon == 2 else p + offset)
                                    + cycle
                                    < len(calendar["weeks"])
                                    for cycle in range(0, len(calendar["weeks"]), horizon)
                                    for p in phases
                                )
                                if available < quota:
                                    continue
                            for weekday in range(6 if calendar["settings"]["saturday"] else 5):
                                day = reference + timedelta(days=(phase % 2) * 7 + weekday)
                                key = (calendar["id"], subject["subject_id"], teacher, day)
                                if key not in cache:
                                    cache[key] = candidates(
                                        snapshot, {**calendar, **subject}, teacher, day
                                    )
                                task_choices.extend(
                                    {
                                        **o,
                                        "day": (
                                            reference + timedelta(days=phase * 7 + weekday)
                                        ).isoformat(),
                                        "phase": phase,
                                        "offset": offset,
                                        "cost": 0,
                                    }
                                    for o in cache[key]
                                )
                    tasks.append(task)
                    pins = snapshot.get("pins", {})
                    teachers = {
                        p["teacher_id"]
                        for key, p in pins.items()
                        if key.startswith(f"{calendar['id']}-{subject['subject_id']}-{track}-")
                        and int(key.rsplit("-", 1)[1]) % cadence == occurrence
                    }
                    if teachers:
                        task_choices = [o for o in task_choices if o["teacher_id"] in teachers]
                    choices.append(task_choices)
    if len(tasks) > 2000:
        raise GenerationError("Le cycle dépasse 2 000 séances ; réduisez le périmètre.")
    log(f"Recherche A/B : {len(tasks)} séances, engagements exacts et alternance contrôlés.")
    if horizon != 2:
        log(f"Cycle commun : {horizon} semaines ; cadences régulières et vagues espacées.")
    reference_bookings = dict(snapshot["bookings"])
    for phase in range(horizon):
        for weekday in range(7):
            day = reference + timedelta(days=phase * 7 + weekday)
            source = reference + timedelta(days=(phase % 2) * 7 + weekday)
            reference_bookings[day.isoformat()] = snapshot["bookings"].get(source.isoformat(), [])
    log(
        "Répartition initiale du temps (stabilité A/B, répartition hebdomadaire, "
        "horaires et rotation, adaptation annuelle) : "
        + " / ".join(f"{share} %" for share in rules.time_distribution())
        + ". Le temps gagné est redistribué aux étapes restantes selon leurs poids initiaux."
    )
    template = solve_choices(
        {**snapshot, "bookings": reference_bookings},
        tasks,
        choices,
        rules,
        log,
        stop,
        deadline,
        template=True,
    )
    annual_tasks, annual_choices = [], []
    pins = snapshot.get("pins", {})
    log("Déploiement annuel : conservation des intervenants ; reports à ± une semaine.")
    cache.clear()
    for calendar in calendars:
        cfg = YearSettings.model_validate(calendar["settings"])
        weeks = calendar["weeks"]
        for quota in (q for q in quotas if q["calendar_id"] == calendar["id"]):
            for track in range(1, calendar["group_count"] + 1):
                pattern = sorted(
                    (
                        s
                        for s in template
                        if s["calendar_id"] == calendar["id"]
                        and s["subject_id"] == quota["subject_id"]
                        and s["track"] == track
                    ),
                    key=lambda s: (s["phase"], s["day"], s["start"]),
                )
                if quota["cycle_based"]:
                    occurrences = [
                        (cycle_start + original["phase"], original)
                        for cycle_start in range(0, len(weeks), horizon)
                        for original in pattern
                        if cycle_start + original["phase"] < len(weeks)
                    ]
                    quota.setdefault("track_sessions", {})[str(track)] = len(occurrences)
                else:
                    occurrences = [
                        (
                            min(
                                (number // len(pattern)) * horizon
                                + pattern[number % len(pattern)]["phase"],
                                len(weeks) - 1,
                            ),
                            pattern[number % len(pattern)],
                        )
                        for number in range(quota["sessions"])
                    ]
                for number, (week_index, original) in enumerate(occurrences):
                    if stop.is_set():
                        raise GenerationError("Calcul annulé.", "cancelled")
                    monday = date.fromisoformat(weeks[week_index]["start"])
                    preferred_day = monday + timedelta(
                        days=date.fromisoformat(original["day"]).weekday()
                    )
                    task = {
                        "id": f"{calendar['id']}-{quota['subject_id']}-{track}-{number}",
                        "calendar_id": calendar["id"],
                        "subject_id": quota["subject_id"],
                        "track": track,
                        "original_day": preferred_day.isoformat(),
                        "original_start": original["start"],
                        "teacher_id": original["teacher_id"],
                    }
                    all_options = []
                    for delta in range(
                        -7 * rules.recovery_weeks, 7 * rules.recovery_weeks + 5 + int(cfg.saturday)
                    ):
                        day = monday + timedelta(days=delta)
                        if not (
                            calendar["period_start"] <= day.isoformat() <= calendar["period_end"]
                        ):
                            continue
                        key = (calendar["id"], quota["subject_id"], original["teacher_id"], day)
                        if key not in cache:
                            cache[key] = candidates(
                                snapshot,
                                {**calendar, "subject_id": quota["subject_id"]},
                                original["teacher_id"],
                                day,
                            )
                        for candidate in cache[key]:
                            regular = (
                                candidate["day"] == preferred_day.isoformat()
                                and candidate["start"] == original["start"]
                            )
                            all_options.append(
                                {
                                    **candidate,
                                    "cost": (0 if regular else 100)
                                    + (0 if (day - monday).days in range(7) else 10_000_000)
                                    + abs((day - preferred_day).days) * 2
                                    + int(candidate["room_id"] != original["room_id"]),
                                }
                            )
                    pin = pins.get(task["id"])
                    if pin:
                        all_options = [
                            o
                            for o in all_options
                            if all(
                                o[k] == pin[k] for k in ("day", "start", "room_id", "teacher_id")
                            )
                        ]
                    task["locked"] = bool(pin)
                    annual_tasks.append(task)
                    annual_choices.append(all_options)
    if len(annual_tasks) > 20000:
        raise GenerationError("Le calendrier annuel dépasse 20 000 séances.")
    for quota in quotas:
        counts = list(quota.get("track_sessions", {}).values())
        if counts:
            quota["min_sessions"], quota["max_sessions"] = min(counts), max(counts)
    if any(q["cycle_based"] and q["min_sessions"] != q["max_sessions"] for q in quotas):
        log("Fin de cycle incomplète : volumes issus de l’alternance A/B conservés sans arrondi.")
    if set(pins) - {task["id"] for task in annual_tasks}:
        raise GenerationError(
            "Les nouvelles règles supprimeraient des séances verrouillées. "
            "Revoyez les volumes ou désactivez explicitement la conservation des verrouillages."
        )
    log(
        f"Recherche annuelle : {len(annual_tasks)} séances. "
        "Les quotas annuels ne sont pas réduits par les fermetures."
    )
    if any(not options for options in annual_choices):
        raise GenerationError("Une séance n'a aucun créneau annuel dans sa fenêtre de rattrapage.")
    baseline = [
        {**task, **min(options, key=lambda o: o.get("cost", 0))}
        for task, options in zip(annual_tasks, annual_choices, strict=True)
    ]
    try:
        validate_draft(snapshot, {"sessions": baseline, "quotas": quotas}, rules)
        log(
            "La répétition et les premiers reports passent tous les contrôles : "
            "recherche annuelle évitée."
        )
        annual = baseline
    except GenerationError as error:
        log(f"Adaptation annuelle nécessaire : {error}")
        seeds = {
            i
            for i, options in enumerate(annual_choices)
            if not any(o.get("cost") == 0 for o in options)
        }
        for i, s in enumerate(baseline):
            if stop.is_set():
                raise GenerationError("Calcul annulé.", "cancelled") from None
            simultaneous = []
            for j, other in enumerate(baseline):
                if s["day"] != other["day"] or not overlaps(
                    s["start"], s["end"], other["start"], other["end"]
                ):
                    continue
                if i != j and (
                    s["teacher_id"] == other["teacher_id"]
                    or (s["calendar_id"], s["track"]) == (other["calendar_id"], other["track"])
                ):
                    seeds.update((i, j))
                if s["room_id"] == other["room_id"] and other["start"] <= s["start"] < other["end"]:
                    simultaneous.append(j)
            existing = [
                e
                for e in snapshot["bookings"].get(s["day"], [])
                if e["room_id"] == s["room_id"] and e["start"] <= s["start"] < e["end"]
            ]
            if len(simultaneous) + len(existing) > snapshot["capacities"][str(s["room_id"])]:
                seeds.update(simultaneous)
        seeds.update(lunch_conflicts(snapshot, baseline, rules))
        affected = set()
        for i in seeds:
            for option in annual_choices[i]:
                day = date.fromisoformat(option["day"])
                affected.add(day - timedelta(days=day.weekday()))
        local = []
        for task, options, fixed in zip(annual_tasks, annual_choices, baseline, strict=True):
            day = date.fromisoformat(task["original_day"])
            local.append(
                options
                if not affected or day - timedelta(days=day.weekday()) in affected
                else [fixed]
            )
        log(
            f"Réparation locale : {sum(len(o) > 1 for o in local)} séances mobiles ; "
            "les autres restent fixes."
        )
        try:
            annual = solve_choices(
                snapshot, annual_tasks, local, rules, log, stop, deadline, template=False
            )
        except GenerationError as error:
            if error.status != "infeasible" or local == annual_choices:
                raise
            log("Réparation locale impossible : élargissement aux autres séances non verrouillées.")
            annual = solve_choices(
                snapshot, annual_tasks, annual_choices, rules, log, stop, deadline, template=False
            )
    if stop.is_set():
        raise GenerationError("Calcul annulé.", "cancelled")
    moved = sum(s["day"] != s["original_day"] or s["start"] != s["original_start"] for s in annual)
    result = {
        "template": template,
        "sessions": annual,
        "quotas": quotas,
        "moved": moved,
        "mappings": [],
        "applied": False,
        "reference": reference.isoformat(),
        "cycle_length": horizon,
    }
    validate_draft(snapshot, result, rules)
    if rules.optimize:
        # Import locally: assignment uses the independent resource validator above.
        from app.services.kholloscope_assignment import repair_rotation, rotated_sessions

        mapping = [
            {"calendar_id": c["id"], "track": g, "group": g}
            for c in calendars
            for g in range(1, c["group_count"] + 1)
        ]
        log("Vérification de la rotation par cycle sur des groupes abstraits.")
        desired = rotated_sessions(snapshot, result, mapping, "cycle")
        try:
            validate_draft(
                snapshot,
                {**result, "sessions": desired},
                rules,
                coverage_tracks={s["id"]: s["track"] for s in annual},
            )
            witness = desired
        except GenerationError:
            witness = repair_rotation(
                snapshot, result, mapping, "cycle", rules, {}, deadline=deadline, stop=stop
            )
        validate_draft(
            snapshot,
            {**result, "sessions": witness},
            rules,
            coverage_tracks={s["id"]: s["track"] for s in annual},
        )
        adjustments = sum(a["group"] != b["group"] for a, b in zip(desired, witness, strict=True))
        log(
            f"Rotation abstraite réalisable : {adjustments} écarts à la rotation cible. "
            "L’affectation réelle vérifiera aussi les appartenances des élèves."
        )
    if stop.is_set():
        raise GenerationError("Calcul annulé.", "cancelled")
    log(
        f"Terminé : {len(annual)} séances, {moved} reports. "
        "Affectez les groupes dans l'étape suivante."
    )
    return result


def lunch_conflicts(snapshot: dict, sessions: list[dict], rules: GenerationRules) -> set[int]:
    """Locate actual meal violations without treating every valid noon kholle as a conflict.

    Parameters
    ----------
    snapshot, sessions, rules
        Existing bookings, candidate annual schedule and configured student/staff meals.

    Returns
    -------
    set[int]
        Session indices touching a resource/day with no sufficient continuous meal gap.
    """
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    resources = defaultdict(list)
    for index, session in enumerate(sessions):
        resources["track", session["calendar_id"], session["track"], session["day"]].append(index)
        if rules.teacher_lunch:
            resources["teacher", session["teacher_id"], None, session["day"]].append(index)
    conflicts = set()
    for (kind, identifier, _, day), indices in resources.items():
        cfg = calendars[identifier]["settings"] if kind == "track" else {}
        duration = (cfg["session_minutes"] if kind == "track" else rules.teacher_lunch_minutes) * 60
        busy = [(sessions[i]["start"], sessions[i]["end"]) for i in indices]
        busy.extend(
            (e["start"], e["end"])
            for e in snapshot["bookings"].get(day, [])
            if (kind == "track" and e["calendar_id"] == identifier)
            or (kind == "teacher" and identifier in e["teachers"])
        )
        if not free_lunch(
            busy, cfg.get("lunch_start", 43200), cfg.get("lunch_end", 50400), duration
        ):
            conflicts.update(indices)
    return conflicts


def free_lunch(busy: list[tuple[int, int]], start: int, end: int, duration: int) -> bool:
    """Require one continuous free meal interval rather than summing fragmented gaps."""
    cursor = start
    for left, right in sorted(busy):
        if left - cursor >= duration:
            return True
        if left < end and right > start:
            cursor = max(cursor, right)
    return end - cursor >= duration


def validate_draft(
    snapshot: dict,
    result: dict,
    rules: GenerationRules,
    *,
    coverage_tracks: dict[str, int] | None = None,
) -> None:
    """Verify annual coverage, capacities, anonymous conflicts and meal rules.

    Parameters
    ----------
    snapshot, result, rules
        Trusted source data, draft sessions/quotas and generation rules.
    coverage_tracks
        Original tracks keyed by session ID, supplied only after validated group rotation.
        Cycle-based coverage follows source occurrences; resource checks use actual groups.

    Returns
    -------
    None
        Raises GenerationError when any independent validation fails.
    """
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    counts, by_day = defaultdict(int), defaultdict(list)
    for session in result["sessions"]:
        c = calendars[session["calendar_id"]]
        day = date.fromisoformat(session["day"])
        if not c["period_start"] <= session["day"] <= c["period_end"]:
            raise GenerationError("Une séance sort de sa période de khôlles.")
        origin = date.fromisoformat(session["original_day"])
        origin_monday = origin - timedelta(days=origin.weekday())
        monday = day - timedelta(days=day.weekday())
        if abs((monday - origin_monday).days) > rules.recovery_weeks * 7:
            raise GenerationError("Le déplacement dépasse la fenêtre de rattrapage autorisée.")
        allowed = candidates(
            snapshot, {**c, "subject_id": session["subject_id"]}, session["teacher_id"], day
        )
        if not any(
            all(o[k] == session[k] for k in ("start", "end", "room_id", "teacher_id"))
            for o in allowed
        ):
            raise GenerationError(
                "Créneau indisponible : cours, disponibilité, salle, vacances ou pause."
            )
        if not 1 <= session["track"] <= c["group_count"]:
            raise GenerationError("Position abstraite invalide.")
        source_track = (coverage_tracks or {}).get(session["id"], session["track"])
        counts[c["id"], source_track, session["subject_id"]] += 1
        by_day[session["day"]].append(session)
    for quota in result["quotas"]:
        for track in range(1, calendars[quota["calendar_id"]]["group_count"] + 1):
            expected = quota.get("track_sessions", {}).get(str(track), quota["sessions"])
            if counts[quota["calendar_id"], track, quota["subject_id"]] != expected:
                raise GenerationError("Le volume annuel par groupe n'est pas couvert exactement.")
    for calendar in calendars.values():
        weeks = [w["start"] for w in calendar["weeks"]]
        for subject in calendar.get("requirements", []):
            if not subject["minutes"]:
                continue
            interval = 60 * len(weeks) / subject["minutes"]
            if interval < 1:
                continue
            for track in range(1, calendar["group_count"] + 1):
                origins = sorted(
                    weeks.index(
                        (
                            date.fromisoformat(s["original_day"])
                            - timedelta(days=date.fromisoformat(s["original_day"]).weekday())
                        ).isoformat()
                    )
                    for s in result["sessions"]
                    if s["calendar_id"] == calendar["id"]
                    and s["track"] == track
                    and s["subject_id"] == subject["subject_id"]
                )
                if any(
                    b - a not in {math.floor(interval), math.ceil(interval)}
                    for a, b in zip(origins, origins[1:], strict=False)
                ):
                    raise GenerationError(
                        "La cadence régulière d’un groupe par matière n’est pas respectée. "
                        "Régénérez le calendrier avec les nouvelles règles."
                    )
    for day, sessions in by_day.items():
        tracks, teachers = defaultdict(list), defaultdict(list)
        for i, s in enumerate(sessions):
            tracks[s["calendar_id"], s["track"]].append((s["start"], s["end"]))
            teachers[s["teacher_id"]].append((s["start"], s["end"]))
            simultaneous = [
                o
                for o in sessions
                if o["room_id"] == s["room_id"] and o["start"] <= s["start"] < o["end"]
            ]
            existing = [
                o
                for o in snapshot["bookings"].get(day, [])
                if o["room_id"] == s["room_id"] and o["start"] <= s["start"] < o["end"]
            ]
            if len(simultaneous) + len(existing) > snapshot["capacities"][str(s["room_id"])]:
                raise GenerationError("La capacité simultanée d'une salle est dépassée.")
            for other in sessions[i + 1 :]:
                if overlaps(s["start"], s["end"], other["start"], other["end"]) and (
                    s["teacher_id"] == other["teacher_id"]
                    or (s["calendar_id"], s["track"]) == (other["calendar_id"], other["track"])
                ):
                    raise GenerationError("Chevauchement d'intervenant ou de groupe abstrait.")
        for (calendar, _), busy in tracks.items():
            if len(busy) > rules.max_per_day:
                raise GenerationError("Trop de khôlles pour un groupe le même jour.")
            cfg = calendars[calendar]["settings"]
            busy += [
                (e["start"], e["end"])
                for e in snapshot["bookings"].get(day, [])
                if e["calendar_id"] == calendar
            ]
            if not free_lunch(
                busy,
                cfg.get("lunch_start", 43200),
                cfg.get("lunch_end", 50400),
                cfg["session_minutes"] * 60,
            ):
                raise GenerationError("La pause repas des élèves n'est pas respectée.")
        if rules.teacher_lunch:
            for teacher, busy in teachers.items():
                busy += [
                    (e["start"], e["end"])
                    for e in snapshot["bookings"].get(day, [])
                    if teacher in e["teachers"]
                ]
                if not free_lunch(busy, 43200, 50400, rules.teacher_lunch_minutes * 60):
                    raise GenerationError("La pause repas d'un intervenant n'est pas respectée.")
