"""Resolve explicit group rotations and remove kholles without touching course occurrences."""

import threading
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from uuid import uuid4

from ortools.sat.python import cp_model

from app.schemas.kholloscope_generation import GenerationRules
from app.schemas.timetable import SeriesData, YearDocument
from app.services.kholloscope_solver import GenerationError, overlaps
from app.services.timetable_engine import series_dates, teaching_weeks


def solve_assignment(
    solver: cp_model.CpSolver, model: cp_model.CpModel, stop: threading.Event | None
) -> cp_model.CpSolverStatus:
    """Run a bounded assignment search and observe optional generation cancellation.

    Parameters
    ----------
    solver, model, stop
        Configured native search, assignment constraints and optional cancellation event.

    Returns
    -------
    cp_model.CpSolverStatus
        Native status, unless generation cancellation was requested.
    """
    if stop is None:
        return solver.solve(model)
    finished = threading.Event()

    def watch() -> None:
        """Interrupt even a native search that has no feasible solution yet."""
        while not finished.wait(0.2):
            if stop.is_set():
                solver.stop_search()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        status = solver.solve(model)
    finally:
        finished.set()
        watcher.join()
    if stop.is_set():
        raise GenerationError("Calcul annulé.", "cancelled")
    return status


def rotation_plan(
    snapshot: dict, result: dict, mappings: list[dict], mode: str
) -> tuple[list[dict], list[list[int]]]:
    """Advance groups down each subject's ordered slots, retaining original logical weeks.

    Parameters
    ----------
    snapshot, result, mappings, mode
        Trusted source calendar, annual sessions, base group bijections and rotation mode.

    Returns
    -------
    tuple[list[dict], list[list[int]]]
        Ideal assignments and cadence-compatible real group numbers for each session.
    """
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    bindings = {(m["calendar_id"], m["track"]): m["group"] for m in mappings}
    numbers = {c: sorted(m["group"] for m in mappings if m["calendar_id"] == c) for c in calendars}
    per_track = defaultdict(list)
    for s in result["sessions"]:
        per_track[s["calendar_id"], s["subject_id"], s["track"]].append(s)
    signatures, orders = {}, {}
    for key, sessions in per_track.items():
        origins = [date.fromisoformat(s.get("original_day", s["day"])) for s in sessions]
        signatures[key] = tuple(
            sorted((d - timedelta(days=d.weekday())).isoformat() for d in origins)
        )
        first = min(
            sessions,
            key=lambda s: (
                s.get("original_day", s["day"]),
                s.get("original_start", s.get("start", 0)),
            ),
        )
        orders[key] = (
            date.fromisoformat(first.get("original_day", first["day"])).weekday(),
            first.get("original_start", first.get("start", 0)),
            first.get("teacher_id", 0),
            first.get("room_id", 0),
            key[2],
        )
    pools = {
        key: sorted(
            (
                other
                for other in per_track
                if other[:2] == key[:2] and signatures[other] == signature
            ),
            key=lambda item: orders[item],
        )
        for key, signature in signatures.items()
    }
    # Interleave distinct teacher/room pairs so adjacent visits do not simply move
    # between two hours of the same examiner. Keep chronological order within a pair.
    for key, pool in pools.items():
        buckets = defaultdict(list)
        for item in pool:
            buckets[orders[item][2:4]].append(item)
        pools[key] = [
            bucket[index]
            for index in range(max(map(len, buckets.values())))
            for bucket in buckets.values()
            if index < len(bucket)
        ]
    resolved, options = [], []
    for s in result["sessions"]:
        key = (s["calendar_id"], s["subject_id"], s["track"])
        original = date.fromisoformat(s.get("original_day", s["day"]))
        monday = (original - timedelta(days=original.weekday())).isoformat()
        weeks = [w["start"] for w in calendars[s["calendar_id"]]["weeks"]]
        week = weeks.index(monday)
        shift = (
            week
            if mode == "weekly"
            else week // result.get("cycle_length", 2)
            if mode == "cycle"
            else 0
        )
        pool = pools[key]
        # A group descends the slot list, so each slot receives its predecessor's group.
        source = pool[(pool.index(key) - shift) % len(pool)]
        group = bindings[source[0], source[2]]
        resolved.append({**s, "group": group, "track": numbers[s["calendar_id"]].index(group) + 1})
        options.append([bindings[k[0], k[2]] for k in pool] if mode != "fixed" else [group])
    return resolved, options


