"""Project published revision metadata at the school's current civil date."""

from copy import deepcopy
from datetime import date

VERSION_FIELDS = (
    "revision_wishes",
    "revision_rooms",
    "revision_group_mappings",
    "revision_entitlement",
    "assigned_sessions",
)


def version_metadata(result: dict) -> dict:
    """Return only reversible published metadata, without logs or nested version history."""
    return {key: deepcopy(result[key]) for key in VERSION_FIELDS if key in result}


def effective_sessions(result: dict, today: date) -> list[dict]:
    """Return the annual schedule with only revisions already effective in Paris applied."""
    sessions = result.get("assigned_sessions", [])
    for version in reversed(result.get("revision_versions", [])):
        if version["effective_on"] <= today.isoformat():
            break
        sessions = version["before"].get("assigned_sessions", sessions)
    return deepcopy(sessions)


def effective_metadata(result: dict, today: date) -> dict:
    """Resolve current service and rooms while keeping the dated annual schedule intact."""
    projected = deepcopy(result)
    resolved: set[str] = set()
    for version in reversed(result.get("revision_versions", [])):
        fields = set(version.get("fields", VERSION_FIELDS)) - {"assigned_sessions"}
        if version["effective_on"] > today.isoformat():
            for key in fields - resolved:
                projected.pop(key, None)
                if key in version["before"]:
                    projected[key] = deepcopy(version["before"][key])
        elif version.get("return_on") and version["return_on"] <= today.isoformat():
            # Temporary service/room changes end without undoing permanent group changes.
            for key in {"revision_wishes", "revision_rooms"} - resolved:
                if key in version["before"]:
                    projected[key] = deepcopy(version["before"][key])
                else:
                    projected.pop(key, None)
            resolved.update(fields - {"revision_wishes", "revision_rooms"})
        else:
            resolved.update(fields)
    return projected
