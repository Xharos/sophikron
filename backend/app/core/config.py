"""Validated PostgreSQL configuration and runtime secret loading."""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    """Read DB_* variables; accept passwords only through a runtime secret file."""

    model_config = SettingsConfigDict(
        env_prefix="DB_", env_file=None, frozen=True, hide_input_in_errors=True, extra="ignore"
    )

    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = Field(min_length=1)
    user: str = Field(min_length=1)
    password_file: Path = Field(repr=False, exclude=True)
    pool_size: int = Field(default=5, ge=1, le=100)
    max_overflow: int = Field(default=5, ge=0, le=100)
    pool_timeout: float = Field(default=5, gt=0, allow_inf_nan=False)
    pool_recycle: int = Field(default=1800, ge=1)
    connect_timeout: int = Field(default=5, ge=2)
    statement_timeout_ms: int = Field(default=10000, ge=1)
    lock_timeout_ms: int = Field(default=2000, ge=1)
    idle_transaction_timeout_ms: int = Field(default=30000, ge=1)
    health_timeout: float = Field(default=2, gt=0, allow_inf_nan=False)
    sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "disable"
    )
    sslrootcert: Path | None = None
    target_session_attrs: Literal["any", "read-write", "primary"] = "read-write"
    _password: SecretStr = PrivateAttr()

    @model_validator(mode="after")
    def load_password(self) -> Self:
        """Load a UTF-8 secret without exposing its contents in validation errors.

        Returns
        -------
        Self
            Validated settings containing a private, redacted password.
        """
        try:
            with self.password_file.open("rb") as secret_file:
                raw = secret_file.read(4097)
            password = raw.decode("utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ValueError("Cannot read the PostgreSQL password secret") from None
        if (
            len(raw) > 4096
            or not password.strip()
            or any(character in password for character in "\r\n\x00")
        ):
            raise ValueError("Invalid PostgreSQL password secret")
        self._password = SecretStr(password)
        return self

    @property
    def url(self) -> URL:
        """Return a driver URL that safely handles special characters in credentials."""
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self._password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )
