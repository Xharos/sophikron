"""Register application metadata for Alembic without initializing connections."""

from app.models.activity import ActivityEvent
from app.models.auth import (
    AccountInvitation,
    ApplicationState,
    AuthRateLimit,
    LoginAttempt,
    Role,
    Session,
    User,
    UserRole,
)
from app.models.permissions import Permission, RolePermission
from app.models.promotions import Promotion, UserPromotion

__all__ = [
    "AccountInvitation",
    "ActivityEvent",
    "ApplicationState",
    "AuthRateLimit",
    "LoginAttempt",
    "Permission",
    "Promotion",
    "Role",
    "RolePermission",
    "Session",
    "User",
    "UserPromotion",
    "UserRole",
]
