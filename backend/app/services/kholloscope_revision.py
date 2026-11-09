"""Private subject branches, durable repair and transactional live-calendar merge."""

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from uuid import uuid4

import anyio
from sqlalchemy import select

from app.models import (
    KholloscopeRun,
    PromotionGroup,
    TeacherAvailability,
    TimetableRoom,
    TimetableSchoolYear,
    TimetableYear,
    User,
)
from app.repositories.groups import active_kholle_group
from app.schemas.kholloscope_generation import DraftVersion, GenerationRules
from app.schemas.kholloscope_revision import (
    RevisionCalculate,
    RevisionCreate,
    RevisionMerge,
    RevisionRollback,
    RevisionRoomChange,
)
from app.schemas.timetable import SeriesFields, YearDocument, YearSettings
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.kholle_wishes import KholleWishesService
from app.services.kholloscope_generation import KholloscopeGenerationService
from app.services.kholloscope_revision_solver import (
    GenerationError,
    entitlement,
    future_service,
    in_revision_period,
    revised_entitlement,
    revision_changes,
    revision_subjects,
    validate_revision,
)
from app.services.kholloscope_versions import effective_metadata, version_metadata
from app.services.kholloscope_worker import run_log_lines
from app.services.kholloscope_workflow import fingerprint
from app.services.teacher_availability import availability_settings, effective_ranges
from app.services.timetable_assignments import assigned_teachers
from app.services.timetable_engine import PARIS, apply_event_change, daily_slots, occurrences
from app.services.timetable_occupancy import replacement_room_problem, room_capacity_conflicts


def revision_group_problems(
    calendars: list[dict], mappings: list[dict], current: dict[int, set[int]]
) -> list[dict]:
    """Compare published group numbers with groups still containing nonarchived pupils.

    Parameters
    ----------
    calendars, mappings, current
        Published calendars and assignment, and current dashboard group numbers by calendar.

    Returns
    -------
    list[dict]
        Public count/number diagnostics without pupil identities or automatic reassignment.
    """
    problems = []
    for calendar in calendars:
        identifier = calendar["id"]
        expected = {m["group"] for m in mappings if m["calendar_id"] == identifier}
        if not expected:
            expected = set(range(1, calendar["group_count"] + 1))
        actual = current.get(identifier, set())
        if expected != actual:
            label = calendar["name"]
            message = (
                f"{label} : kholloscope créé pour {len(expected)} groupes ; "
                f"{len(actual)} groupes détectés actuellement (hors groupes sans élève actif). "
            )
            if len(expected) == len(actual):
                message += "La numérotation des groupes a changé. "
            problems.append(
                {
                    "kind": "groups",
                    "calendar_id": identifier,
                    "expected_count": len(expected),
                    "actual_count": len(actual),
                    "active_groups": sorted(actual),
                    "message": message + "Une révision et un recalcul sont nécessaires.",
                }
            )
    return problems


def check_boundary(effective_on: date, now: datetime) -> None:
    """Reject retroactive or non-Monday publication in the school's local timezone."""
    if effective_on.weekday() != 0 or datetime.combine(effective_on, time(), PARIS) <= now:
        raise AuthError(422, "Choisissez un lundi à minuit à venir (Europe/Paris).")


def membership_conflicts(events: list[dict], pupils: dict[tuple[int, int], set[int]]) -> list[dict]:
    """Report recurring group collisions without exposing pupil identities."""
    active: list[dict] = []
    found = {}
    for event in sorted(events, key=lambda e: e["start"]):
        if event["kind"] != "kholle" or event.get("target_kind") != "kholles":
            continue
        key = (event["calendar_id"], event["target_number"])
        active = [e for e in active if e["end"] > event["start"]]
        for other in active:
            other_key = (other["calendar_id"], other["target_number"])
            pair = tuple(sorted((key, other_key)))
            if pair not in found and pupils.get(key, set()).intersection(
                pupils.get(other_key, set())
            ):
                found[pair] = {
                    "kind": "memberships",
                    "calendar_id": key[0],
                    "message": f"Les groupes {other_key[1]} (agenda {other_key[0]}) et "
                    f"{key[1]} (agenda {key[0]}) ont des élèves communs et des khôlles "
                    f"simultanées le {event['start'][:10]}. Un recalcul est nécessaire.",
                }
        active.append(event)
    return list(found.values())


def room_replacement_changes(
    sessions: list[dict],
    subjects: set[int],
    old_room: int,
    new_room: int,
    starts_on: date,
    now: datetime,
) -> list[dict]:
    """Select only not-yet-started occurrences for a same-time room replacement."""
    return [
        {"before": s, "after": {**s, "room_id": new_room}}
        for s in sessions
        if s["room_id"] == old_room
        and s["subject_id"] in subjects
        and s["day"] >= starts_on.isoformat()
        and datetime.combine(date.fromisoformat(s["day"]), time(), PARIS)
        + timedelta(seconds=s["start"])
        > now
    ]


