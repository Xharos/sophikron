"""Register application metadata for Alembic without initializing connections."""

from app.models.auth import (
    AccountInvitation,
    ApplicationState,
    AuthRateLimit,
    LoginAttempt,
    LoginEvent,
    Role,
    Session,
    User,
    UserRole,
)

__all__ = [
    "AccountInvitation",
    "ApplicationState",
    "AuthRateLimit",
    "LoginAttempt",
    "LoginEvent",
    "Role",
    "Session",
    "User",
    "UserRole",
]