def rotated_sessions(snapshot: dict, result: dict, mappings: list[dict], mode: str) -> list[dict]:
    """Return the ideal per-subject rotation before independent resource validation."""
    return rotation_plan(snapshot, result, mappings, mode)[0]


def add_assignment_meal(
    model: cp_model.CpModel, intervals: list, presences: list, cfg: dict, fixed: list[dict]
) -> None:
    """Require a continuous meal only when the assignment uses this resource/day.

    Parameters
    ----------
    model, intervals, presences, cfg, fixed
        Assignment model, optional sessions, day activators, settings and course bookings.

    Returns
    -------
    None
        Adds an optional meal excluding both sessions and fixed courses.
    """
    active = model.new_bool_var("meal_active")
    model.add_max_equality(active, presences)
    duration = cfg["session_minutes"] * 60
    start = model.new_int_var(
        cfg.get("lunch_start", 43200), cfg.get("lunch_end", 50400) - duration, "meal_start"
    )
    meal = model.new_optional_fixed_size_interval_var(start, duration, active, "meal")
    model.add_no_overlap([meal, *intervals])
    for event in fixed:
        course = model.new_fixed_size_interval_var(
            event["start"], event["end"] - event["start"], "course"
        )
        model.add_no_overlap([meal, course])


def repair_rotation(
    snapshot: dict,
    result: dict,
    mappings: list[dict],
    mode: str,
    rules: GenerationRules,
    context: dict,
    *,
    deadline: float | None = None,
    stop: threading.Event | None = None,
) -> list[dict]:
    """Favor fair annual teacher/room diversity, then a balanced safe rotation.

    Parameters
    ----------
    snapshot, result, mappings, mode, rules
        Trusted placement, base group numbers, selected rotation and generation rules.
    context
        Assignment-only pupil IDs by calendar/group and their occupied calendar IDs.
    deadline, stop
        Optional global generation deadline and cancellation signal for anonymous verification.

    Returns
    -------
    list[dict]
        Complete safe assignments, or an explicit infeasibility/timeout diagnostic.
    """
    desired, allowed = rotation_plan(snapshot, result, mappings, mode)
    if sum(map(len, allowed)) > 150000:
        raise GenerationError("Limite technique de recherche des affectations atteinte.", "failed")
    calendars = {c["id"]: c for c in snapshot["calendars"]}
    bindings = {(m["calendar_id"], m["track"]): m["group"] for m in mappings}
    numbers = {c: sorted(m["group"] for m in mappings if m["calendar_id"] == c) for c in calendars}
    model = cp_model.CpModel()
    expected, coverage = Counter(), defaultdict(list)
    group_busy, group_days = defaultdict(list), defaultdict(list)
    pupil_busy, pupil_calendar_vars = defaultdict(list), defaultdict(list)
    pupils = context.get("pupils", {})
    pupil_calendars = context.get("pupil_calendars", {})
    decisions, costs = [], []
    pair_choices = defaultdict(list)
    for i, (source, target, choices) in enumerate(
        zip(result["sessions"], desired, allowed, strict=True)
    ):
        if stop is not None and stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        origin = date.fromisoformat(source.get("original_day", source["day"]))
        week = (origin - timedelta(days=origin.weekday())).isoformat()
        c, subject, day = source["calendar_id"], source["subject_id"], source["day"]
        expected[c, subject, week, bindings[c, source["track"]]] += 1
        variables = {}
        for group in choices:
            x = model.new_bool_var(f"assign_{i}_{group}")
            variables[group] = x
            interval = model.new_optional_fixed_size_interval_var(
                source["start"], source["end"] - source["start"], x, "session"
            )
            coverage[c, subject, week, group].append(x)
            pair_choices[
                c, subject, group, source.get("teacher_id", 0), source.get("room_id", 0)
            ].append(x)
            group_busy[c, group, day].append(interval)
            group_days[c, group, day].append(x)
            for pupil in pupils.get((c, group), set()):
                pupil_busy[pupil, day].append(interval)
                pupil_calendar_vars[pupil, day, c].append(x)
                if any(
                    e["calendar_id"] in pupil_calendars.get(pupil, set())
                    and overlaps(source["start"], source["end"], e["start"], e["end"])
                    for e in snapshot["bookings"].get(day, [])
                ):
                    model.add(x == 0)
            position, preferred = choices.index(group), choices.index(target["group"])
            distance = min(
                (position - preferred) % len(choices), (preferred - position) % len(choices)
            )
            costs.append(x * ((10 if group != target["group"] else 0) + distance))
            model.add_hint(x, int(group == target["group"]))
        model.add_exactly_one(list(variables.values()))
        decisions.append(variables)
    for key, values in coverage.items():
        model.add(sum(values) == expected[key])
    for (c, group, day), intervals in group_busy.items():
        variables = group_days[c, group, day]
        model.add_no_overlap(intervals)
        model.add(sum(variables) <= rules.max_per_day)
        add_assignment_meal(
            model,
            intervals,
            variables,
            calendars[c]["settings"],
            [e for e in snapshot["bookings"].get(day, []) if e["calendar_id"] == c],
        )
    for intervals in pupil_busy.values():
        model.add_no_overlap(intervals)
    for (pupil, day, c), variables in pupil_calendar_vars.items():
        add_assignment_meal(
            model,
            pupil_busy[pupil, day],
            variables,
            calendars[c]["settings"],
            [
                e
                for e in snapshot["bookings"].get(day, [])
                if e["calendar_id"] in pupil_calendars.get(pupil, set())
            ],
        )
    pair_uses, exposures = defaultdict(list), []
    for (c, subject, group, _teacher, _room), variables in pair_choices.items():
        used = model.new_bool_var("pair_used")
        model.add_max_equality(used, variables)
        pair_uses[c, subject, group].append(used)
        count = model.new_int_var(0, len(variables), "pair_count")
        model.add(count == sum(variables))
        square = model.new_int_var(0, len(variables) ** 2, "pair_exposure")
        model.add_multiplication_equality(square, [count, count])
        exposures.append(square)
    totals = Counter()
    for (c, subject, _week, group), count in expected.items():
        totals[c, subject, group] += count
    fairness = model.new_int_var(0, 1000, "minimum_diversity")
    diversity_rewards = []
    for key, uses in pair_uses.items():
        target = min(len(uses), totals[key])
        model.add(sum(uses) * 1000 >= fairness * target)
        # Diminishing rewards protect remaining groups even if one unavoidable
        # bottleneck fixes the global minimum at a low diversity score.
        for level in range(1, target + 1):
            reached = model.new_bool_var("diversity_level")
            model.add(sum(uses) >= level).only_enforce_if(reached)
            model.add(sum(uses) < level).only_enforce_if(reached.Not())
            diversity_rewards.append(reached * max(1, 10000 // level))
    # A global diagonal can be infeasible: do not sacrifice one group's diversity
    # merely to retain the maximum number of ideal assignments elsewhere.
    objectives = [
        (-fairness, fairness),
        (-sum(diversity_rewards), sum(diversity_rewards)),
        (sum(costs) * (len(desired) ** 2 + 1) + sum(exposures), None),
    ]
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 2
    solver.parameters.random_seed = 2026
    budget = min(10, rules.time_limit)
    deadline = min(deadline, time.monotonic() + budget) if deadline else time.monotonic() + budget
    selected = None
    status = cp_model.UNKNOWN
    for stage, (objective, retain) in enumerate(objectives):
        if stop is not None and stop.is_set():
            raise GenerationError("Calcul annulé.", "cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        model.minimize(objective)
        solver.parameters.max_time_in_seconds = (
            min(remaining, budget * (0.4 if stage == 0 else 0.25)) if stage < 2 else remaining
        )
        status = solve_assignment(solver, model, stop)
        if status == cp_model.UNKNOWN and selected is None and deadline > time.monotonic():
            solver.parameters.max_time_in_seconds = deadline - time.monotonic()
            status = solve_assignment(solver, model, stop)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break
        selected = [
            next(g for g, x in variables.items() if solver.boolean_value(x))
            for variables in decisions
        ]
        if retain is not None:
            model.add(retain >= solver.value(retain))
            model.clear_hints()
            for variables, group in zip(decisions, selected, strict=True):
                for number, variable in variables.items():
                    model.add_hint(variable, int(number == group))
    if selected is None:
        if status == cp_model.MODEL_INVALID:
            raise GenerationError("Modèle d’affectation invalide.", "failed")
        if status == cp_model.INFEASIBLE:
            raise GenerationError(
                "Aucune affectation ne respecte les cadences, les repas "
                "et les disponibilités des groupes."
            )
        raise GenerationError(
            "Aucune affectation complète trouvée dans le délai. "
            "Cela ne prouve pas l’impossibilité.",
            "timeout",
        )
    assigned = []
    for source, group in zip(result["sessions"], selected, strict=True):
        assigned.append(
            {**source, "group": group, "track": numbers[source["calendar_id"]].index(group) + 1}
        )
    return assigned


def remove_kholles(document: YearDocument, today: date, scope: str) -> tuple[YearDocument, int]:
    """Remove all or strictly future kholles, including moved or recurring occurrences.

    Parameters
    ----------
    document, today, scope
        Current live document, school-local date and confirmed future/all selection.

    Returns
    -------
    tuple[YearDocument, int]
        Updated document and removed occurrence count, preserving non-kholle blocks and
        historical UIDs. Only affected recurring kholles are materialized as dated records.
    """
    result = document.model_copy(deep=True)
    result.series = []
    removed = 0
    weeks = teaching_weeks(document.settings)
    for series in document.series:
        dates = sorted(
            set(series_dates(series, document.settings, weeks=weeks)) | set(series.exceptions)
        )
        removed_dates = set()
        for source in dates:
            block = series.exceptions.get(source, series)
            if block is None:
                continue
            actual = block.starts_on if source in series.exceptions else source
            if block.kind == "kholle" and (scope == "all" or actual > today):
                removed_dates.add(source)
        if not removed_dates:
            result.series.append(series)
            continue
        removed += len(removed_dates)
        if series.kind != "kholle":
            updated = series.model_copy(deep=True)
            updated.exceptions.update(dict.fromkeys(removed_dates))
            result.series.append(updated)
            continue
        for source in dates:
            block = series.exceptions.get(source, series)
            if source in removed_dates or block is None:
                continue
            actual = block.starts_on if source in series.exceptions else source
            fields = block.model_dump(
                exclude={"id", "lineage", "exceptions", "uid_lineage", "uid_date"}
            )
            fields.update(starts_on=actual, interval=0, until=None)
            identifier = uuid4().hex
            result.series.append(
                SeriesData(
                    **fields,
                    id=identifier,
                    lineage=identifier,
                    uid_lineage=series.uid_lineage or series.lineage,
                    uid_date=(series.uid_date or source) if source == series.starts_on else source,
                )
            )
    return result, removed
