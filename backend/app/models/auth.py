"""Authentication persistence; only users contains reversibly encrypted identities."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
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
    """An integer-keyed account whose external identity fields remain encrypted."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('pending_activation', 'active', 'disabled')", name="status"),
        CheckConstraint("status != 'active' OR password_hash IS NOT NULL", name="active_password"),
        CheckConstraint(
            "status != 'pending_activation' OR password_hash IS NULL", name="pending_password"
        ),
        CheckConstraint("login_count >= 0", name="login_count"),
        CheckConstraint(
            "is_bootstrap OR (first_name_encrypted IS NOT NULL AND "
            "last_name_encrypted IS NOT NULL)",
            name="permanent_names",
        ),
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

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    first_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manually_archived: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    profile_version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    birth_date_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    city_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    postal_code_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    commune_code_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_school_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    baccalaureate_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    orientation_project_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    reference_adult_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)


class Role(Base):
    """An extensible role catalogue independent of Python enums."""

    __tablename__ = "roles"
    __table_args__ = (CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,63}$'", name="code"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    """Associate any number of explicit roles with an account."""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sophikron.roles.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
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

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="CASCADE"), index=True
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
        CheckConstraint("purpose IN ('activation', 'reset')", name="purpose"),
        CheckConstraint(
            "(issuance_kind = 'bootstrap' AND issued_by_user_id IS NULL) OR "
            "(issuance_kind = 'admin' AND issued_by_user_id IS NOT NULL)",
            name="issuer",
        ),
        Index(
            "uq_account_invitations_outstanding",
            "user_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    issued_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sophikron.users.id", ondelete="RESTRICT"), index=True
    )
    issuance_kind: Mapped[str] = mapped_column(String(16))
    delivery_method: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[str] = mapped_column(String(16), server_default="activation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ip_key: Mapped[bytes] = mapped_column(
        ForeignKey("sophikron.auth_rate_limits.key", ondelete="CASCADE"), index=True
    )
    identity_key: Mapped[bytes] = mapped_column(
        ForeignKey("sophikron.auth_rate_limits.key", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
