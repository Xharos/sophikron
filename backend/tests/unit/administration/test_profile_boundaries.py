"""Profile privacy, patch authorization and atomic revision checks."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.profile import AdminProfileUpdate, OrientationUpdate, SchoolProfile
from app.services.errors import AuthError
from app.services.profiles import ProfileService


@pytest.fixture
def profile_service() -> ProfileService:
    """Keep the real service and isolate database, identity and presentation boundaries."""
    db = MagicMock()
    db.scalars = AsyncMock(return_value=[])
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    repo = SimpleNamespace(
        permissions=AsyncMock(return_value={"profiles.manage"}),
        user=AsyncMock(),
        roles=AsyncMock(return_value={"user"}),
    )
    auth = SimpleNamespace(db=db, repo=repo, _actor=AsyncMock(), _lifecycle_lock=AsyncMock())
    service = ProfileService(auth)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("first_name", "Alpha"),
        ("last_name", "Specimen"),
        ("email", "new@example.org"),
        ("orientation_project", "Engineering"),
        ("previous_school", "School"),
        ("phone", "+33612345678"),
        ("birth_date", "2005-01-02"),
    ],
)
async def test_private_field_write_is_encrypted_and_audited(
    profile_service: ProfileService,
    field: str,
    value: str,
) -> None:
    """Encrypt changes, increment revisions and keep private values out of audit data."""
    service = profile_service
    user = SimpleNamespace(
        id=2,
        profile_version=2,
        status="active",
        first_name_encrypted=b"old",
        last_name_encrypted=b"old",
        email_encrypted=b"old",
    )
    service.target = AsyncMock(return_value=user)
    service.auth.repo.user.return_value = user
    service.auth.repo.revoke_invitations = AsyncMock()
    service.auth.clock = MagicMock(return_value=datetime(2026, 11, 10, tzinfo=UTC))
    service.auth.cipher = SimpleNamespace(
        decrypt=MagicMock(return_value="Old"),
        encrypt=MagicMock(return_value=b"encrypted"),
        lookup=MagicMock(return_value=b"lookup"),
    )
    service.decode = MagicMock(return_value=SchoolProfile())
    service.present = AsyncMock(return_value="saved")
    with patch("app.services.profiles.record_event", new_callable=AsyncMock) as event:
        result = await service.update(
            SimpleNamespace(id=1), 2, AdminProfileUpdate(expected_version=2, **{field: value})
        )
    assert result == "saved" and user.profile_version == 3
    assert getattr(user, field + "_encrypted") == b"encrypted"
    assert event.call_args.kwargs["data"] == {"changed_fields": [field]}
    if field == "email":
        assert user.email_verified_at is None and user.email_lookup == b"lookup"
        service.auth.repo.revoke_invitations.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("owner,manager", [(True, False), (False, True), (False, False)])
async def test_profile_target_uses_current_scope(
    profile_service: ProfileService,
    owner: bool,
    manager: bool,
) -> None:
    """Restrict reads to the owner or the caller's current authorized scope."""
    actor = SimpleNamespace(id=1)
    user = SimpleNamespace(id=1 if owner else 2, is_bootstrap=False)
    profile_service.auth.repo.permissions.return_value = {"profiles.manage"} if manager else set()
    profile_service.auth.repo.user.return_value = user
    profile_service.db.scalar = AsyncMock(return_value=user)
    assert await profile_service.target(actor, 2, owner=owner) is user
    if owner or manager:
        profile_service.auth.repo.user.assert_awaited_once_with(1 if owner else 2)
    else:
        profile_service.auth.repo.user.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, SimpleNamespace(is_bootstrap=True)])
async def test_unavailable_profile_is_hidden(profile_service: ProfileService, user: object) -> None:
    """Missing and bootstrap profiles return the same public error."""
    profile_service.auth.repo.user.return_value = user
    with pytest.raises(AuthError) as error:
        await profile_service.target(SimpleNamespace(id=1), 2)
    assert error.value.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["denied_admin", "denied_orientation", "stale", "unchanged", "orientation"]
)
async def test_profile_patch_checks_before_writes(
    profile_service: ProfileService, scenario: str
) -> None:
    """Refuse unauthorized or stale changes and leave unchanged patches without audit writes."""
    actor = SimpleNamespace(id=1)
    user = SimpleNamespace(id=2, profile_version=2, status="active")
    profile_service.target = AsyncMock(return_value=user)
    profile_service.auth.repo.user.return_value = user
    profile_service.auth.repo.permissions.return_value = (
        set() if scenario.startswith("denied") else {"profiles.manage", "orientation.manage"}
    )
    profile_service.decode = MagicMock(return_value=SchoolProfile())
    profile_service.present = AsyncMock(return_value="presented")
    orientation = scenario in {"denied_orientation", "orientation"}
    data = (
        OrientationUpdate(expected_version=2, orientation_project=None)
        if orientation
        else AdminProfileUpdate(expected_version=1 if scenario == "stale" else 2)
    )
    with patch("app.services.profiles.record_event", new_callable=AsyncMock) as event:
        if scenario.startswith("denied") or scenario == "stale":
            with pytest.raises(AuthError) as error:
                await profile_service.update(actor, 2, data)
            assert error.value.status == (409 if scenario == "stale" else 403)
            profile_service.db.flush.assert_not_awaited()
            profile_service.present.assert_not_awaited()
        else:
            assert await profile_service.update(actor, 2, data) == "presented"
            assert user.profile_version == 2
        event.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "values",
    [
        {"city": "Paris"},
        {"city": "Paris", "postal_code": None, "commune_code": "75056"},
    ],
)
async def test_location_patch_is_coherent_before_transaction(
    profile_service: ProfileService,
    values: dict,
) -> None:
    """Reject incomplete location updates without modifying profile data."""
    data = AdminProfileUpdate(expected_version=2, **values)
    with pytest.raises(AuthError) as error:
        await profile_service.update(SimpleNamespace(id=1), 2, data)
    assert error.value.status == 422
    profile_service.auth._lifecycle_lock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["unchanged", "self_demotion", "unknown_role"])
async def test_role_replacement_preserves_grants_on_rejection(
    profile_service: ProfileService,
    scenario: str,
) -> None:
    """Avoid writes for identical grants and reject self-demotion or unknown roles."""
    profile_service.auth.repo.roles.return_value = {"admin"}
    profile_service.auth.repo.role_records = AsyncMock(return_value=[])
    actor = SimpleNamespace(id=1)
    target = SimpleNamespace(id=2 if scenario == "unknown_role" else 1)
    if scenario == "unchanged":
        assert not await profile_service.replace_roles(actor, target, ["admin"])
    else:
        with pytest.raises(AuthError) as error:
            await profile_service.replace_roles(actor, target, ["teacher"])
        assert error.value.status == (409 if scenario == "self_demotion" else 422)
    profile_service.db.execute.assert_not_awaited()
