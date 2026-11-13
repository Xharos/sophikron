"""Shared synthetic scenario fixtures."""

from icalendar import Calendar

from tests.support.authentication import PASSWORD, Harness
from tests.support.timetable import Workspace, workspace  # noqa: F401


async def login(case: Harness, name: str) -> None:
    """Switch to a real account without bypassing session authentication."""
    case.client.cookies.clear()
    response = await case.client.post(
        "/api/v1/auth/login", json={"identifier": name, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


async def personal(case: Harness) -> dict:
    """Read only the current owner's credential via its authenticated endpoint."""
    response = await case.client.get("/api/v1/timetable/subscription")
    assert response.status_code == 200, response.text
    return response.json()


async def feed(case: Harness, token: str) -> list:
    """Parse the public ICS route, requiring successful private, nonindexed responses."""
    response = await case.client.get(f"/api/v1/timetable/feed/{token}.ics")
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    assert "noindex" in response.headers["x-robots-tag"]
    return Calendar.from_ical(response.content).walk("VEVENT")
