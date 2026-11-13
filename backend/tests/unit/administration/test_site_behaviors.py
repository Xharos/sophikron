"""Public configuration and subject mutation behavior, including authorization failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas.site import SettingsUpdate, SubjectUpdate
from app.services.errors import AuthError
from app.services.site import SiteService


@pytest.fixture
def site_service() -> SiteService:
    """Provide a transactional session double without replacing the service under test."""
    db = MagicMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    auth = SimpleNamespace(db=db, _actor=AsyncMock(), _lifecycle_lock=AsyncMock())
    service = SiteService(auth)
    service._event = AsyncMock()
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True])
async def test_public_settings_whitelist(site_service: SiteService, exists: bool) -> None:
    """Publish presentation fields only, with defaults when no row exists."""
    site_service.db.get.return_value = (
        SimpleNamespace(
            name="School", home_text="Welcome", text_color="#244BC1", version=2, secret="private"
        )
        if exists
        else None
    )
    result = await site_service.public()
    assert result.settings.name == ("School" if exists else "Sophikron")
    assert "secret" not in result.model_dump()["settings"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["changed", "unchanged", "stale", "denied"])
async def test_site_settings_revision_and_audit(site_service: SiteService, scenario: str) -> None:
    """Reject stale or unauthorized writes and journal only actual changes without text bodies."""
    row = SimpleNamespace(name="School", home_text="Welcome", text_color="#244BC1", version=2)
    site_service.db.get.return_value = row
    actor = SimpleNamespace(id=1)
    if scenario == "denied":
        site_service.auth._actor.side_effect = AuthError(403, "Forbidden")
    data = SettingsUpdate(
        name="New school" if scenario == "changed" else "School",
        home_text="Welcome",
        expected_version=1 if scenario == "stale" else 2,
    )
    if scenario in {"stale", "denied"}:
        with pytest.raises(AuthError) as error:
            await site_service.settings_save(actor, data)
        assert error.value.status == (409 if scenario == "stale" else 403)
        assert row.version == 2 and row.name == "School"
        site_service._event.assert_not_awaited()
    else:
        result = await site_service.settings_save(actor, data)
        assert result.version == (3 if scenario == "changed" else 2)
        if scenario == "changed":
            facts = site_service._event.call_args.args[-1]
            assert facts == {
                "changed_fields": ["name"],
                "previous_name": "School",
                "name": "New school",
            }
        else:
            site_service._event.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "stale", "archived", "valid"])
async def test_subject_edit_revisions(site_service: SiteService, state: str) -> None:
    """A successful edit changes the canonical key and invalidates dependent course revisions."""
    row = SimpleNamespace(
        id=3,
        name="Maths",
        name_key="maths",
        color="#244BC1",
        icon="book",
        is_active=state != "archived",
        version=2,
    )
    site_service.db.get.return_value = None if state == "missing" else row
    data = SubjectUpdate(name="Physics", expected_version=1 if state == "stale" else 2)
    if state != "valid":
        with pytest.raises(AuthError) as error:
            await site_service.subject_save(SimpleNamespace(id=1), data, 3)
        assert error.value.status == (404 if state == "missing" else 409)
        site_service.db.execute.assert_not_awaited()
        site_service._event.assert_not_awaited()
    else:
        result = await site_service.subject_save(SimpleNamespace(id=1), data, 3)
        assert result.name == "Physics" and result.version == 3 and row.name_key == "physics"
        site_service.db.execute.assert_awaited_once()
        site_service.db.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "stale", "used", "unused"])
async def test_subject_archival_protects_courses(site_service: SiteService, state: str) -> None:
    """Used subjects cannot be archived and unused subjects lose their teaching assignments."""
    row = SimpleNamespace(
        id=3, name="Maths", color="#244BC1", icon="book", is_active=True, version=2
    )
    site_service.db.get.return_value = None if state == "missing" else row
    site_service.db.scalar.return_value = 9 if state == "used" else None
    site_service.db.scalars.return_value = []
    if state != "unused":
        with pytest.raises(AuthError) as error:
            await site_service.subject_archive(
                SimpleNamespace(id=1), 3, 1 if state == "stale" else 2
            )
        assert error.value.status == (404 if state == "missing" else 409)
        site_service.db.execute.assert_not_awaited()
    else:
        await site_service.subject_archive(SimpleNamespace(id=1), 3, 2)
        assert not row.is_active and row.version == 3
        assert site_service.db.execute.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mine", [False, True])
async def test_subject_catalogue_scope_and_counts(site_service: SiteService, mine: bool) -> None:
    """Teacher catalogues request their own grant and do not expose administrator counts."""
    row = SimpleNamespace(
        id=3, name="Maths", icon="book", color="#244BC1", is_active=True, version=2
    )
    rows = MagicMock()
    rows.all.return_value = [row]
    site_service.db.scalars.return_value = rows
    site_service.db.scalar.side_effect = [1] if mine else [1, 4, 6]
    actor = SimpleNamespace(id=7)
    result = await site_service.subjects(actor, mine=mine, q=" %_\\ ", is_active=None)
    item = result["items"][0]
    assert result["total"] == 1
    assert (item.teacher_count, item.lesson_count) == ((0, 0) if mine else (4, 6))
    site_service.auth._actor.assert_awaited_once_with(
        actor, permission="teacher.access" if mine else "users.manage"
    )
