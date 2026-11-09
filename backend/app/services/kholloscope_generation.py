"""Administrator-owned durable generation queue and explicitly assigned draft publication."""

from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from uuid import uuid4

import anyio
from sqlalchemy import delete, select

from app.models import (
    KholloscopeRun,
    Promotion,
    PromotionGroup,
    PromotionGroupMember,
    TeacherAvailability,
    TimetableSeries,
    TimetableYear,
    User,
)
from app.repositories.groups import active_kholle_group
from app.schemas.kholloscope_generation import (
    ApplyDraft,
    AssignGroups,
    DraftMove,
    DraftVersion,
    GenerationStart,
    RemoveKholloscope,
)
from app.schemas.timetable import SeriesData
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.kholle import kholle_weeks
from app.services.kholloscope_assignment import remove_kholles, repair_rotation, rotated_sessions
from app.services.kholloscope_pdf import render_kholloscope_pdf
from app.services.kholloscope_solver import GenerationError, free_lunch, overlaps
from app.services.kholloscope_versions import effective_sessions
from app.services.kholloscope_worker import run_log_lines
from app.services.kholloscope_workflow import KholloscopeWorkflowService, fingerprint
from app.services.teacher_availability import availability_settings, effective_ranges
from app.services.timetable_assignments import assigned_teachers
from app.services.timetable_engine import occurrences


def generation_saved(result: dict | None) -> bool:
    """Recognize explicit confirmation and preserve already assigned legacy drafts.

    Parameters
    ----------
    result
        Persisted draft result, including older results without a saved flag.

    Returns
    -------
    bool
        Whether generation was confirmed or the legacy draft already reached assignment.
    """
    return bool(
        result
        and (
            result.get("saved")
            or result.get("mappings")
            or result.get("applied")
            or result.get("withdrawn")
        )
    )


