"""Shared assignment operations without duplicating pupil sessions or occurrence identities."""


def assigned_teachers(event: dict) -> list[int]:
    """Return canonical teacher IDs, accepting legacy single-teacher dictionaries."""
    return event.get("teacher_ids", [event["teacher_id"]] if event.get("teacher_id") else [])


def individual_assignments(events: list[dict]) -> list[dict]:
    """Expand only teacher checks, giving each assignment its own label and availability."""
    return [
        {
            **event,
            "teacher_id": identifier,
            "teacher": next(
                (item["name"] for item in event.get("teachers", []) if item["id"] == identifier),
                event.get("teacher", ""),
            ),
            "teacher_available": next(
                (
                    item["available"]
                    for item in event.get("teachers", [])
                    if item["id"] == identifier
                ),
                event.get("teacher_available", True),
            ),
        }
        for event in events
        for identifier in assigned_teachers(event)
    ]
