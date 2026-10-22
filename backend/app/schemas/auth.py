"""Strict public authentication contracts with no credential verifiers in responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.core.security import normalize_email, normalize_username


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
    """Normalize the username and email supplied for a permanent account."""

    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=3, max_length=254)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Normalize the public username before encryption and uniqueness checks."""
        return normalize_username(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Normalize the email without making network-dependent DNS checks."""
        return normalize_email(value)


class CreateUserRequest(UserIdentityRequest):
    """Let administrators explicitly assign existing roles to an unactivated account."""

    roles: list[str] = Field(min_length=1, max_length=20)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[str]) -> list[str]:
        """Reject duplicate and oversized role codes before querying the catalogue."""
        if len(set(value)) != len(value) or any(not 1 <= len(role) <= 64 for role in value):
            raise ValueError("Invalid roles")
        return value


class CompleteSetupRequest(UserIdentityRequest):
    """Create the permanent administrator with a strong password and no caller-selected roles."""

    password: SecretStr = Field(min_length=10, max_length=128)


class UserResponse(BaseModel):
    """Return identity only to the account itself or an authorized administrator."""

    id: UUID
    username: str
    email: str | None
    status: str
    roles: tuple[str, ...]
    email_verified: bool
    is_bootstrap: bool
    created_at: datetime
