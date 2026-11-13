"""Searchable, attributed annual PDF pages and private export guards."""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pypdf import PdfReader

from app.services.errors import AuthError
from app.services.kholloscope_generation import KholloscopeGenerationService
from app.services.kholloscope_pdf import group_palette, render_kholloscope_pdf


def test_two_promotions_export_eight_subject_pages_and_two_rosters() -> None:
    """Export every assigned group with accents, rooms, attribution and dated page headings."""
    calendars = [
        {
            "id": c,
            "name": f"Promotion {c} 2026/2027",
            "weeks": [{"start": "2026-09-07"}, {"start": "2026-09-14"}],
            "groups": [
                {"number": c, "students": [{"last_name": f"Élève {c}", "first_name": "Zêta"}]}
            ],
        }
        for c in (1, 2)
    ]
    catalog = {
        "subjects": [{"id": s, "name": f"Matière {s}", "color": "#244BC1"} for s in range(1, 5)],
        "teachers": [{"id": 7, "name": "Échantillon Temoin"}],
        "rooms": [{"id": 8, "name": "B208"}],
    }
    sessions = [
        {
            "calendar_id": c,
            "subject_id": s,
            "teacher_id": 7,
            "room_id": 8,
            "day": "2026-09-07",
            "original_day": "2026-09-08",
            "start": 43200,
            "group": c,
        }
        for c in (1, 2)
        for s in range(1, 5)
    ]
    pdf = render_kholloscope_pdf(
        calendars,
        sessions,
        catalog,
        "Compte Échantillon",
        datetime(2026, 11, 5, 13, 45, tzinfo=timezone.utc),
    )
    reader = PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 10
    assert reader.metadata.author == "Compte Échantillon"
    for page in reader.pages:
        assert page.mediabox.width > page.mediabox.height
        text = page.extract_text()
        assert all(
            value in text
            for value in (
                "Compte Échantillon",
                "05/11/2026",
                "14:45",
            )
        )
        if "COMPOSITION DES GROUPES" in text:
            assert "ÉLÈVE" in text and "Zêta" in text and "Groupe" in text
        else:
            assert all(v in text for v in ("Échantillon Temoin", "B208", "07/09", "Matière", "*"))
            assert "Zêta" not in text
    assert "10 / 10" in reader.pages[-1].extract_text()
    # A painted group rectangle reaches the full table cell bounds, not an inset badge.
    subject = reader.pages[1]
    width, height = float(subject.mediabox.width), float(subject.mediabox.height)
    rectangles = [
        list(map(float, operands))
        for operands, operator in subject.get_contents().operations
        if operator == b"re"
    ]
    assert any(
        rect == pytest.approx([267, height - 202, (width - 299) / 2, 42], abs=0.001)
        for rect in rectangles
    )
    color = group_palette([1])[1]
    expected = [color.red, color.green, color.blue]
    for page in (reader.pages[0], subject):
        assert any(
            list(map(float, operands)) == pytest.approx(expected, abs=0.00001)
            for operands, operator in page.get_contents().operations
            if operator == b"rg"
        )


def test_group_palette_is_unique_beyond_six_groups_and_restarts_per_promotion() -> None:
    """All ten demo groups get distinct colors, including the former repeated 1/7 pair."""
    palette = group_palette(list(range(1, 11)))
    assert len({color.hexval() for color in palette.values()}) == 10
    assert palette == group_palette(list(range(10, 0, -1)))


