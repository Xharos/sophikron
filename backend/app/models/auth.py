"""Authentication persistence; only users contains reversibly encrypted identities."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApplicationState(Base):
    """Persist installation completion independently of environment settings and accounts."""

    __tablename__ = "application_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(Base):
    """An account identified internally by UUID and externally by encrypted identity fields."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('pending_activation', 'active', 'disabled')", name="status"),
        CheckConstraint("status != 'active' OR password_hash IS NOT NULL", name="active_password"),
        CheckConstraint(
            "status != 'pending_activation' OR password_hash IS NULL", name="pending_password"
        ),
        CheckConstraint("login_count >= 0", name="login_count"),
        CheckConstraint("octet_length(username_lookup) = 32", name="username_lookup_length"),
        CheckConstraint("octet_length(email_lookup) = 32", name="email_lookup_length"),
        CheckConstraint(
            "(email_encrypted IS NOT NULL AND email_lookup IS NOT NULL) OR "
            "(is_bootstrap AND email_encrypted IS NULL AND email_lookup IS NULL)",
            name="email_identity",
        ),
        CheckConstraint(
            "is_bootstrap = (bootstrap_expires_at IS NOT NULL)", name="bootstrap_expiration"
        ),
        Index(
            "uq_users_bootstrap", "is_bootstrap", unique=True, postgresql_where=text("is_bootstrap")
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    email_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    username_lookup: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    email_lookup: Mapped[bytes | None] = mapped_column(LargeBinary, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), server_default="pending_activation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    login_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    is_bootstrap: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    bootstrap_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    """An extensible role catalogue independent of Python enums."""

    __tablename__ = "roles"
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,63}$'", name="code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    """Associate any number of explicit roles with an account."""

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("sophikron.roles.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """A revocable browser session containing only a verifier of its bearer secret."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="token_length"),
        CheckConstraint("expires_at > created_at", name="expiration"),
        CheckConstraint("last_activity_at >= created_at", name="activity"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(64))


class AccountInvitation(Base):
    """A single-use initial activation credential issued by an administrator or bootstrap."""

    __tablename__ = "account_invitations"
    __table_args__ = (
        CheckConstraint("octet_length(token_hash) = 32", name="token_length"),
        CheckConstraint("expires_at > created_at", name="expiration"),
        CheckConstraint("used_at IS NULL OR used_at >= created_at", name="usage"),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation"),
        CheckConstraint("delivery_method IN ('email', 'manual')", name="delivery"),
        CheckConstraint(
            "(issuance_kind = 'bootstrap' AND issued_by_user_id IS NULL) OR "
            "(issuance_kind = 'admin' AND issued_by_user_id IS NOT NULL)",
            name="issuer",
        ),
        CheckConstraint(
            "delivery_method != 'manual' OR issuance_kind = 'bootstrap'", name="manual_bootstrap"
        ),
        Index(
            "uq_account_invitations_outstanding",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    issued_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sophikron.users.id", ondelete="RESTRICT"), index=True
    )
    issuance_kind: Mapped[str] = mapped_column(String(16))
    delivery_method: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginEvent(Base):
    """Retain successful login times independently of expiring session records."""

    __tablename__ = "login_events"
    __table_args__ = (Index("ix_login_events_user_time", "user_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("sophikron.users.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthRateLimit(Base):
    """Share bounded, fixed-window attempt budgets across application workers."""

    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        CheckConstraint("octet_length(key) = 32", name="key_length"),
        CheckConstraint("attempts >= 0", name="attempts"),
    )

    key: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginAttempt(Base):
    """Lease pending login capacity across workers without counting it as a failure."""

    __tablename__ = "login_attempts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ip_key: Mapped[bytes] = mapped_column(
        ForeignKey("sophikron.auth_rate_limits.key", ondelete="CASCADE"), index=True
    )
    identity_key: Mapped[bytes] = mapped_column(
        ForeignKey("sophikron.auth_rate_limits.key", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