def merge_document(document: YearDocument, changes: list[dict]) -> YearDocument:
    """Apply only changed occurrences, preserving history and stable subscription identities.

    Parameters
    ----------
    document, changes
        Current annual document and independently validated before/after differences.

    Returns
    -------
    YearDocument
        Updated document; unrelated and unchanged series retain their identifiers and data.
    """
    for change in changes:
        before, after = change["before"], change["after"]
        if after is None:
            document = apply_event_change(
                document,
                before["series_id"],
                date.fromisoformat(before["source_date"]),
                "one",
                None,
            )
            continue
        retained = {}
        if before:
            source = next(s for s in document.series if s.id == before["series_id"])
            original = source.exceptions.get(date.fromisoformat(before["source_date"]), source)
            retained = {"title": original.title}
        block = SeriesFields(
            starts_on=after["day"],
            start_slot=0,
            duration_slots=2,
            start_time=after["start"],
            end_time=after["end"],
            subject_id=after["subject_id"],
            teacher_id=after["teacher_id"],
            teacher_ids=[after["teacher_id"]],
            room_id=after["room_id"],
            kind="kholle",
            title=retained.get("title", ""),
            interval=0,
            until=None,
            target_kind="kholles",
            target_number=after["group"],
            target_user_id=None,
        )
        document = apply_event_change(
            document,
            before["series_id"] if before else None,
            date.fromisoformat(before["source_date"]) if before else None,
            "one",
            block,
        )
    return document


