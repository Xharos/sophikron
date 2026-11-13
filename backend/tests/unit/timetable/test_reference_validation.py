"""Server-side reference validation independent of calendar UI restrictions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models import Promotion, Subject, User
from app.models.timetable import TimetableRoom
from app.schemas.timetable import SessionFields
from app.services.errors import AuthError
from app.services.timetable import TimetableService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("valid", None),
        ("subject_missing", 422),
        ("subject_archived", 422),
        ("room_missing", 422),
        ("room_archived", 422),
        ("teacher_missing", 422),
        ("teacher_disabled", 422),
        ("teacher_bootstrap", 422),
        ("teacher_no_role", 422),
        ("kholleur_course", 422),
        ("kholleur_kholle", None),
        ("promotion_missing", 409),
        ("promotion_archived", 409),
        ("historical", None),
        ("unavailable_override", None),
    ],
)
async def test_live_reference_matrix(scenario: str, expected: int | None) -> None:
    """Reject unavailable subjects, rooms and teaching identities on the server."""
    subject = SimpleNamespace(is_active=scenario not in {"subject_archived", "historical"})
    room = SimpleNamespace(is_active=scenario != "room_archived")
    teacher = SimpleNamespace(
        is_bootstrap=scenario == "teacher_bootstrap",
        status="disabled"
        if scenario in {"teacher_disabled", "historical", "unavailable_override"}
        else "active",
    )
    promotion = SimpleNamespace(is_active=scenario != "promotion_archived")
    objects = {Subject: subject, TimetableRoom: room, User: teacher, Promotion: promotion}
    missing = {
        "subject_missing": Subject,
        "room_missing": TimetableRoom,
        "teacher_missing": User,
        "promotion_missing": Promotion,
    }
    if scenario in missing:
        objects[missing[scenario]] = None

    async def get(model: type, _identifier: int) -> object:
        """Return a typed reference double selected by the real service query."""
        return objects[model]

    roles = (
        set()
        if scenario == "teacher_no_role"
        else ({"kholleur"} if scenario.startswith("kholleur") else {"teacher"})
    )
    service = object.__new__(TimetableService)
    service.db = SimpleNamespace(get=AsyncMock(side_effect=get))
    service.auth = SimpleNamespace(repo=SimpleNamespace(roles=AsyncMock(return_value=roles)))
    block = SessionFields(
        subject_id=1,
        room_id=2,
        teacher_id=3,
        kind="kholle" if scenario == "kholleur_kholle" else "course",
    )
    arguments = {
        "historical": scenario == "historical",
        "allow_unavailable_teacher": scenario == "unavailable_override",
    }
    if expected is None:
        assert (
            await service._references(block, SimpleNamespace(promotion_id=4), **arguments) is None
        )
    else:
        with pytest.raises(AuthError) as error:
            await service._references(block, SimpleNamespace(promotion_id=4), **arguments)
        assert error.value.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["student", "custom", "kholles"])
@pytest.mark.parametrize("member", [False, True])
async def test_audience_requires_current_membership(target: str, member: bool) -> None:
    """Named recipients and groups must still belong to the calendar's current promotion."""
    service = object.__new__(TimetableService)
    service.db = SimpleNamespace(
        get=AsyncMock(side_effect=[SimpleNamespace(is_active=True), member]),
        scalar=AsyncMock(return_value=1 if member else None),
    )
    service.auth = SimpleNamespace(repo=SimpleNamespace(roles=AsyncMock()))
    block = SessionFields(
        title="Study",
        target_kind=target,
        target_number=1 if target != "student" else None,
        target_user_id=1 if target == "student" else None,
    )
    if member:
        assert await service._references(block, SimpleNamespace(promotion_id=4)) is None
    else:
        with pytest.raises(AuthError) as error:
            await service._references(block, SimpleNamespace(promotion_id=4))
        assert error.value.status == 422
