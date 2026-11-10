"""Explicit role checks, detached identity and disabled delivery contracts."""

from types import SimpleNamespace

import pytest

from app.core.security_policy import validate_password
from app.dependencies.auth import RequirePermission, RequireRole
from app.services.auth import UserContext
from app.services.errors import AuthError
from app.services.mail import DisabledMailer, MailDeliveryError


@pytest.mark.parametrize("permission", ["", "statistics.read"])
def test_permission_policy_rejects_empty_configuration(permission: str) -> None:
    """Require an explicit capability instead of accidentally permitting an empty policy."""
    if not permission:
        with pytest.raises(ValueError, match="required"):
            RequirePermission(permission)
    else:
        assert RequirePermission(permission).permission == permission


@pytest.mark.parametrize("password", ["Aa1!short", "a" * 129, "ABCDEFGHI1!", "Abcdefgh1é!"])
def test_password_policy_rejects_invalid_categories(password: str) -> None:
    """Invalid lengths, alphabets and missing categories are refused."""
    with pytest.raises(ValueError):
        validate_password(password)


def test_password_policy_accepts_complete_ascii_password() -> None:
    """A bounded password with every required category is accepted."""
    assert validate_password("Abcdefghi1!") is None


@pytest.mark.asyncio
async def test_role_policy_returns_principal_or_denies() -> None:
    """A role check accepts an explicit match and denies unrelated roles."""
    actor = UserContext(SimpleNamespace(roles=("teacher",)), session_id=1)
    assert actor.roles == ("teacher",)
    assert await RequireRole("teacher")(actor) is actor
    with pytest.raises(AuthError):
        await RequireRole("admin")(actor)


@pytest.mark.asyncio
async def test_disabled_delivery_fails_without_exposing_credentials() -> None:
    """Disabled SMTP must fail explicitly rather than discard an invitation silently."""
    mailer = DisabledMailer()
    assert mailer.available is False
    with pytest.raises(MailDeliveryError) as error:
        await mailer.send_invitation("synthetic@example.org", "synthetic-secret")
    assert "synthetic" not in str(error.value)