class KholloscopeGenerationService(KholloscopeWorkflowService):
    """Snapshot only counts for solving; read real group numbers exclusively at assignment."""

    async def pdf(self, actor: UserContext, year: int) -> bytes:
        """Export only the current authorized saved assignment, outside database transactions.

        Parameters
        ----------
        actor, year
            Authenticated administrator and selected academic year.

        Returns
        -------
        bytes
            A private annual colloscope PDF with server-resolved account attribution.
        """
        choices = await self.group_choices(actor, year)
        if not choices["assigned_sessions"] and not choices.get("export_available"):
            raise AuthError(409, "Affectez les groupes avant de télécharger le kholloscope.")
        async with self.db.begin():
            if "users.read" not in await self.auth.repo.permissions(actor.id):
                raise AuthError(
                    403,
                    "Le droit de consulter les élèves est requis "
                    "pour exporter les groupes nominatifs.",
                )
        catalog = await self.catalog(actor)
        async with self.db.begin():
            await self.authorize(actor)
            row = await self.latest(year)
            if row is None or row.revision != choices["revision"]:
                raise AuthError(409, "Le kholloscope a changé. Rechargez avant de télécharger.")
            choices["assigned_sessions"] = effective_sessions(row.result, self.today())
            if not choices["assigned_sessions"]:
                raise AuthError(409, "Affectez les groupes avant de télécharger le kholloscope.")
            calendars = deepcopy(row.snapshot["calendars"])
            for calendar in calendars:
                current = await self._calendar(calendar["id"], actor, write=False)
                numbers = sorted(
                    {
                        s["group"]
                        for s in choices["assigned_sessions"]
                        if s["calendar_id"] == calendar["id"]
                    }
                )
                members = list(
                    await self.db.execute(
                        select(PromotionGroupMember.group_number, User)
                        .join(User, User.id == PromotionGroupMember.user_id)
                        .where(
                            PromotionGroupMember.promotion_id == current.promotion_id,
                            PromotionGroupMember.kind == "kholles",
                        )
                    )
                )
                calendar["groups"] = [
                    {
                        "number": number,
                        "students": sorted(
                            [
                                {
                                    "last_name": self.auth.cipher.decrypt(
                                        pupil.id, "last_name", pupil.last_name_encrypted
                                    )
                                    or "",
                                    "first_name": self.auth.cipher.decrypt(
                                        pupil.id, "first_name", pupil.first_name_encrypted
                                    )
                                    or "",
                                }
                                for group, pupil in members
                                if group == number
                            ],
                            key=lambda s: (s["last_name"].casefold(), s["first_name"].casefold()),
                        ),
                    }
                    for number in numbers
                ]
            user = await self.db.get(User, actor.id)
            requester = self._identity(user)["name"]
        return await anyio.to_thread.run_sync(
            render_kholloscope_pdf,
            calendars,
            choices["assigned_sessions"],
            catalog,
            requester,
            datetime.now(timezone.utc),
        )

    async def inputs(self, actor: UserContext, year: int) -> tuple[dict, str]:
        """Collect active annual source revisions without accessing pupil memberships."""
        state = await self._state(actor, year)
        documents = await self.repo.teaching_documents(year, include_private=True)
        availability = list(
            await self.db.scalars(
                select(TeacherAvailability).where(TeacherAvailability.school_year == year)
            )
        )
        key = fingerprint(
            [
                state["revision"],
                sorted((r.id, r.revision) for r, _ in documents),
                sorted((r.user_id, r.revision, r.ranges) for r in availability),
            ]
        )
        return {"state": state, "documents": documents, "availability": availability}, key

    async def snapshot(
        self, actor: UserContext, year: int, *, require_prepared: bool = True
    ) -> tuple[dict, str]:
        """Resolve private course occupancy and effective availability for the solver."""
        inputs, revision = await self.inputs(actor, year)
        state = inputs["state"]
        if require_prepared and (not all(state["validated"].values()) or state["wish_errors"]):
            raise AuthError(
                409, "Validez les volumes, les souhaits équilibrés et les salles avant de générer."
            )
        annual = {row.calendar_id: (row, doc) for row, doc in inputs["documents"]}
        calendars = []
        for item in (await self._overview(actor, year))["calendars"]:
            row, doc = annual[item["id"]]
            calendar = await self._calendar(item["id"], actor, write=True)
            promotion = await self.db.get(Promotion, calendar.promotion_id)
            if promotion is None or not promotion.is_active:
                raise AuthError(409, "Chaque calendrier doit être affecté à une promotion active.")
            weeks = [
                w
                for w in kholle_weeks(doc.settings, year)
                if w["eligible"]
                and item["settings"]["start"] <= w["start"] <= item["settings"]["end"]
            ]
            calendars.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "group_count": item["group_count"],
                    "settings": doc.settings.model_dump(mode="json"),
                    "weeks": weeks,
                    "requirements": item["settings"]["subjects"],
                    "period_start": item["settings"]["start"],
                    "period_end": item["settings"]["end"],
                    "year_id": row.id,
                }
            )
        bookings = {}
        for row, doc in inputs["documents"]:
            for event in occurrences(doc):
                start, end = (
                    datetime.fromisoformat(event["start"]),
                    datetime.fromisoformat(event["end"]),
                )
                bookings.setdefault(start.date().isoformat(), []).append(
                    {
                        "start": start.hour * 3600 + start.minute * 60 + start.second,
                        "end": end.hour * 3600 + end.minute * 60 + end.second,
                        "calendar_id": row.calendar_id,
                        "teachers": assigned_teachers(event),
                        "room_id": event["room_id"],
                        "kind": event["kind"],
                    }
                )
        staff = {p["id"] for s in state["subjects"] for p in s["staff"]}
        explicit = {r.user_id: r.ranges for r in inputs["availability"]}
        promotions = {
            c.id: c.promotion_id for c in await self.repo.calendars(None, school_year=year)
        }
        return {
            "base_date": f"{year}-09-01",
            "calendars": calendars,
            "bookings": bookings,
            "availability": {
                str(t): effective_ranges(explicit.get(t), availability_settings(year))
                for t in staff
            },
            "subjects": state["subjects"],
            "capacities": {str(r["id"]): r["kholle_capacity"] for r in state["rooms"]},
            "selected_rooms": {
                str(s["subject_id"]): s["room_ids"] for s in state["selected_rooms"]
            },
            "preferences": {
                str(p["user_id"]): {
                    **p,
                    "calendar_ids": [
                        identifier
                        for identifier, promotion in promotions.items()
                        if promotion in p["promotion_ids"]
                    ],
                }
                for p in state["teacher_preferences"]
            },
        }, revision

    async def latest(self, year: int, *, lock: bool = False) -> KholloscopeRun | None:
        """Read the last annual job, optionally locking its draft for mutation."""
        query = (
            select(KholloscopeRun)
            .where(
                KholloscopeRun.school_year == year,
                ~KholloscopeRun.snapshot.has_key("revision_branch"),
            )
            .order_by(KholloscopeRun.created_at.desc())
            .limit(1)
        )
        return await self.db.scalar(query.with_for_update() if lock else query)

    async def view(self, actor: UserContext, year: int) -> dict:
        """Return resumable progress without revealing internal anonymous solver witnesses."""
        async with self.db.begin():
            inputs, revision = await self.inputs(actor, year)
            row = await self.latest(year)
            revision_state = {"conflicts": False, "pending": False}
            pending_publications = []
            if row and row.result and row.result.get("applied"):
                from app.services.kholloscope_revision import KholloscopeRevisionService

                revisions = KholloscopeRevisionService(self.auth)
                branch = await revisions.branch(year)
                pending_publications = await revisions.pending_publications(year)
                revision_state = {
                    "conflicts": bool(await revisions.revision_problems(year, row)),
                    "pending": bool(branch and not branch.snapshot.get("closed")),
                }
            return {
                "pending_publications": pending_publications,
                "revision_state": revision_state,
                "source_revision": revision,
                "ready": all(inputs["state"]["validated"].values()),
                "run": self.serialize(row, revision),
            }

    def serialize(self, row: KholloscopeRun | None, revision: str) -> dict | None:
        """Expose public placement data, keeping proof tracks hidden until group assignment."""
        if row is None:
            return None
        result = deepcopy(row.result)
        if result:
            if result.get("applied") and result.get("revisions"):
                result["sessions"] = deepcopy(result.get("assigned_sessions", result["sessions"]))
            result.pop("revision_versions", None)
            for quota in result["quotas"]:
                quota.pop("track_sessions", None)
            for session in result["sessions"]:
                session.pop("track", None)
            for session in result["template"]:
                session.pop("track", None)
            result.pop("assigned_sessions", None)
        preview_calendars = []
        if row.snapshot:
            from app.schemas.timetable import YearSettings
            from app.services.timetable_engine import daily_slots

            preview_calendars = [
                {
                    "id": c["id"],
                    "calendar_id": c["id"],
                    "school_year": row.school_year,
                    "settings": c["settings"],
                    "revision": None,
                    "slots": daily_slots(YearSettings.model_validate(c["settings"])),
                    "weeks": {w["start"]: w["number"] for w in c["weeks"]},
                    "series": [],
                }
                for c in row.snapshot["calendars"]
            ]
        return {
            "id": row.id,
            "status": row.status,
            "revision": row.revision,
            "stale": (
                row.result.get("applied_source_revision", row.source_revision)
                if row.result
                else row.source_revision
            )
            != revision,
            "rules": row.options,
            "logs": row.logs,
            "result": result,
            "calendars": preview_calendars,
        }

    async def start(self, actor: UserContext, year: int, data: GenerationStart) -> dict:
        """Queue a private draft after serializing launches and checking source revisions."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            await self.require_unpublished_kholloscope(year)
            snapshot, revision = await self.snapshot(actor, year)
            if revision != data.expected_revision:
                raise AuthError(409, "Les données ont changé. Rechargez avant de générer.")
            previous = await self.latest(year)
            if previous and previous.status in {"queued", "running"}:
                raise AuthError(409, "Un calcul est déjà en cours pour cette année.")
            if (
                data.rules.preserve_locks
                and previous
                and previous.source_revision == revision
                and previous.result
            ):
                snapshot["pins"] = {
                    s["id"]: s for s in previous.result["sessions"] if s.get("locked")
                }
            now = datetime.now(timezone.utc)
            row = KholloscopeRun(
                id=uuid4().hex,
                school_year=year,
                status="queued",
                source_revision=revision,
                revision=uuid4().hex,
                snapshot=snapshot,
                options=data.rules.model_dump(),
                logs=run_log_lines("Calcul en attente d'un exécutant.", now, at=now),
                result=None,
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
            return {"id": row.id}

    async def cancel(self, actor: UserContext, year: int, run_id: str) -> dict:
        """Cancel the latest active job; workers observe cancellation on their heartbeat."""
        async with self.db.begin():
            await self.authorize(actor, write=True)
            row = await self.latest(year, lock=True)
            if row is None or row.id != run_id:
                raise AuthError(
                    409, "Le calcul affiché n'est plus le dernier calcul de cette année."
                )
            if row and row.status in {"queued", "running"}:
                row.status = "cancelled"
                row.logs = [*row.logs, *run_log_lines("Annulation demandée.", row.created_at)][
                    -500:
                ]
                row.updated_at = datetime.now(timezone.utc)
            return {"cancelled": True}

    async def editable(self, actor: UserContext, year: int, revision: str) -> KholloscopeRun:
        """Require a current completed draft and fresh source data for every editing action."""
        await self.authorize(actor, write=True)
        row = await self.latest(year, lock=True)
        if (
            not row
            or row.status != "completed"
            or not row.result
            or row.result.get("applied")
            or row.result.get("withdrawn")
        ):
            raise AuthError(409, "Aucun brouillon modifiable.")
        if row.revision != revision:
            raise AuthError(409, "Le brouillon a changé. Rechargez-le.")
        _, current = await self.inputs(actor, year)
        if current != row.source_revision:
            raise AuthError(
                409, "Les cours, disponibilités ou règles ont changé. Régénérez le brouillon."
            )
        return row

    async def save(self, actor: UserContext, year: int, data: DraftVersion) -> dict:
        """Persist explicit generation confirmation after rights and revision checks.

        Parameters
        ----------
        actor, year, data
            Current administrator, selected year and observed draft revision.

        Returns
        -------
        dict
            The confirmed draft revision; no live calendar is modified.
        """
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable(actor, year, data.expected_revision)
            row.result = {**row.result, "saved": True}
            row.revision = uuid4().hex
            return {"revision": row.revision}

    async def move(self, actor: UserContext, year: int, data: DraftMove) -> dict:
        """Validate a manual room/time correction against all resource and anonymous constraints."""
        from app.schemas.kholloscope_generation import GenerationRules
        from app.services.kholloscope_solver import validate_draft

        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable(actor, year, data.expected_revision)
            result = deepcopy(row.result)
            target = next((s for s in result["sessions"] if s["id"] == data.session_id), None)
            if target is None:
                raise AuthError(404, "Séance introuvable.")
            duration = target["end"] - target["start"]
            target.update(
                day=data.day.isoformat(),
                start=data.start,
                end=data.start + duration,
                room_id=data.room_id,
                locked=data.locked,
            )
            try:
                validate_draft(
                    row.snapshot, result, GenerationRules.from_saved_options(row.options)
                )
            except GenerationError as error:
                raise AuthError(422, str(error)) from None
            result["mappings"] = []
            result["saved"] = False
            result.pop("assigned_sessions", None)
            result.pop("assignment_mode", None)
            result.pop("rotation_adjustments", None)
            row.result, row.revision = result, uuid4().hex
            return {"revision": row.revision}

    async def group_choices(self, actor: UserContext, year: int) -> dict:
        """Read real numbered groups only in the separate post-generation assignment step."""
        async with self.db.begin():
            await self.authorize(actor)
            row = await self.latest(year)
            if not row or row.status != "completed":
                raise AuthError(409, "Générez un calendrier avant d'affecter les groupes.")
            if not generation_saved(row.result):
                raise AuthError(409, "Sauvegardez la proposition avant d’affecter les groupes.")
            inputs, revision = await self.inputs(actor, year)
            management = row.result and (row.result.get("applied") or row.result.get("withdrawn"))
            if not management and (
                not all(inputs["state"]["validated"].values()) or revision != row.source_revision
            ):
                raise AuthError(409, "Reconfirmez la préparation puis régénérez le calendrier.")
            calendars = await self.repo.calendars(None, school_year=year)
            groups = list(
                await self.db.scalars(
                    select(PromotionGroup).where(
                        PromotionGroup.promotion_id.in_([c.promotion_id for c in calendars]),
                        PromotionGroup.kind == "kholles",
                        active_kholle_group(),
                    )
                )
            )
            return {
                "revision": row.revision,
                "export_available": bool(effective_sessions(row.result, self.today())),
                "mappings": row.result.get("revision_group_mappings", row.result["mappings"]),
                "schedule": row.result.get("assigned_sessions", row.result["sessions"])
                if row.result.get("revisions")
                else row.result["sessions"],
                "assigned_sessions": row.result.get("assigned_sessions", []),
                "mode": row.result.get("assignment_mode", "fixed"),
                "rotation_adjustments": row.result.get("rotation_adjustments", 0),
                "calendars": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "groups": sorted(
                            g.number for g in groups if g.promotion_id == c.promotion_id
                        ),
                        "tracks": next(
                            s["group_count"] for s in row.snapshot["calendars"] if s["id"] == c.id
                        )
                        if "revision_group_mappings" not in row.result
                        else sum(
                            m["calendar_id"] == c.id for m in row.result["revision_group_mappings"]
                        ),
                    }
                    for c in calendars
                    if any(s["id"] == c.id for s in row.snapshot["calendars"])
                ],
            }

    async def assign(self, actor: UserContext, year: int, data: AssignGroups) -> dict:
        """Save a complete bijection between anonymous tracks and real promotion group numbers."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable(actor, year, data.expected_revision)
            if not generation_saved(row.result):
                raise AuthError(409, "Sauvegardez la proposition avant d’affecter les groupes.")
            calendars = {c.id: c for c in await self.repo.calendars(None, school_year=year)}
            available = {
                identifier: sorted(
                    await self.db.scalars(
                        select(PromotionGroup.number).where(
                            PromotionGroup.promotion_id == calendar.promotion_id,
                            PromotionGroup.kind == "kholles",
                            active_kholle_group(),
                        )
                    )
                )
                for identifier, calendar in calendars.items()
            }
            mappings = (
                [m.model_dump() for m in data.mappings]
                if data.mappings is not None
                else [
                    {"calendar_id": c["id"], "track": i + 1, "group": number}
                    for c in row.snapshot["calendars"]
                    for i, number in enumerate(available[c["id"]])
                ]
            )
            expected = {
                (c["id"], t)
                for c in row.snapshot["calendars"]
                for t in range(1, c["group_count"] + 1)
            }
            keys = [(m["calendar_id"], m["track"]) for m in mappings]
            if len(keys) != len(set(keys)) or set(keys) != expected:
                raise AuthError(422, "Affectez chaque position abstraite exactement une fois.")
            for identifier in calendars:
                choices = [m["group"] for m in mappings if m["calendar_id"] == identifier]
                if not choices:
                    continue
                numbers = set(
                    await self.db.scalars(
                        select(PromotionGroup.number).where(
                            PromotionGroup.promotion_id == calendars[identifier].promotion_id,
                            PromotionGroup.kind == "kholles",
                            active_kholle_group(),
                        )
                    )
                )
                if len(choices) != len(set(choices)) or set(choices) != numbers:
                    raise AuthError(
                        422, "Chaque groupe de la promotion doit être affecté une seule fois."
                    )
            assigned = await self.resolve_assignment(row, year, mappings, data.mode)
            row.result = {
                **row.result,
                "mappings": mappings,
                "assignment_mode": data.mode,
                "assigned_sessions": assigned,
                "rotation_adjustments": sum(
                    a["group"] != b["group"]
                    for a, b in zip(
                        assigned,
                        rotated_sessions(row.snapshot, row.result, mappings, data.mode),
                        strict=True,
                    )
                ),
            }
            row.revision = uuid4().hex
            return {"revision": row.revision}

    async def resolve_assignment(
        self,
        row: KholloscopeRun,
        year: int,
        mappings: list[dict],
        mode: str,
        *,
        preserve_saved: bool = False,
    ) -> list[dict]:
        """Revalidate volumes, meals, overlaps and real pupil boundaries after rotation."""
        from app.schemas.kholloscope_generation import GenerationRules
        from app.services.kholloscope_solver import validate_draft

        rules = GenerationRules.from_saved_options(row.options)
        identity = [
            {"calendar_id": identifier, "track": i + 1, "group": group}
            for identifier in {m["calendar_id"] for m in mappings}
            for i, group in enumerate(
                sorted(m["group"] for m in mappings if m["calendar_id"] == identifier)
            )
        ]
        assigned = (
            deepcopy(row.result["assigned_sessions"])
            if preserve_saved and row.result.get("assigned_sessions")
            else rotated_sessions(row.snapshot, row.result, mappings, mode)
        )
        if mode != "fixed" and not preserve_saved:
            context = await self.assignment_context(year, mappings)
            try:
                assigned = await anyio.to_thread.run_sync(
                    partial(
                        repair_rotation, row.snapshot, row.result, mappings, mode, rules, context
                    )
                )
            except GenerationError as error:
                raise AuthError(422, str(error)) from None
        try:
            validate_draft(
                row.snapshot,
                {**row.result, "sessions": assigned},
                rules,
                coverage_tracks={s["id"]: s["track"] for s in row.result["sessions"]},
            )
            await self.verify_memberships(year, assigned, identity, row.snapshot)
        except (GenerationError, AuthError) as error:
            raise AuthError(422, str(error)) from None
        return assigned

    async def assignment_context(self, year: int, mappings: list[dict]) -> dict:
        """Load pupil constraints only at the authorized real-group assignment stage.

        Parameters
        ----------
        year, mappings
            Selected academic year and validated base group numbers.

        Returns
        -------
        dict
            Pupil IDs by group and their calendar memberships; never serialized to the browser.
        """
        calendars = {
            c.id: c.promotion_id for c in await self.repo.calendars(None, school_year=year)
        }
        members = list(
            await self.db.scalars(
                select(PromotionGroupMember).where(
                    PromotionGroupMember.kind == "kholles",
                    PromotionGroupMember.promotion_id.in_(calendars.values()),
                    PromotionGroupMember.user_id.in_(
                        select(User.id).where(User.status != "disabled")
                    ),
                )
            )
        )
        pupils = {
            (m["calendar_id"], m["group"]): {
                member.user_id
                for member in members
                if member.promotion_id == calendars[m["calendar_id"]]
                and member.group_number == m["group"]
            }
            for m in mappings
        }
        pupil_calendars = {}
        for member in members:
            pupil_calendars.setdefault(member.user_id, set()).update(
                c for c, promotion in calendars.items() if promotion == member.promotion_id
            )
        return {"pupils": pupils, "pupil_calendars": pupil_calendars}

    async def verify_memberships(
        self, year: int, sessions: list[dict], mappings: list[dict], snapshot: dict
    ) -> None:
        """At assignment time only, reject real pupils shared by overlapping promotions."""
        bookings = snapshot["bookings"]
        calendars = {
            c.id: c.promotion_id for c in await self.repo.calendars(None, school_year=year)
        }
        members = list(
            await self.db.scalars(
                select(PromotionGroupMember).where(
                    PromotionGroupMember.kind == "kholles",
                    PromotionGroupMember.promotion_id.in_(calendars.values()),
                )
            )
        )
        recipients = {}
        for mapping in mappings:
            recipients[mapping["calendar_id"], mapping["track"]] = {
                m.user_id
                for m in members
                if m.promotion_id == calendars[mapping["calendar_id"]]
                and m.group_number == mapping["group"]
            }
        by_day, pupil_busy, pupil_meals = {}, {}, {}
        for session in sessions:
            audience = recipients.get((session["calendar_id"], session["track"]), set())
            cfg = next(
                c["settings"] for c in snapshot["calendars"] if c["id"] == session["calendar_id"]
            )
            for pupil in audience:
                pupil_busy.setdefault((pupil, session["day"]), []).append(
                    (session["start"], session["end"])
                )
                pupil_meals[pupil, session["day"], session["calendar_id"]] = cfg
            promotions = {m.promotion_id for m in members if m.user_id in audience}
            for event in bookings.get(session["day"], []):
                if calendars.get(event["calendar_id"]) in promotions and overlaps(
                    session["start"], session["end"], event["start"], event["end"]
                ):
                    raise AuthError(
                        422, "Un élève du groupe a un cours sur une autre promotion à cet horaire."
                    )
            for other in by_day.get(session["day"], []):
                if audience & recipients.get(
                    (other["calendar_id"], other["track"]), set()
                ) and overlaps(session["start"], session["end"], other["start"], other["end"]):
                    raise AuthError(
                        422,
                        "Cette affectation crée un chevauchement pour des élèves "
                        "communs à plusieurs promotions.",
                    )
            by_day.setdefault(session["day"], []).append(session)
        for (pupil, day, _), cfg in pupil_meals.items():
            promotions = {m.promotion_id for m in members if m.user_id == pupil}
            busy = pupil_busy[pupil, day] + [
                (e["start"], e["end"])
                for e in bookings.get(day, [])
                if calendars.get(e["calendar_id"]) in promotions
            ]
            if not free_lunch(
                busy,
                cfg.get("lunch_start", 43200),
                cfg.get("lunch_end", 50400),
                cfg["session_minutes"] * 60,
            ):
                raise AuthError(
                    422,
                    "L'affectation ne conserve pas une pause repas suffisante pour chaque élève.",
                )

    async def apply(self, actor: UserContext, year: int, data: ApplyDraft) -> dict:
        """Apply a fully assigned draft atomically, preserving existing series and diffusion."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            row = await self.editable(actor, year, data.expected_revision)
            if not data.confirmed_live:
                raise AuthError(409, "Confirmez l'application aux agendas.")
            mappings = {(m["calendar_id"], m["track"]): m["group"] for m in row.result["mappings"]}
            expected = {
                (c["id"], t)
                for c in row.snapshot["calendars"]
                for t in range(1, c["group_count"] + 1)
            }
            if set(mappings) != expected:
                raise AuthError(
                    422, "Terminez l'affectation des groupes avant d'appliquer le calendrier."
                )
            assigned = await self.resolve_assignment(
                row,
                year,
                row.result["mappings"],
                row.result.get("assignment_mode", "fixed"),
                preserve_saved=True,
            )
            for calendar in row.snapshot["calendars"]:
                annual = await self.db.scalar(
                    select(TimetableYear)
                    .where(
                        TimetableYear.calendar_id == calendar["id"],
                        TimetableYear.school_year == year,
                    )
                    .with_for_update()
                )
                live_calendar = await self._calendar(calendar["id"], actor, write=True)
                series = []
                for s in assigned:
                    if s["calendar_id"] != calendar["id"]:
                        continue
                    identifier = uuid4().hex
                    series.append(
                        SeriesData(
                            id=identifier,
                            lineage=identifier,
                            starts_on=s["day"],
                            start_slot=0,
                            duration_slots=2,
                            start_time=s["start"],
                            end_time=s["end"],
                            subject_id=s["subject_id"],
                            teacher_id=s["teacher_id"],
                            teacher_ids=[s["teacher_id"]],
                            room_id=s["room_id"],
                            kind="kholle",
                            title="",
                            interval=0,
                            until=None,
                            target_kind="kholles",
                            target_number=s["group"],
                            target_user_id=None,
                            exceptions={},
                        )
                    )
                checked = set()
                existing = await self.repo.document(annual)
                if len(existing.series) + len(series) > 5000:
                    raise AuthError(422, "Limite de 5000 séries par agenda atteinte.")
                for block in series:
                    key = (block.subject_id, block.teacher_id, block.room_id, block.target_number)
                    if key not in checked:
                        await self._references(block, live_calendar)
                        checked.add(key)
                await self.repo.store_series_many(annual.id, series)
                annual.revision, annual.updated_at = uuid4().hex, datetime.now(timezone.utc)
            row.result = {**row.result, "applied": True, "assigned_sessions": assigned}
            await self.db.flush()
            _, applied_source = await self.inputs(actor, year)
            row.result = {**row.result, "applied_source_revision": applied_source}
            row.revision = uuid4().hex
            return {"revision": row.revision, "applied": True}

    async def remove(self, actor: UserContext, year: int, data: RemoveKholloscope) -> dict:
        """Remove confirmed live kholles even after edits, preserving unrelated event types."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            if data.scope != "future":
                raise AuthError(
                    409, "Le retrait est limité aux khôlles à venir. L’historique est conservé."
                )
            row = await self.latest(year, lock=True)
            if not row or not row.result or not row.result.get("applied"):
                raise AuthError(409, "Aucun kholloscope affecté à retirer.")
            _, current = await self.inputs(actor, year)
            if row.revision != data.expected_revision or current != data.expected_source_revision:
                raise AuthError(
                    409, "Les agendas ont changé. Rechargez avant de confirmer le retrait."
                )
            if data.confirmation != "SUPPRIMER":
                raise AuthError(409, "Saisissez SUPPRIMER pour confirmer le retrait des khôlles.")
            removed = 0
            for calendar in row.snapshot["calendars"]:
                await self._calendar(calendar["id"], actor, write=True)
                annual = await self.db.scalar(
                    select(TimetableYear)
                    .where(
                        TimetableYear.calendar_id == calendar["id"],
                        TimetableYear.school_year == year,
                    )
                    .with_for_update()
                )
                if annual is None:
                    continue
                document = await self.repo.document(annual)
                updated, count = remove_kholles(document, self.today(), data.scope)
                if not count:
                    continue
                removed += count
                await self.db.execute(
                    delete(TimetableSeries).where(
                        TimetableSeries.year_id == annual.id,
                        TimetableSeries.id.not_in([s.id for s in updated.series]),
                    )
                )
                await self.repo.store_series_many(annual.id, updated.series)
                annual.revision, annual.updated_at = uuid4().hex, datetime.now(timezone.utc)
            audit = {
                "actor_id": actor.id,
                "at": self.auth.clock().isoformat(),
                "scope": data.scope,
                "removed": removed,
            }
            row.result = {**row.result, "applied": False, "withdrawn": audit}
            row.logs = [
                *row.logs,
                *run_log_lines(
                    f"Retrait confirmé : {removed} khôlles ({data.scope}).", row.created_at
                ),
            ][-500:]
            row.revision = uuid4().hex
            return {"revision": row.revision, "removed": removed}
