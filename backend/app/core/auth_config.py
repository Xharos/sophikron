"""Validated authentication settings; key material lives in separate secret files."""

from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security_policy import read_bootstrap_password


class AuthSettings(BaseSettings):
    """Read AUTH_* variables without loading local dotenv files."""

    model_config = SettingsConfigDict(
        env_prefix="AUTH_", env_file=None, frozen=True, hide_input_in_errors=True, extra="ignore"
    )

    environment: Literal["production", "development", "test"] = "production"
    keys_file: Path = Field(repr=False, exclude=True)
    allowed_origins: list[str] = Field(min_length=1)
    cors_enabled: bool = True
    manual_invitations_enabled: bool = False
    cookie_secure: bool = True
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    idle_seconds: int = Field(default=1800, ge=60, le=86400)
    invitation_seconds: int = Field(default=172800, ge=60, le=172800)
    argon_memory_kib: int = Field(default=65536, ge=8192, le=262144)
    argon_iterations: int = Field(default=3, ge=1, le=10)
    argon_parallelism: int = Field(default=4, ge=1, le=8)
    password_workers: int = Field(default=2, ge=1, le=8)
    password_queue_size: int = Field(default=8, ge=0, le=100)
    password_queue_timeout_seconds: float = Field(default=5, gt=0, le=30, allow_inf_nan=False)
    request_max_bytes: int = Field(default=16384, ge=1024, le=1048576)
    request_body_timeout_seconds: float = Field(default=10, gt=0, le=60, allow_inf_nan=False)
    login_reservation_seconds: int = Field(default=120, ge=60, le=300)
    rate_window_seconds: int = Field(default=900, ge=1, le=3600)
    login_identity_limit: int = Field(default=5, ge=1, le=1000)
    login_ip_limit: int = Field(default=20, ge=1, le=10000)
    mail_transport: Literal["disabled", "smtp"] = "disabled"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password_file: Path | None = Field(default=None, repr=False, exclude=True)
    smtp_sender: str | None = None
    smtp_security: Literal["starttls", "tls"] = "starttls"
    activation_url: str | None = None
    bootstrap_username: str | None = None
    bootstrap_password_file: Path | None = Field(default=None, repr=False, exclude=True)

    @field_validator(
        "bootstrap_username",
        "bootstrap_password_file",
        "smtp_host",
        "smtp_username",
        "smtp_password_file",
        "smtp_sender",
        "activation_url",
        mode="before",
    )
    @classmethod
    def empty_optional(cls, value: object) -> object:
        """Treat empty optional Compose environment entries as unconfigured values."""
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_security(self) -> Self:
        """Reject unsafe production settings and incomplete bootstrap or SMTP settings."""
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
                or (self.environment == "production" and parsed.scheme != "https")
            ):
                raise ValueError("Invalid allowed origin")
        if self.environment == "production" and (
            not self.cookie_secure or self.argon_memory_kib < 19456 or self.argon_iterations < 2
        ):
            raise ValueError("Unsafe production authentication settings")
        if self.mail_transport == "smtp":
            if not all((self.smtp_host, self.smtp_sender, self.activation_url)):
                raise ValueError("SMTP requires host, sender and activation URL")
            if bool(self.smtp_username) != bool(self.smtp_password_file):
                raise ValueError("SMTP credentials must be configured together")
        if self.activation_url:
            parsed = urlsplit(self.activation_url)
            if (
                not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
                or parsed.scheme not in {"https", "http"}
                or (self.environment == "production" and parsed.scheme != "https")
            ):
                raise ValueError("Invalid activation URL")
        return self

    def bootstrap_password(self) -> str:
        """Load the installation secret only when initial setup or explicit recovery needs it."""
        return read_bootstrap_password(self.bootstrap_password_file)

    @property
    def cookie_name(self) -> str:
        """Return a host-only production cookie or a distinct local development cookie."""
        return "__Host-sophikron_session" if self.cookie_secure else "sophikron_session_dev"