class KholloscopeRevisionService(KholloscopeGenerationService):
    """Keep one editable branch per year, separate from the published generation run."""

    async def branch(self, year: int, *, lock: bool = False) -> KholloscopeRun | None:
        """Return the latest revision without replacing the published generation pointer."""
        query = (
            select(KholloscopeRun)
            .where(
                KholloscopeRun.school_year == year,
                KholloscopeRun.snapshot.has_key("revision_branch"),
            )
            .order_by(KholloscopeRun.created_at.desc())
            .limit(1)
        )
        return await self.db.scalar(query.with_for_update() if lock else query)

    async def revision_problems(self, year: int, published: KholloscopeRun) -> list[dict]:
        """Read dashboard group drift and actual future shared-room overbookings.

        Parameters
        ----------
        year, published
            Authorized academic year and its published annual assignment.

        Returns
        -------
        list[dict]
            Recalculation warnings; this read never changes groups or live sessions.
        """
        calendars = await self.repo.calendars(None, school_year=year)
        promotion_ids = {c.promotion_id for c in calendars if c.promotion_id is not None}
        rows = await self.db.execute(
            select(PromotionGroup.promotion_id, PromotionGroup.number)
            .where(
                PromotionGroup.kind == "kholles",
                PromotionGroup.promotion_id.in_(promotion_ids),
                active_kholle_group(),
            )
            .distinct()
        )
        groups: dict[int, set[int]] = {}
        for promotion, number in rows:
            groups.setdefault(promotion, set()).add(number)
        current = {c.id: groups.get(c.promotion_id, set()) for c in calendars}
        expected = published.snapshot["calendars"]
        # Some legacy jobs retain only mappings, not a complete original calendar snapshot.
        if not expected:
            expected = [
                {"id": c.id, "name": c.name, "group_count": len(current[c.id])} for c in calendars
            ]
        effective_mappings = published.result.get(
            "revision_group_mappings", published.result["mappings"]
        )
        if "revision_group_mappings" in published.result:
            expected = [
                {**c, "group_count": sum(m["calendar_id"] == c["id"] for m in effective_mappings)}
                for c in expected
            ]
        problems = revision_group_problems(expected, effective_mappings, current)
        rooms = list(await self.db.scalars(select(TimetableRoom)))
        names = {r.id: r.name for r in rooms}
        participants = {c["id"] for c in expected}
        events = await self.future_events()
        for conflict in room_capacity_conflicts(
            events, {r.id: r.kholle_capacity for r in rooms}, self.auth.clock()
        ):
            if conflict["calendar_id"] not in participants:
                continue
            problems.append(
                {
                    **conflict,
                    "kind": "room_capacity",
                    "message": f"Salle « {names[conflict['room_id']]} » : "
                    f"{conflict['simultaneous']} khôlles simultanées pour une capacité de "
                    f"{conflict['capacity']}, le {conflict['at'][:10]} à "
                    f"{conflict['at'][11:16]}. Une révision et un recalcul sont nécessaires.",
                }
            )
        teacher_ids = {
            t
            for e in events
            if e["calendar_id"] in participants
            for t in assigned_teachers(e)
            if e["kind"] == "kholle"
        }
        teachers = list(await self.db.scalars(select(User).where(User.id.in_(teacher_ids))))
        teacher_names = {teacher.id: self._identity(teacher)["name"] for teacher in teachers}
        for teacher in teachers:
            if teacher.status != "disabled":
                continue
            problems.append(
                {
                    "kind": "teacher_archived",
                    "calendar_id": 0,
                    "message": f"{self._identity(teacher)['name']} est archivé mais assure encore "
                    "des khôlles à venir. Une révision est nécessaire.",
                }
            )
        context = await self.assignment_context(
            year,
            [
                {"calendar_id": calendar, "group": group, "track": group}
                for calendar, numbers in current.items()
                for group in numbers
            ],
        )
        problems.extend(
            membership_conflicts(
                [e for e in events if e["calendar_id"] in participants], context["pupils"]
            )
        )
        explicit = {
            r.user_id: r.ranges
            for r in await self.db.scalars(
                select(TeacherAvailability).where(
                    TeacherAvailability.school_year == year,
                    TeacherAvailability.user_id.in_(teacher_ids),
                )
            )
        }
        unavailable = set()
        for event in events:
            if event["kind"] != "kholle" or event["calendar_id"] not in participants:
                continue
            first, last = (
                datetime.fromisoformat(event[k]).astimezone(PARIS) for k in ("start", "end")
            )
            for teacher in assigned_teachers(event):
                ranges = effective_ranges(explicit.get(teacher), availability_settings(year))
                if teacher not in unavailable and not any(
                    r["weekday"] == first.weekday()
                    and r["start"] <= first.hour * 3600 + first.minute * 60
                    and last.hour * 3600 + last.minute * 60 <= r["end"]
                    for r in ranges
                ):
                    unavailable.add(teacher)
                    problems.append(
                        {
                            "kind": "availability",
                            "calendar_id": event["calendar_id"],
                            "message": f"{teacher_names.get(teacher, str(teacher))} : "
                            f"une khôlle le {first.date()} "
                            "est hors de ses disponibilités actuelles. "
                            "Une révision est nécessaire.",
                        }
                    )
        return problems

    async def revision_sources(self, actor: UserContext, year: int) -> tuple[dict, str]:
        """Snapshot actual group sessions, private occupancy and membership revisions."""
        snapshot, source = await self.snapshot(actor, year, require_prepared=False)
        published = await self.latest(year)
        if not published or not published.result or not published.result.get("applied"):
            raise AuthError(409, "Publiez un kholloscope avant de créer une révision.")
        # Retired-only subjects still need to be selectable to remove their future sessions.
        roster = await KholleWishesService(self.auth)._state(
            await self.db.get(TimetableSchoolYear, year)
        )
        baseline_subjects = {s["subject_id"] for s in published.result.get("assigned_sessions", [])}
        present = {s["id"] for s in snapshot["subjects"]}
        snapshot["subjects"].extend(
            s for s in roster["subjects"] if s["id"] in baseline_subjects and s["id"] not in present
        )
        mappings = list(published.result["mappings"])
        problems = await self.revision_problems(year, published)
        mapped = {(m["calendar_id"], m["group"]) for m in mappings}
        for session in published.result.get("assigned_sessions", []):
            key = session["calendar_id"], session["group"]
            if key not in mapped:
                mappings.append({"calendar_id": key[0], "group": key[1], "track": key[1]})
                mapped.add(key)
        for problem in problems:
            if problem["kind"] == "groups":
                mappings.extend(
                    {"calendar_id": problem["calendar_id"], "group": group, "track": group}
                    for group in problem["active_groups"]
                    if (problem["calendar_id"], group) not in mapped
                )
        context = await self.assignment_context(year, mappings)
        pupils = {f"{c}:{g}": sorted(p) for (c, g), p in context["pupils"].items()}
        calendars = {c["id"] for c in snapshot["calendars"]}
        books, live = {}, []
        documents = await self.repo.teaching_documents(year, include_private=True)
        for row, document in documents:
            for e in occurrences(document):
                start, end = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
                day = start.date().isoformat()
                entry = {
                    "start": start.hour * 3600 + start.minute * 60 + start.second,
                    "end": end.hour * 3600 + end.minute * 60 + end.second,
                    "calendar_id": row.calendar_id,
                    "room_id": e["room_id"],
                    "teachers": assigned_teachers(e),
                    "kind": e["kind"],
                    "pupils": sorted(
                        {
                            p
                            for key, members in pupils.items()
                            if key.startswith(f"{row.calendar_id}:")
                            for p in members
                        }
                    ),
                }
                if e["kind"] == "kholle" and row.calendar_id in calendars:
                    if (end - start).total_seconds() != document.settings.session_minutes * 60:
                        raise AuthError(
                            422,
                            "Une khôlle a une durée non standard. Vérifiez son volume.",
                        )
                    if e["target_kind"] != "kholles" or len(entry["teachers"]) != 1:
                        raise AuthError(
                            422,
                            "La révision nécessite des khôlles de groupe avec un seul intervenant.",
                        )
                    group = e["target_number"]
                    if f"{row.calendar_id}:{group}" not in pupils:
                        raise AuthError(
                            422,
                            "Un groupe du planning a changé. Vérifiez les groupes.",
                        )
                    live.append(
                        {
                            "id": f"{e['series_id']}:{e['source_date']}",
                            "series_id": e["series_id"],
                            "source_date": e["source_date"],
                            "calendar_id": row.calendar_id,
                            "day": day,
                            "original_day": day,
                            "start": entry["start"],
                            "end": entry["end"],
                            "room_id": e["room_id"],
                            "teacher_id": entry["teachers"][0],
                            "subject_id": e["subject_id"],
                            "group": group,
                            "track": group,
                        }
                    )
                else:
                    books.setdefault(day, []).append(entry)
        baseline = published.result.get(
            "revision_entitlement", published.result.get("assigned_sessions", [])
        )
        if not baseline:
            raise AuthError(
                409, "Le kholloscope publié ne contient pas d'affectation de référence."
            )
        snapshot.update(
            revision_branch=True,
            live_sessions=live,
            entitlement=baseline,
            group_pupils=pupils,
            bookings=books,
            published_run_id=published.id,
            problems=problems,
            effective_rooms=snapshot["selected_rooms"],
            selected_rooms=published.result.get("revision_rooms", snapshot["selected_rooms"]),
        )
        return snapshot, fingerprint(
            [source, pupils, published.id, entitlement_rows(baseline), snapshot["problems"]]
        )

    async def read(self, actor: UserContext, year: int) -> dict:
        """Expose resumable private branch data and fresh wishes without exposing pupil IDs."""
        async with self.db.begin():
            await self.authorize(actor)
            snapshot, source = await self.revision_sources(actor, year)
            row = await self.branch(year)
            published = await self.latest(year)
            latest_wishes = published.result.get("revision_wishes", {})
            subjects = deepcopy(snapshot["subjects"])
            for subject in subjects:
                saved = latest_wishes.get(str(subject["id"]), {})
                original = next(
                    (s for s in published.snapshot["subjects"] if s["id"] == subject["id"]),
                    {"staff": []},
                )
                published_values = {p["id"]: p["sessions"] for p in original["staff"]}
                for person in subject["staff"]:
                    person["sessions"] = saved.get(
                        str(person["id"]), published_values.get(person["id"], 0)
                    )
                subject["required_service"] = required_service(snapshot, subject)
            return {
                "rooms": [
                    {"id": r.id, "name": r.name, "kholle_capacity": r.kholle_capacity}
                    for r in await self.db.scalars(
                        select(TimetableRoom)
                        .where(TimetableRoom.is_active.is_(True))
                        .order_by(TimetableRoom.name)
                    )
                ],
                "pending_publications": await self.pending_publications(year),
                "problems": snapshot["problems"],
                "needs_recalculation": bool(snapshot["problems"]),
                "source_revision": source,
                "subjects": subjects,
                "published_sessions": snapshot["live_sessions"],
                "calendars": [
                    {
                        "id": c["year_id"],
                        "calendar_id": c["id"],
                        "school_year": year,
                        "settings": c["settings"],
                        "revision": None,
                        "slots": daily_slots(YearSettings.model_validate(c["settings"])),
                        "weeks": {w["start"]: w["number"] for w in c["weeks"]},
                        "series": [],
                    }
                    for c in snapshot["calendars"]
                ],
                "next_monday": (
                    self.today() + timedelta(days=7 - self.today().weekday())
                ).isoformat(),
                "branch": None
                if row is None
                else {
                    "id": row.id,
                    "revision": row.revision,
                    "status": row.status,
                    "stale": row.source_revision != source,
                    "effective_on": row.snapshot["effective_on"],
                    "return_on": row.snapshot.get("return_on"),
                    "subject_id": row.snapshot["subject_id"],
                    "subject_ids": revision_subjects(row.snapshot),
                    "wishes": row.snapshot["wishes"],
                    "allow_moves": row.snapshot.get("allow_moves", False),
                    "rooms": row.snapshot.get("selected_rooms", {}),
                    "future_service": row.snapshot.get("future_service", {}),
                    "history_sessions": [
                        s
                        for s in row.snapshot["live_sessions"]
                        if s["day"] < row.snapshot["effective_on"]
                    ],
                    "closed": row.snapshot.get("closed", False),
                    "logs": row.logs,
                    "result": {k: v for k, v in row.result.items() if k != "rollback"}
                    if row.result
                    else None,
                },
            }

    async def create(self, actor: UserContext, year: int, data: RevisionCreate) -> dict:
        """Fork current agendas and prefill a subject branch under the lifecycle lock."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            check_boundary(data.effective_on, self.auth.clock())
            snapshot, source = await self.revision_sources(actor, year)
            if source != data.expected_source_revision:
                raise AuthError(
                    409, "Le planning a changé. Rechargez avant de créer la proposition."
                )
            previous = await self.branch(year)
            if previous and not previous.snapshot.get("closed"):
                raise AuthError(409, "Terminez ou abandonnez la proposition existante.")
            pending = await self.pending_publications(year)
            if pending and data.effective_on.isoformat() < max(p["effective_on"] for p in pending):
                raise AuthError(409, "La prise d'effet doit suivre les révisions déjà publiées.")
            ids = data.subject_ids or ([data.subject_id] if data.subject_id else [])
            subjects = [s for s in snapshot["subjects"] if s["id"] in ids]
            if not ids or len(set(ids)) != len(ids) or len(subjects) != len(ids):
                raise AuthError(422, "Choisissez une matière du kholloscope publié.")
            if not any(
                c["period_end"] >= data.effective_on.isoformat() for c in snapshot["calendars"]
            ):
                raise AuthError(422, "La prise d'effet dépasse la période de khôlles.")
            published = await self.latest(year)
            effective = effective_metadata(published.result, data.effective_on)
            saved = {
                **{
                    str(s["id"]): {str(p["id"]): p["sessions"] or 0 for p in s["staff"]}
                    for s in published.snapshot["subjects"]
                },
                **effective.get("revision_wishes", {}),
            }
            snapshot["selected_rooms"] = effective.get(
                "revision_rooms",
                published.snapshot.get("selected_rooms", snapshot["effective_rooms"]),
            )
            retired = {
                f"{p['calendar_id']}:{m['group']}"
                for p in snapshot["problems"]
                if p["kind"] == "groups"
                for m in published.result.get(
                    "revision_group_mappings", published.result["mappings"]
                )
                if m["calendar_id"] == p["calendar_id"] and m["group"] not in p["active_groups"]
            }
            existing = {
                (m["calendar_id"], m["group"])
                for m in published.result.get(
                    "revision_group_mappings", published.result["mappings"]
                )
            }
            added_groups = [
                {"calendar_id": p["calendar_id"], "group": group}
                for p in snapshot["problems"]
                if p["kind"] == "groups"
                for group in p["active_groups"]
                if (p["calendar_id"], group) not in existing
            ]
            if (retired or added_groups) and set(ids) != {s["id"] for s in snapshot["subjects"]}:
                raise AuthError(422, "Sélectionnez toutes les matières pour réviser les groupes.")
            snapshot.update(
                subject_id=ids[0],
                subject_ids=ids,
                retired_groups=sorted(retired),
                added_groups=added_groups,
                effective_on=data.effective_on.isoformat(),
                return_on=data.return_on.isoformat() if data.return_on else None,
                wishes=[
                    {
                        "subject_id": subject["id"],
                        "user_id": p["id"],
                        "sessions": saved.get(str(subject["id"]), {}).get(
                            str(p["id"]), p["sessions"] or 0
                        ),
                    }
                    for subject in subjects
                    for p in subject["staff"]
                ],
                allow_moves=False,
            )
            try:
                snapshot["entitlement"] = revised_entitlement(
                    snapshot, snapshot["entitlement"], snapshot["effective_on"]
                )
            except GenerationError as error:
                raise AuthError(422, str(error)) from None
            now = datetime.now(timezone.utc)
            row = KholloscopeRun(
                id=uuid4().hex,
                school_year=year,
                status="completed",
                source_revision=source,
                revision=uuid4().hex,
                snapshot=snapshot,
                options=GenerationRules().model_dump(),
                logs=run_log_lines("Proposition créée depuis le planning publié.", now, at=now),
                result=None,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
            return {"id": row.id}

    async def editable_branch(self, actor: UserContext, year: int, revision: str) -> KholloscopeRun:
        """Require branch write rights, an observed revision and an unclosed branch."""
        await self.authorize(actor, write=True)
        row = await self.branch(year, lock=True)
        if not row or row.revision != revision or row.snapshot.get("closed"):
            raise AuthError(409, "La proposition a changé ou est fermée. Rechargez-la.")
        return row

    async def calculate(self, actor: UserContext, year: int, data: RevisionCalculate) -> dict:
        """Queue branch repair only against unchanged live sources and a complete staff roster."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable_branch(actor, year, data.expected_revision)
            boundary = data.effective_on or date.fromisoformat(row.snapshot["effective_on"])
            check_boundary(boundary, self.auth.clock())
            if row.snapshot.get("return_on") and boundary.isoformat() >= row.snapshot["return_on"]:
                raise AuthError(422, "La prise d'effet doit précéder le retour.")
            current, source = await self.revision_sources(actor, year)
            if not any(c["period_end"] >= boundary.isoformat() for c in current["calendars"]):
                raise AuthError(422, "La prise d'effet dépasse la période de khôlles.")
            pending = await self.pending_publications(year)
            if pending and boundary.isoformat() < max(p["effective_on"] for p in pending):
                raise AuthError(409, "La prise d'effet doit suivre les révisions déjà publiées.")
            if source != row.source_revision:
                raise AuthError(
                    409, "Le planning ou les intervenants ont changé. Recréez la proposition."
                )
            active = await self.db.scalar(
                select(KholloscopeRun.id).where(
                    KholloscopeRun.school_year == year,
                    KholloscopeRun.status.in_(["queued", "running"]),
                )
            )
            if active:
                raise AuthError(409, "Un calcul est déjà en cours pour cette année.")
            subjects = [
                s for s in current["subjects"] if s["id"] in revision_subjects(row.snapshot)
            ]
            wishes = [w.model_dump() for w in data.wishes]
            for wish in wishes:
                wish["subject_id"] = wish["subject_id"] or row.snapshot["subject_id"]
            allowed = {(s["id"], p["id"]) for s in subjects for p in s["staff"]}
            keys = [(w["subject_id"], w["user_id"]) for w in wishes]
            if len(keys) != len(set(keys)) or set(keys) != allowed:
                raise AuthError(422, "Renseignez tous les intervenants des matières sélectionnées.")
            for subject in subjects:
                if (
                    abs(
                        sum(w["sessions"] for w in wishes if w["subject_id"] == subject["id"])
                        - required_service(current, subject)
                    )
                    > 1e-7
                ):
                    raise AuthError(
                        422, "Les souhaits doivent couvrir le besoin de chaque matière."
                    )
            snapshot = {
                **row.snapshot,
                "wishes": wishes,
                "allow_moves": data.allow_moves,
                "effective_on": boundary.isoformat(),
            }
            if data.effective_on:
                snapshot["entitlement"] = revised_entitlement(
                    snapshot, current["entitlement"], snapshot["effective_on"]
                )
            if data.rooms is not None:
                valid_rooms = set(current["capacities"])
                if set(data.rooms) != {str(s["id"]) for s in subjects} or any(
                    not ids
                    or len(ids) != len(set(ids))
                    or any(
                        str(i) not in valid_rooms or current["capacities"][str(i)] <= 0 for i in ids
                    )
                    for ids in data.rooms.values()
                ):
                    raise AuthError(422, "Choisissez au moins une salle disponible par matière.")
                snapshot["selected_rooms"] = {**snapshot["selected_rooms"], **data.rooms}
            from app.services.kholloscope_revision_solver import revision_tasks

            try:
                tasks = revision_tasks(snapshot)
                snapshot["future_service"] = {
                    str(subject["id"]): future_service(
                        sum(
                            s["subject_id"] == subject["id"]
                            and (s.get("added") or in_revision_period(snapshot, s["day"]))
                            for s in tasks
                        ),
                        [w for w in wishes if w["subject_id"] == subject["id"]],
                    )
                    for subject in subjects
                }
            except GenerationError as error:
                raise AuthError(422, str(error)) from None
            row.snapshot, row.options = snapshot, data.rules.model_dump()
            row.status, row.result, row.revision = "queued", None, uuid4().hex
            row.created_at = row.updated_at = datetime.now(timezone.utc)
            row.logs = run_log_lines("Révision en attente de calcul.", row.created_at)
            return {"id": row.id}

    async def discard(self, actor: UserContext, year: int, data: DraftVersion) -> dict:
        """Close only the private branch, including a queued or running calculation."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable_branch(actor, year, data.expected_revision)
            row.snapshot = {**row.snapshot, "closed": True}
            row.status, row.revision = "cancelled", uuid4().hex
            return {"discarded": True}

    async def merge(self, actor: UserContext, year: int, data: RevisionMerge) -> dict:
        """Validate and atomically merge only reviewed future differences into live agendas."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable_branch(actor, year, data.expected_revision)
            if row.status != "completed" or not row.result or not data.confirmed_live:
                raise AuthError(
                    409, "Calculez une proposition complète et confirmez sa publication."
                )
            if data.effective_on.isoformat() != row.snapshot["effective_on"]:
                raise AuthError(409, "Confirmez la date exacte de prise d'effet de la proposition.")
            confirmed_return = data.return_on.isoformat() if data.return_on else None
            if confirmed_return != row.snapshot.get("return_on"):
                raise AuthError(409, "Confirmez la date exacte du retour de congé.")
            check_boundary(data.effective_on, self.auth.clock())
            # Lock live annual rows before checking revisions to serialize concurrent agenda edits.
            await self.db.scalars(
                select(TimetableYear)
                .where(TimetableYear.school_year == year)
                .order_by(TimetableYear.id)
                .with_for_update()
            )
            _, source = await self.revision_sources(actor, year)
            if source != row.source_revision:
                raise AuthError(
                    409, "Le planning a changé. La fusion est refusée ; recréez la proposition."
                )
            try:
                annual = await anyio.to_thread.run_sync(
                    partial(
                        validate_revision,
                        row.snapshot,
                        row.result["sessions"],
                        GenerationRules.from_saved_options(row.options),
                    )
                )
            except GenerationError as error:
                raise AuthError(422, str(error)) from None
            changes = revision_changes(row.snapshot, annual)
            rollback_documents = []
            for calendar in row.snapshot["calendars"]:
                updates = [
                    c
                    for c in changes
                    if (c["after"] or c["before"])["calendar_id"] == calendar["id"]
                ]
                if not updates:
                    continue
                live_calendar = await self._calendar(calendar["id"], actor, write=True)
                year_row = await self.db.get(TimetableYear, calendar["year_id"])
                document = await self.repo.document(year_row)
                updated = merge_document(document, updates)
                old = {s.id: s for s in document.series}
                changed = [s for s in updated.series if old.get(s.id) != s]
                for block in changed:
                    await self._references(block, live_calendar, historical=True)
                await self.persist_document(year_row.id, document, updated)
                year_row.revision, year_row.updated_at = uuid4().hex, datetime.now(timezone.utc)
                rollback_documents.append(
                    {
                        "year_id": year_row.id,
                        "before": document.model_dump(mode="json"),
                        "after": updated.model_dump(mode="json"),
                    }
                )
            published = await self.latest(year, lock=True)
            before_metadata = version_metadata(published.result)
            saved_wishes = {
                **published.result.get("revision_wishes", {}),
                **{
                    str(subject): {
                        str(w["user_id"]): w["sessions"]
                        for w in row.snapshot["wishes"]
                        if w.get("subject_id", row.snapshot["subject_id"]) == subject
                    }
                    for subject in revision_subjects(row.snapshot)
                },
            }
            published.result = {
                **published.result,
                "revision_entitlement": row.snapshot["entitlement"],
                "revision_group_mappings": [
                    m
                    for m in published.result.get(
                        "revision_group_mappings", published.result["mappings"]
                    )
                    if f"{m['calendar_id']}:{m['group']}"
                    not in row.snapshot.get("retired_groups", [])
                ]
                + [
                    {
                        **g,
                        "track": max(
                            (
                                m["track"]
                                for m in published.result["mappings"]
                                if m["calendar_id"] == g["calendar_id"]
                            ),
                            default=0,
                        )
                        + i
                        + 1,
                    }
                    for i, g in enumerate(row.snapshot.get("added_groups", []))
                ],
                "revision_wishes": saved_wishes,
                "revision_rooms": row.snapshot["selected_rooms"],
                "assigned_sessions": annual,
                "revisions": [
                    *published.result.get("revisions", []),
                    {
                        "id": row.id,
                        "effective_on": row.snapshot["effective_on"],
                        "return_on": row.snapshot.get("return_on"),
                        "actor_id": actor.id,
                        "at": self.auth.clock().isoformat(),
                    },
                ],
            }
            published.result = {
                **published.result,
                "revision_versions": [
                    *published.result.get("revision_versions", []),
                    {
                        "id": row.id,
                        "effective_on": row.snapshot["effective_on"],
                        "return_on": row.snapshot.get("return_on"),
                        "before": before_metadata,
                    },
                ],
            }
            row.snapshot = {**row.snapshot, "closed": True}
            row.result = {
                **row.result,
                "merged": True,
                "rollback": {
                    "documents": rollback_documents,
                    "metadata": before_metadata,
                    "published_id": published.id,
                },
            }
            row.revision, published.revision = uuid4().hex, uuid4().hex
            school_year = await self.db.get(TimetableSchoolYear, year)
            school_year.used = True
            await self.db.flush()
            _, applied_source = await self.inputs(actor, year)
            published.result = {**published.result, "applied_source_revision": applied_source}
            check_boundary(data.effective_on, self.auth.clock())
            return {"merged": True, "effective_on": row.snapshot["effective_on"]}

    async def pending_publications(self, year: int) -> list[dict]:
        """List reversible future publications without returning their private backups."""
        rows = await self.db.scalars(
            select(KholloscopeRun)
            .where(
                KholloscopeRun.school_year == year,
                KholloscopeRun.snapshot.has_key("revision_branch"),
            )
            .order_by(KholloscopeRun.created_at.desc())
        )
        return [
            {
                "id": r.id,
                "revision": r.revision,
                "effective_on": r.snapshot["effective_on"],
                "return_on": r.snapshot.get("return_on"),
                "can_rollback": bool(r.result.get("rollback")),
            }
            for r in rows
            if r.result
            and r.result.get("merged")
            and not r.result.get("rolled_back")
            and r.snapshot["effective_on"] > self.today().isoformat()
        ]

    async def change_room(self, actor: UserContext, year: int, data: RevisionRoomChange) -> dict:
        """Preview and apply a same-time room replacement only to unstarted sessions.

        Parameters
        ----------
        actor, year, data
            Authorized administrator, academic year and concurrency-bound room replacement.

        Returns
        -------
        dict
            Number of affected sessions and whether the reviewed change was published.
        """
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            await self.db.scalars(
                select(TimetableYear)
                .where(TimetableYear.school_year == year)
                .order_by(TimetableYear.id)
                .with_for_update()
            )
            snapshot, source = await self.revision_sources(actor, year)
            if source != data.expected_source_revision:
                raise AuthError(409, "Le planning a changé. Rechargez la page.")
            previous = await self.branch(year)
            if previous and not previous.snapshot.get("closed"):
                raise AuthError(409, "Terminez ou abandonnez la proposition en cours.")
            now = self.auth.clock()
            if data.starts_on < self.today():
                raise AuthError(422, "Les séances passées ne peuvent pas être modifiées.")
            pending = await self.pending_publications(year)
            if pending and data.starts_on.isoformat() < max(p["effective_on"] for p in pending):
                raise AuthError(
                    409,
                    "Une révision est déjà publiée pour une date ultérieure. "
                    "Annulez cette publication avant de modifier les salles à une date antérieure.",
                )
            if data.room_id == data.replacement_room_id:
                raise AuthError(422, "Choisissez une autre salle.")
            selected = set(data.subject_ids)
            if not selected <= {s["id"] for s in snapshot["subjects"]}:
                raise AuthError(422, "Choisissez des matières du kholloscope.")
            room = await self.db.get(TimetableRoom, data.replacement_room_id)
            if not room or not room.is_active or room.kholle_capacity <= 0:
                raise AuthError(422, "La salle choisie ne peut pas accueillir de khôlles.")
            changes = room_replacement_changes(
                snapshot["live_sessions"], selected, data.room_id, room.id, data.starts_on, now
            )
            if not changes:
                raise AuthError(422, "Aucune séance à venir ne correspond à ce changement.")
            targets = {
                (c["before"]["calendar_id"], c["before"]["series_id"], c["before"]["source_date"])
                for c in changes
            }
            events = [
                {**e, "room_id": room.id}
                if (e["calendar_id"], e["series_id"], e["source_date"]) in targets
                else e
                for e in await self.future_events()
            ]
            intervals = []
            for change in changes:
                session = change["after"]
                start = datetime.combine(date.fromisoformat(session["day"]), time(), PARIS)
                first, last = (
                    start + timedelta(seconds=session["start"]),
                    start + timedelta(seconds=session["end"]),
                )
                intervals.append((first, last))
            problem = replacement_room_problem(
                events, room.id, room.kholle_capacity, intervals, now
            )
            if problem:
                raise AuthError(422, problem + " Créez une proposition avec recalcul.")
            if not data.confirmed_live:
                return {"published": False, "count": len(changes), "changes": changes}
            backups = []
            for calendar in snapshot["calendars"]:
                updates = [c for c in changes if c["before"]["calendar_id"] == calendar["id"]]
                if not updates:
                    continue
                await self._calendar(calendar["id"], actor, write=True)
                annual = await self.db.get(TimetableYear, calendar["year_id"])
                document = await self.repo.document(annual)
                updated = merge_document(document, updates)
                await self.persist_document(annual.id, document, updated)
                annual.revision, annual.updated_at = uuid4().hex, now
                backups.append(
                    {
                        "year_id": annual.id,
                        "before": document.model_dump(mode="json"),
                        "after": updated.model_dump(mode="json"),
                    }
                )
            published = await self.latest(year, lock=True)
            before_metadata = version_metadata(published.result)
            replaced = {c["before"]["id"]: c["after"] for c in changes}
            annual_sessions = [replaced.get(s["id"], s) for s in snapshot["live_sessions"]]
            updated_rooms = {
                subject: sorted(
                    {room.id if int(subject) in selected and i == data.room_id else i for i in ids}
                )
                for subject, ids in effective_metadata(published.result, data.starts_on)
                .get(
                    "revision_rooms",
                    published.snapshot.get("selected_rooms", snapshot["effective_rooms"]),
                )
                .items()
            }
            identifier = uuid4().hex
            boundary = data.starts_on.isoformat()
            wishes = [
                {"subject_id": s["id"], "user_id": p["id"], "sessions": p["sessions"] or 0}
                for s in snapshot["subjects"]
                if s["id"] in selected
                for p in s["staff"]
            ]
            branch = KholloscopeRun(
                id=identifier,
                school_year=year,
                revision=uuid4().hex,
                source_revision=source,
                status="completed",
                options=GenerationRules().model_dump(),
                created_at=now,
                updated_at=now,
                logs=run_log_lines("Changement de salle sans déplacement.", now, at=now),
                snapshot={
                    **snapshot,
                    "room_only": True,
                    "closed": True,
                    "effective_on": boundary,
                    "subject_id": data.subject_ids[0],
                    "subject_ids": data.subject_ids,
                    "wishes": wishes,
                    "selected_rooms": updated_rooms,
                },
                result={
                    "merged": True,
                    "changes": changes,
                    "sessions": annual_sessions,
                    "quotas": [],
                    "rollback": {
                        "documents": backups,
                        "metadata": before_metadata,
                        "published_id": published.id,
                    },
                },
            )
            self.db.add(branch)
            published.result = {
                **published.result,
                "assigned_sessions": annual_sessions,
                "revision_rooms": updated_rooms,
                "revisions": [
                    *published.result.get("revisions", []),
                    {
                        "id": identifier,
                        "effective_on": boundary,
                        "actor_id": actor.id,
                        "at": now.isoformat(),
                        "room_only": True,
                    },
                ],
                "revision_versions": [
                    *published.result.get("revision_versions", []),
                    {
                        "id": identifier,
                        "effective_on": boundary,
                        "fields": ["revision_rooms"],
                        "before": before_metadata,
                    },
                ],
            }
            published.revision = uuid4().hex
            await self.db.flush()
            _, revision = await self.inputs(actor, year)
            published.result = {**published.result, "applied_source_revision": revision}
            return {"published": True, "count": len(changes)}

    async def rollback(self, actor: UserContext, year: int, data: RevisionRollback) -> dict:
        """Restore a future publication only when no later changes would be overwritten."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            row = await self.db.scalar(
                select(KholloscopeRun)
                .where(
                    KholloscopeRun.id == data.revision_id,
                    KholloscopeRun.school_year == year,
                    KholloscopeRun.snapshot.has_key("revision_branch"),
                )
                .with_for_update()
            )
            if not row or row.revision != data.expected_revision or not row.result:
                raise AuthError(409, "Cette publication a changé. Rechargez la page.")
            if row.snapshot.get("room_only"):
                if row.snapshot["effective_on"] <= self.today().isoformat():
                    raise AuthError(409, "Cette révision a déjà pris effet.")
            else:
                check_boundary(date.fromisoformat(row.snapshot["effective_on"]), self.auth.clock())
            backup = row.result.get("rollback")
            if not backup or not row.result.get("merged") or row.result.get("rolled_back"):
                raise AuthError(409, "Cette publication ne peut pas être annulée.")
            published = await self.latest(year, lock=True)
            versions = published.result.get("revision_versions", [])
            if (
                published.id != backup["published_id"]
                or not versions
                or versions[-1]["id"] != row.id
            ):
                raise AuthError(409, "Annulez d'abord la révision publiée la plus récente.")
            documents = []
            for entry in sorted(backup["documents"], key=lambda d: d["year_id"]):
                annual = await self.db.scalar(
                    select(TimetableYear)
                    .where(
                        TimetableYear.id == entry["year_id"],
                        TimetableYear.school_year == year,
                    )
                    .with_for_update()
                )
                if not annual:
                    raise AuthError(409, "Un agenda a été retiré depuis la publication.")
                await self._calendar(annual.calendar_id, actor, write=True)
                current = await self.repo.document(annual)
                if current.model_dump(mode="json") != entry["after"]:
                    raise AuthError(
                        409, "Un agenda a changé depuis la publication ; annulation refusée."
                    )
                documents.append((annual, current, YearDocument.model_validate(entry["before"])))
            for annual, current, restored in documents:
                await self.persist_document(annual.id, current, restored)
                annual.revision, annual.updated_at = uuid4().hex, datetime.now(timezone.utc)
            from app.services.kholloscope_versions import VERSION_FIELDS

            restored_result = {k: v for k, v in published.result.items() if k not in VERSION_FIELDS}
            published.result = {
                **restored_result,
                **backup["metadata"],
                "revision_versions": versions[:-1],
            }
            row.result = {
                **row.result,
                "rolled_back": True,
                "rolled_back_at": self.auth.clock().isoformat(),
                "rolled_back_by": actor.id,
            }
            row.revision, published.revision = uuid4().hex, uuid4().hex
            await self.db.flush()
            _, applied_source = await self.inputs(actor, year)
            published.result = {**published.result, "applied_source_revision": applied_source}
            if row.snapshot["effective_on"] <= self.today().isoformat():
                raise AuthError(409, "Cette révision a déjà pris effet.")
            return {"rolled_back": True}


def entitlement_rows(sessions: list[dict]) -> list:
    """Serialize stable quota keys for a source fingerprint without tuple JSON keys."""
    return sorted([*key, count] for key, count in entitlement(sessions).items())


def required_service(snapshot: dict, subject: dict) -> float:
    """Return the unchanged cycle service required by annual volumes and group counts."""
    return sum(
        r["minutes"] * c["group_count"] * subject.get("cycle_weeks", 2) / 60 / len(c["weeks"])
        for c in snapshot["calendars"]
        if c["weeks"]
        for r in c["requirements"]
        if r["subject_id"] == subject["id"]
    )
