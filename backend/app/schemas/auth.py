"""Strict public authentication contracts with no credential verifiers in responses."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.identity import normalize_name
from app.core.security import normalize_email


def validate_roles(value: list[str]) -> list[str]:
    """Require one supported role combination for account creation and later changes.

    Parameters
    ----------
    value
        Explicit role codes supplied by the administrator.

    Returns
    -------
    list[str]
        The validated codes, preserving the supplied order.
    """
    if len(set(value)) != len(value):
        raise ValueError("Duplicate roles")
    codes = set(value)
    if not codes or not codes <= {"user", "kholleur", "teacher", "admin"}:
        raise ValueError("Unknown or missing roles")
    if "user" in codes and len(codes) > 1:
        raise ValueError("Incompatible roles")
    return value


RoleCodes = Annotated[list[str], Field(min_length=1, max_length=3), AfterValidator(validate_roles)]


class InputModel(BaseModel):
    """Reject unexpected fields and avoid including inputs in validation diagnostics."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LoginRequest(InputModel):
    """Supply either a username or an email without exposing credential fields in repr."""

    identifier: str = Field(min_length=1, max_length=254, repr=False)
    password: SecretStr = Field(min_length=0, max_length=128)


class ActivateRequest(InputModel):
    """Supply a single-use invitation secret and the first password."""

    token: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=10, max_length=128)


class ChangePasswordRequest(InputModel):
    """Require proof of the current password before replacing it."""

    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=10, max_length=128)


class UserIdentityRequest(InputModel):
    """Validate identity fields; permanent usernames are generated exclusively by the server."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Keep French spelling while rejecting empty and unsupported names."""
        return normalize_name(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize the email without making network-dependent DNS checks."""
        return normalize_email(value)


class CreateUserRequest(UserIdentityRequest):
    """Let administrators explicitly assign existing roles to an unactivated account."""

    roles: RoleCodes = Field(default_factory=lambda: ["user"])
    promotion_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("promotion_ids")
    @classmethod
    def validate_promotions(cls, value: list[int]) -> list[int]:
        """Reject nonpositive and duplicate promotion identifiers."""
        if any(item <= 0 for item in value) or len(set(value)) != len(value):
            raise ValueError("Invalid promotions")
        return value


class CompleteSetupRequest(UserIdentityRequest):
    """Create the permanent administrator with a strong password and no caller-selected roles."""

    password: SecretStr = Field(min_length=10, max_length=128)


class UserResponse(BaseModel):
    """Return identity only to the account itself or an authorized administrator."""

    id: int
    username: str
    first_name: str | None
    last_name: str | None
    email: str | None
    status: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    email_verified: bool
    is_bootstrap: bool
    created_at: datetime


class AccountResponse(UserResponse):
    """Expose account activity only to the authenticated account itself."""

    updated_at: datetime
    last_login_at: datetime | None
    password_changed_at: datetime | None
    email_verified_at: datetime | None
    login_count: int


class ManualInvitationResponse(BaseModel):
    """Expose a new invitation only to the issuing permanent administrator."""

    token: str = Field(repr=False)
    expires_at: datetime


class AccessInvitationResponse(BaseModel):
    """Expose a token only when the server selected manual delivery without SMTP."""

    delivery: str
    purpose: str
    expires_at: datetime
    token: str | None = Field(default=None, repr=False)