def test_ten_group_roster_keeps_all_names_clear_of_the_footer() -> None:
    """Keep a full promotion's fifty pupil names visible above the attribution area."""
    roster = [
        {
            "number": g,
            "students": [{"last_name": f"Nom{g:02d}{p}", "first_name": "Prénom"} for p in range(5)],
        }
        for g in range(1, 11)
    ]
    pdf = render_kholloscope_pdf(
        [{"id": 1, "name": "PT", "groups": roster, "weeks": []}],
        [],
        {"subjects": [], "teachers": [], "rooms": []},
        "Compte Test",
        datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    page = PdfReader(BytesIO(pdf)).pages[0]
    content = page.extract_text()
    assert all(f"NOM{g:02d}{p} Prénom" in content for g in range(1, 11) for p in range(5))
    assert "Compte Test" in content
    assert (
        min(
            float(operands[1])
            for operands, operator in page.get_contents().operations
            if operator == b"re"
        )
        >= 55
    )


@pytest.mark.asyncio
async def test_pdf_cannot_read_a_foreign_or_unassigned_draft() -> None:
    """Authorization and saved assignment are required before loading export metadata."""
    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    service.catalog = AsyncMock()
    service.group_choices = AsyncMock(side_effect=AuthError(403, "Refus"))
    with pytest.raises(AuthError) as failure:
        await service.pdf(SimpleNamespace(id=1), 2026)
    assert failure.value.status == 403
    service.catalog.assert_not_awaited()
    service.group_choices = AsyncMock(return_value={"assigned_sessions": []})
    with pytest.raises(AuthError) as failure:
        await service.pdf(SimpleNamespace(id=1), 2026)
    assert failure.value.status == 409
    service.catalog.assert_not_awaited()
    service.group_choices = AsyncMock(return_value={"assigned_sessions": [{"group": 1}]})
    service.db = Mock()
    service.db.begin.return_value = AsyncMock()
    service.auth = SimpleNamespace(repo=SimpleNamespace(permissions=AsyncMock(return_value=[])))
    with pytest.raises(AuthError) as failure:
        await service.pdf(SimpleNamespace(id=1), 2026)
    assert failure.value.status == 403
    service.catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_export_reads_pupil_names_in_separate_explicit_transactions() -> None:
    """Export matching rosters without leaving an implicit permission transaction open."""
    active = False

    @asynccontextmanager
    async def transaction():
        """Reject nested transactions as a real SQLAlchemy session would."""
        nonlocal active
        assert not active
        active = True
        try:
            yield
        finally:
            active = False

    async def permissions(_user_id: int) -> tuple[str, ...]:
        """Require explicit ownership of the permission query transaction."""
        assert active
        return ("users.read",)

    async def catalog(_actor: object) -> dict:
        """Reproduce the catalog service's separate transaction boundary."""
        async with transaction():
            return {
                "subjects": [{"id": 1, "name": "Mathématiques"}],
                "teachers": [{"id": 2, "name": "Mme Test"}],
                "rooms": [{"id": 3, "name": "B208"}],
            }

    calendar = {"id": 1, "name": "PT", "weeks": [{"start": "2026-09-07"}]}
    pupil = SimpleNamespace(id=4, last_name_encrypted=b"last", first_name_encrypted=b"first")
    service = KholloscopeGenerationService.__new__(KholloscopeGenerationService)
    service.db = SimpleNamespace(
        begin=transaction,
        execute=AsyncMock(return_value=[(1, pupil)]),
        get=AsyncMock(return_value=SimpleNamespace(id=9)),
    )
    service.auth = SimpleNamespace(
        repo=SimpleNamespace(permissions=permissions),
        cipher=SimpleNamespace(
            decrypt=Mock(
                side_effect=lambda _uid, field, _data: {"last_name": "Élève", "first_name": "Zêta"}[
                    field
                ]
            )
        ),
    )
    service.authorize = AsyncMock()
    service._calendar = AsyncMock(return_value=SimpleNamespace(promotion_id=1))
    service._identity = Mock(return_value={"name": "Compte Test"})
    service.latest = AsyncMock(
        return_value=SimpleNamespace(revision="r1", snapshot={"calendars": [calendar]})
    )
    service.catalog = catalog
    service.today = Mock(return_value=date(2026, 9, 7))
    service.group_choices = AsyncMock(
        return_value={
            "revision": "r1",
            "calendars": [{"id": 1, "groups": [1]}],
            "assigned_sessions": [
                {
                    "calendar_id": 1,
                    "subject_id": 1,
                    "teacher_id": 2,
                    "room_id": 3,
                    "day": "2026-09-07",
                    "start": 43200,
                    "group": 1,
                }
            ],
        }
    )
    service.latest.return_value.result = {
        "assigned_sessions": service.group_choices.return_value["assigned_sessions"]
    }
    exported = await service.pdf(SimpleNamespace(id=9), 2026)
    pages = PdfReader(BytesIO(exported)).pages
    assert len(pages) == 2
    assert "ÉLÈVE Zêta" in pages[0].extract_text()
    assert "Compte Test" in pages[0].extract_text()
    assert "Mathématiques" in pages[1].extract_text()
    assert not active
