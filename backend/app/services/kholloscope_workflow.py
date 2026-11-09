"""Ordered annual kholloscope preparation with invalidation of changed dependencies."""

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.models import KholloscopeWorkflow, TimetableRoom, TimetableSchoolYear, UserPromotion
from app.schemas.kholle import KholloscopeValidate
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.kholle import KholleService
from app.services.kholle_wishes import KholleWishesService
from app.services.kholloscope_service import balanced_service
from app.services.timetable_engine import current_school_year


def fingerprint(value: object) -> str:
    """Return a deterministic revision for JSON-compatible workflow inputs."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def promotion_preference_effective(assigned_count: int, promotion_count: int) -> bool:
    """Favor assigned promotions only when they form a nonempty proper subset of the year."""
    return 0 < assigned_count < promotion_count


def wish_errors(subjects: list[dict], needs: dict[int, float]) -> list[str]:
    """Require complete, exactly balanced two-week commitments for each allocated subject."""
    errors = []
    for subject in subjects:
        staff = subject["staff"]
        if not staff or any(person["sessions"] is None for person in staff):
            errors.append(f"{subject['name']} : renseignez tous les souhaits (0 si nécessaire).")
        elif (
            abs(
                sum(person["sessions"] for person in staff)
                - needs[subject["id"]] * subject.get("cycle_weeks", 2)
            )
            > 1e-7
        ):
            errors.append(f"{subject['name']} : les souhaits ne couvrent pas exactement le besoin.")
    return errors


def preparation_states(
    stored: dict, keys: dict[str, str], conflicts: dict[str, list[str]]
) -> tuple[dict[str, bool], dict[str, bool], dict[str, bool]]:
    """Gate each saved milestone on its current inputs and all preceding milestones.

    Parameters
    ----------
    stored, keys, conflicts
        Saved confirmations, current content fingerprints and validation diagnostics.

    Returns
    -------
    tuple[dict[str, bool], dict[str, bool], dict[str, bool]]
        Validated, review and available flags. Invalidation locks every descendant, but only
        previously confirmed steps require review; untouched steps remain not done.
    """
    validated, review, available = {}, {}, {}
    previous_valid, needs_review = True, False
    for step in ("volumes", "wishes", "service"):
        current = stored.get(step) == keys[step] and not conflicts[step]
        available[step] = previous_valid
        needs_review = needs_review or bool(stored.get(step) and not current)
        validated[step] = bool(previous_valid and current)
        review[step] = bool(stored.get(step)) and needs_review
        previous_valid = validated[step]
    return validated, review, available


class KholloscopeWorkflowService(KholleService):
    """Own workflow transactions while reusing requirement and staff calculations."""

    async def _state(self, actor: UserContext, school_year: int) -> dict:
        """Resolve current inputs and effective milestone states in the active transaction."""
        overview = await self._overview(actor, school_year)
        year = await self.db.get(TimetableSchoolYear, school_year)
        wishes = await KholleWishesService(self.auth)._state(year)
        row = await self.db.get(KholloscopeWorkflow, school_year)
        stored = row.data if row else {}
        errors = list(overview["errors"])
        if school_year < current_school_year(self.today()):
            errors.insert(0, "Cette année scolaire est terminée.")
        calendars = await self.active_calendars(school_year)
        sources = []
        ended = bool(calendars)
        for calendar in calendars:
            annual = (await self.repo.years(calendar.id))[0]
            sources.append([calendar.id, calendar.promotion_id, annual.settings])
            ended = ended and annual.ends_on < self.today()
        if ended:
            errors.append("Tous les calendriers de cette année sont terminés.")
        needs: dict[int, float] = {}
        for calendar in overview["calendars"]:
            if not calendar["weeks"] or not calendar["group_count"]:
                errors.append(f"{calendar['name']} : configurez les semaines et groupes de khôlle.")
                continue
            for subject in calendar["settings"]["subjects"]:
                needs[subject["subject_id"]] = needs.get(subject["subject_id"], 0) + (
                    subject["minutes"] * calendar["group_count"] / calendar["weeks"] / 60
                )
        subjects = [s for s in wishes["subjects"] if needs.get(s["id"], 0) > 0]
        if {identifier for identifier, need in needs.items() if need > 0} - {
            s["id"] for s in subjects
        }:
            errors.append("Réactivez les matières prévues dans les volumes de khôlles.")
        if not subjects:
            errors.append("Aucune matière avec un volume de khôlles positif pour cette année.")
        rooms = [
            {
                "id": room.id,
                "name": room.name,
                "revision": room.revision,
                "kholle_capacity": room.kholle_capacity,
            }
            for room in await self.db.scalars(
                select(TimetableRoom)
                .where(TimetableRoom.is_active.is_(True))
                .order_by(TimetableRoom.name)
            )
        ]
        teacher_ids = {person["id"] for subject in subjects for person in subject["staff"]}
        promotion_ids = {
            calendar.promotion_id for calendar in calendars if calendar.promotion_id is not None
        }
        memberships: dict[int, list[int]] = {}
        for user_id, promotion_id in await self.db.execute(
            select(UserPromotion.user_id, UserPromotion.promotion_id).where(
                UserPromotion.user_id.in_(teacher_ids),
                UserPromotion.promotion_id.in_(promotion_ids),
            )
        ):
            memberships.setdefault(user_id, []).append(promotion_id)
        saved_preferences = {
            entry["user_id"]: entry["prefer_own_promotion"]
            for entry in stored.get("teacher_preferences", [])
        }
        teacher_preferences = [
            {
                "user_id": user_id,
                "prefer_own_promotion": saved_preferences.get(user_id, True),
                "promotion_ids": sorted(memberships.get(user_id, [])),
                "effective": promotion_preference_effective(
                    len(memberships.get(user_id, [])), len(promotion_ids)
                ),
            }
            for user_id in sorted(teacher_ids)
        ]
        volume_key = fingerprint([overview["calendars"], sources])
        wishes_key = fingerprint([volume_key, subjects])
        subjects = balanced_service(subjects)
        selected_rooms = stored.get("rooms", [])
        published = await self.repo.published_kholloscope(school_year)
        if published and published.result:
            from app.services.kholloscope_versions import effective_metadata

            effective = effective_metadata(published.result, self.today())
            if "revision_rooms" in effective:
                selected_rooms = [
                    {"subject_id": int(subject), "room_ids": ids}
                    for subject, ids in effective["revision_rooms"].items()
                ]
        service_key = fingerprint(
            [wishes_key, rooms, selected_rooms, teacher_preferences, subjects]
        )
        room_errors = []
        selections = {entry["subject_id"]: entry["room_ids"] for entry in selected_rooms}
        active_rooms = {room["id"] for room in rooms if room["kholle_capacity"] > 0}
        for subject in subjects:
            chosen = selections.get(subject["id"], [])
            if not chosen:
                room_errors.append(f"{subject['name']} : sélectionnez au moins une salle.")
            elif not set(chosen) <= active_rooms:
                room_errors.append(f"{subject['name']} : salle inactive ou khôlles interdites.")
        conflicts = {
            "volumes": errors,
            "wishes": errors or wish_errors(subjects, needs),
            "service": errors or room_errors,
        }
        keys = {"volumes": volume_key, "wishes": wishes_key, "service": service_key}
        validated, review, available = preparation_states(stored, keys, conflicts)
        return {
            "school_year": school_year,
            "revision": fingerprint(
                [
                    volume_key,
                    wishes["revision"],
                    rooms,
                    teacher_preferences,
                    stored,
                    row.revision if row else None,
                ]
            ),
            "errors": errors,
            "wish_errors": wish_errors(subjects, needs),
            "available": available,
            "conflicts": conflicts,
            "validated": validated,
            "review": review,
            "needs": needs,
            "subjects": subjects,
            "rooms": rooms,
            "selected_rooms": selected_rooms,
            "teacher_preferences": teacher_preferences,
            "keys": keys,
        }

    async def read(self, actor: UserContext, school_year: int) -> dict:
        """Read administrator-only progress; stale milestones are effectively invalidated."""
        async with self.db.begin():
            await self.authorize(actor)
            return await self._state(actor, school_year)

    async def validate(
        self, actor: UserContext, school_year: int, data: KholloscopeValidate
    ) -> dict:
        """Save a valid milestone atomically, checking ordering, inputs and canonical rooms."""
        async with self.db.begin():
            await self.auth._lifecycle_lock()
            await self.authorize(actor, write=True)
            await self.require_unpublished_kholloscope(school_year)
            year = await self.db.get(TimetableSchoolYear, school_year, with_for_update=True)
            if year is None:
                raise AuthError(404, "Année scolaire introuvable.")
            state = await self._state(actor, school_year)
            if state["revision"] != data.expected_revision:
                raise AuthError(409, "La préparation a changé. Rechargez la page.")
            if state["errors"]:
                raise AuthError(422, " ".join(state["errors"]))
            if not state["available"][data.step]:
                raise AuthError(409, "Validez d’abord l’étape précédente.")
            if data.step == "wishes" and state["wish_errors"]:
                raise AuthError(422, " ".join(state["wish_errors"]))
            row = await self.db.get(KholloscopeWorkflow, school_year)
            stored = dict(row.data) if row else {}
            if data.step == "service":
                ids = [item.subject_id for item in data.rooms]
                if len(set(ids)) != len(ids) or set(ids) != {s["id"] for s in state["subjects"]}:
                    raise AuthError(422, "Choisissez des salles pour chaque matière de khôlle.")
                allowed = {room["id"] for room in state["rooms"] if room["kholle_capacity"] > 0}
                if any(not set(item.room_ids) <= allowed for item in data.rooms):
                    raise AuthError(422, "Sélectionnez uniquement des salles actives du catalogue.")
                stored["rooms"] = [item.model_dump() for item in data.rooms]
                if data.teacher_preferences is not None:
                    ids = [item.user_id for item in data.teacher_preferences]
                    expected = {item["user_id"] for item in state["teacher_preferences"]}
                    if len(ids) != len(set(ids)) or set(ids) != expected:
                        raise AuthError(
                            422, "Renseignez les préférences des intervenants autorisés."
                        )
                    stored["teacher_preferences"] = [
                        item.model_dump() for item in data.teacher_preferences
                    ]
                stored["service"] = fingerprint(
                    [
                        state["keys"]["wishes"],
                        state["rooms"],
                        stored["rooms"],
                        [
                            {
                                **item,
                                "prefer_own_promotion": next(
                                    (
                                        p["prefer_own_promotion"]
                                        for p in stored.get("teacher_preferences", [])
                                        if p["user_id"] == item["user_id"]
                                    ),
                                    item["prefer_own_promotion"],
                                ),
                            }
                            for item in state["teacher_preferences"]
                        ],
                        state["subjects"],
                    ]
                )
            else:
                stored[data.step] = state["keys"][data.step]
            if row is None:
                row = KholloscopeWorkflow(
                    school_year=school_year, data=stored, revision=uuid4().hex
                )
                self.db.add(row)
            else:
                if row.data != stored:
                    row.data, row.revision = stored, uuid4().hex
            year.used = True
            await self.db.flush()
            return await self._state(actor, school_year)
