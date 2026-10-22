"""Create installation state, encrypted accounts, roles, sessions and login statistics.

Consolidated with explicit owner authorization for fresh development installations.
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0001_database_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the complete authentication schema and its uninitialized installation state."""
    # Frozen initial schema, ordered by foreign-key dependencies.
    op.create_table(
        "application_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_application_state_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_state")),
        schema="sophikron",
    )
    op.execute("INSERT INTO sophikron.application_state (id, initialized_at) VALUES (1, NULL)")
    op.create_table(
        "auth_rate_limits",
        sa.Column("key", sa.LargeBinary(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_auth_rate_limits_attempts")),
        sa.CheckConstraint("octet_length(key) = 32", name=op.f("ck_auth_rate_limits_key_length")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_rate_limits")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_auth_rate_limits_expires_at"),
        "auth_rate_limits",
        ["expires_at"],
        unique=False,
        schema="sophikron",
    )
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ip_key", sa.LargeBinary(), nullable=False),
        sa.Column("identity_key", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ip_key"], ["sophikron.auth_rate_limits.key"],
            name=op.f("fk_login_attempts_ip_key_auth_rate_limits"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["identity_key"], ["sophikron.auth_rate_limits.key"],
            name=op.f("fk_login_attempts_identity_key_auth_rate_limits"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
        schema="sophikron",
    )
    for column in ("ip_key", "identity_key", "expires_at"):
        op.create_index(
            op.f(f"ix_login_attempts_{column}"), "login_attempts", [column],
            unique=False, schema="sophikron",
        )
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{0,63}$'", name=op.f("ck_roles_code")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
        schema="sophikron",
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("username_lookup", sa.LargeBinary(), nullable=False),
        sa.Column("email_lookup", sa.LargeBinary(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default="pending_activation", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("login_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("is_bootstrap", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("bootstrap_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status != 'active' OR password_hash IS NOT NULL", name=op.f("ck_users_active_password")
        ),
        sa.CheckConstraint(
            "status != 'pending_activation' OR password_hash IS NULL",
            name=op.f("ck_users_pending_password"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_activation', 'active', 'disabled')", name=op.f("ck_users_status")
        ),
        sa.CheckConstraint(
            "is_bootstrap = (bootstrap_expires_at IS NOT NULL)",
            name=op.f("ck_users_bootstrap_expiration"),
        ),
        sa.CheckConstraint("login_count >= 0", name=op.f("ck_users_login_count")),
        sa.CheckConstraint(
            "octet_length(email_lookup) = 32", name=op.f("ck_users_email_lookup_length")
        ),
        sa.CheckConstraint(
            "(email_encrypted IS NOT NULL AND email_lookup IS NOT NULL) OR "
            "(is_bootstrap AND email_encrypted IS NULL AND email_lookup IS NULL)",
            name=op.f("ck_users_email_identity"),
        ),
        sa.CheckConstraint(
            "octet_length(username_lookup) = 32", name=op.f("ck_users_username_lookup_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email_lookup", name=op.f("uq_users_email_lookup")),
        sa.UniqueConstraint("username_lookup", name=op.f("uq_users_username_lookup")),
        schema="sophikron",
    )
    op.create_index(
        "uq_users_bootstrap",
        "users",
        ["is_bootstrap"],
        unique=True,
        schema="sophikron",
        postgresql_where=sa.text("is_bootstrap"),
    )
    op.create_table(
        "account_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("issuance_kind", sa.String(length=16), nullable=False),
        sa.Column("delivery_method", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(issuance_kind = 'bootstrap' AND issued_by_user_id IS NULL) OR "
            "(issuance_kind = 'admin' AND issued_by_user_id IS NOT NULL)",
            name=op.f("ck_account_invitations_issuer"),
        ),
        sa.CheckConstraint(
            "delivery_method != 'manual' OR issuance_kind = 'bootstrap'",
            name=op.f("ck_account_invitations_manual_bootstrap"),
        ),
        sa.CheckConstraint(
            "delivery_method IN ('email', 'manual')", name=op.f("ck_account_invitations_delivery")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_account_invitations_expiration")
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_account_invitations_token_length")
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_account_invitations_revocation"),
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= created_at", name=op.f("ck_account_invitations_usage")
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["sophikron.users.id"],
            name=op.f("fk_account_invitations_issued_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            name=op.f("fk_account_invitations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_account_invitations_token_hash")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_account_invitations_expires_at"),
        "account_invitations",
        ["expires_at"],
        unique=False,
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_account_invitations_issued_by_user_id"),
        "account_invitations",
        ["issued_by_user_id"],
        unique=False,
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_account_invitations_user_id"),
        "account_invitations",
        ["user_id"],
        unique=False,
        schema="sophikron",
    )
    op.create_index(
        "uq_account_invitations_outstanding",
        "account_invitations",
        ["user_id"],
        unique=True,
        schema="sophikron",
        postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "login_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            name=op.f("fk_login_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_events")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_login_events_occurred_at"),
        "login_events",
        ["occurred_at"],
        unique=False,
        schema="sophikron",
    )
    op.create_index(
        "ix_login_events_user_time",
        "login_events",
        ["user_id", "occurred_at"],
        unique=False,
        schema="sophikron",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_sessions_expiration")),
        sa.CheckConstraint("last_activity_at >= created_at", name=op.f("ck_sessions_activity")),
        sa.CheckConstraint("octet_length(token_hash) = 32", name=op.f("ck_sessions_token_length")),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name=op.f("ck_sessions_revocation")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False, schema="sophikron"
    )
    op.create_index(
        op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False, schema="sophikron"
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["sophikron.roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            name=op.f("fk_user_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_user_roles_role_id"), "user_roles", ["role_id"], unique=False, schema="sophikron"
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
        schema="sophikron",
    )
    op.bulk_insert(
        roles,
        [
            {
                "id": UUID("144a4c76-6995-4538-92dd-36b98e2e1901"),
                "code": "admin",
                "description": "Administrator",
            },
            {
                "id": UUID("144a4c76-6995-4538-92dd-36b98e2e1902"),
                "code": "teacher",
                "description": "Teacher",
            },
            {
                "id": UUID("144a4c76-6995-4538-92dd-36b98e2e1903"),
                "code": "student",
                "description": "Student",
            },
        ],
    )


def downgrade() -> None:
    """Remove authentication data while preserving provisioned schema and database roles."""
    # Reverse dependency order preserves provisioned schema and unrelated objects.
    op.drop_index(op.f("ix_user_roles_role_id"), table_name="user_roles", schema="sophikron")
    op.drop_table("user_roles", schema="sophikron")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions", schema="sophikron")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions", schema="sophikron")
    op.drop_table("sessions", schema="sophikron")
    op.drop_index("ix_login_events_user_time", table_name="login_events", schema="sophikron")
    op.drop_index(
        op.f("ix_login_events_occurred_at"), table_name="login_events", schema="sophikron"
    )
    op.drop_table("login_events", schema="sophikron")
    op.drop_index(
        "uq_account_invitations_outstanding",
        table_name="account_invitations",
        schema="sophikron",
        postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_index(
        op.f("ix_account_invitations_user_id"), table_name="account_invitations", schema="sophikron"
    )
    op.drop_index(
        op.f("ix_account_invitations_issued_by_user_id"),
        table_name="account_invitations",
        schema="sophikron",
    )
    op.drop_index(
        op.f("ix_account_invitations_expires_at"),
        table_name="account_invitations",
        schema="sophikron",
    )
    op.drop_table("account_invitations", schema="sophikron")
    op.drop_index(
        "uq_users_bootstrap",
        table_name="users",
        schema="sophikron",
        postgresql_where=sa.text("is_bootstrap"),
    )
    op.drop_table("users", schema="sophikron")
    op.drop_table("roles", schema="sophikron")
    for column in ("expires_at", "identity_key", "ip_key"):
        op.drop_index(
            op.f(f"ix_login_attempts_{column}"), table_name="login_attempts", schema="sophikron"
        )
    op.drop_table("login_attempts", schema="sophikron")
    op.drop_index(
        op.f("ix_auth_rate_limits_expires_at"), table_name="auth_rate_limits", schema="sophikron"
    )
    op.drop_table("auth_rate_limits", schema="sophikron")
    op.drop_table("application_state", schema="sophikron")
