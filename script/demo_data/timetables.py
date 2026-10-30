"""Annual calendars and compact weekly series, resumed without duplicating occurrences."""

import json
from datetime import date, timedelta

from .client import Client
from .configuration import SeedError, Settings
from .planning import PERIODS, Lesson

FIELDS = (
    "starts_on",
    "start_slot",
    "duration_slots",
    "subject_id",
    "teacher_id",
    "room_id",
    "kind",
    "title",
    "interval",
    "until",
    "target_kind",
    "target_number",
    "target_user_id",
)


def fingerprint(block: dict) -> str:
    """Compare recurrence content independently of UUIDs and optimistic revisions."""
    return json.dumps({field: block.get(field) for field in FIELDS}, sort_keys=True)


def blocks_for_year(
    lessons: list[Lesson], year: dict, catalogue: dict, rooms: dict, german: dict
) -> list[dict]:
    """Resolve half-slot positions using the server's grid rather than duplicating its engine."""
    start = date.fromisoformat(year["settings"]["start"])
    result = []
    for lesson in lessons:
        expected = PERIODS[lesson.period]
        slot = next(
            (index for index, value in enumerate(year["slots"]) if value[0] == expected),
            None,
        )
        if (
            slot is None
            or slot + 1 >= len(year["slots"])
            or year["slots"][slot + 1][1] != expected + 3300
        ):
            raise SeedError(
                "La grille du calendrier ne correspond pas aux séances de 55 minutes du scénario."
            )
        result.append(
            {
                "starts_on": (start + timedelta(days=lesson.weekday)).isoformat(),
                "start_slot": slot,
                "duration_slots": 2,
                "subject_id": catalogue["subjects"][lesson.subject]["id"],
                "teacher_id": catalogue["users"][lesson.teacher]["id"],
                "room_id": rooms[lesson.room]["id"],
                "kind": lesson.kind,
                "title": "",
                "interval": 1,
                "until": year["settings"]["end"],
                "target_kind": lesson.target_kind,
                "target_number": german["id"]
                if lesson.target_kind == "custom"
                else lesson.target_number,
                "target_user_id": None,
            }
        )
    return result


def seed_timetables(
    client: Client,
    settings: Settings,
    catalogue: dict,
    groups: dict,
    plan: list[Lesson],
) -> list[int]:
    """Create configured annual agendas and append only missing compatible weekly series."""
    config = client.request("GET", "/timetable/configuration")
    if not any(year["school_year"] == settings.school_year for year in config["years"]):
        client.request("POST", "/timetable/school-years", {"school_year": settings.school_year})
    rooms = {room["name"]: room for room in config["rooms"]}
    for name in settings.rooms:
        if name not in rooms:
            rooms[name] = client.request("POST", "/timetable/rooms", {"name": name})
    catalog = client.request("GET", "/timetable/catalog")
    created = []
    for index, cohort in enumerate(settings.classes()):
        promotion = catalogue["promotions"][cohort.identifier]["id"]
        existing = next(
            (item for item in catalog["calendars"] if item["name"] == cohort.calendar_name),
            None,
        )
        if existing and (existing["promotion_id"] != promotion or existing.get("is_archived")):
            raise SeedError(
                "Un nom d’agenda est déjà utilisé par une autre affectation ; "
                "aucun changement effectué."
            )
        if existing is None:
            if any(item["promotion_id"] == promotion for item in catalog["calendars"]):
                raise SeedError("Cette promotion possède déjà un autre agenda actif.")
            existing = client.request(
                "POST",
                "/timetable/calendars",
                {
                    "name": cohort.calendar_name,
                    "promotion_id": promotion,
                    "is_paused": True,
                    "school_year": settings.school_year,
                    "settings": settings.calendar_settings(),
                },
            )
        identifier = existing["id"]
        board = client.request("GET", f"/timetable/board?calendar_ids={identifier}")
        year = board["years"][0]
        if (
            year["school_year"] != settings.school_year
            or year["settings"] != settings.calendar_settings()
        ):
            raise SeedError(
                "Les réglages de l’agenda existant diffèrent du scénario ; aucun réglage remplacé."
            )
        proposed = blocks_for_year(
            [item for item in plan if item.calendar_index == index],
            year,
            catalogue,
            rooms,
            groups[cohort.identifier],
        )
        expected = {fingerprint(block) for block in proposed}
        present = {fingerprint(series) for series in year["series"]}
        if (
            len(present) != len(year["series"])
            or not present <= expected
            or any(
                series["exceptions"] or series.get("start_time") is not None
                for series in year["series"]
            )
        ):
            raise SeedError(
                "L’agenda contient des séances modifiées ou étrangères au scénario. "
                "Utilisez un autre namespace."
            )
        revision = year["revision"]
        for block in proposed:
            if fingerprint(block) in present:
                continue
            changed = client.request(
                "POST",
                f"/timetable/years/{year['id']}/series",
                {
                    "expected_revision": revision,
                    "confirmed_live": True,
                    "block": block,
                },
            )
            revision = changed["revision"]
        final = client.request("GET", f"/timetable/board?calendar_ids={identifier}")
        if final["issues"]:
            raise SeedError(
                "Le calendrier généré présente des alertes ; consultez les points à vérifier."
            )
        if final.get("teacher_commitments"):
            check_external_commitments(final)
        agenda = final["calendars"][0]
        if settings.broadcast and agenda["is_paused"]:
            client.request(
                "PUT",
                f"/timetable/calendars/{identifier}",
                {
                    "name": cohort.calendar_name,
                    "promotion_id": promotion,
                    "is_paused": False,
                    "expected_revision": agenda["revision"],
                    "confirmed_live": True,
                },
            )
        created.append(identifier)
        print(
            f"{cohort.calendar_name} : {len(proposed)} récurrences, "
            f"{len(final['events'])} occurrences réelles."
        )
    return created


def check_external_commitments(board: dict) -> None:
    """Refuse actual cross-calendar teacher overlaps, ignoring merely unrelated bookings."""
    bookings = {}
    for booking in board["teacher_commitments"]:
        bookings.setdefault((booking["teacher_id"], booking["start"][:10]), []).append(booking)
    for event in board["events"]:
        for booking in bookings.get((event["teacher_id"], event["start"][:10]), []):
            if event["start"] < booking["end"] and booking["start"] < event["end"]:
                raise SeedError(
                    "Un professeur possède déjà un cours sur un autre agenda à cet horaire."
                )
