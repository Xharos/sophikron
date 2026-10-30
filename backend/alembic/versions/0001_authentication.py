"""Create installation state, encrypted accounts, roles, sessions and explicit permissions.

Consolidated with explicit owner authorization for fresh development installations.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001_authentication"
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
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ip_key", sa.LargeBinary(), nullable=False),
        sa.Column("identity_key", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ip_key"],
            ["sophikron.auth_rate_limits.key"],
            name=op.f("fk_login_attempts_ip_key_auth_rate_limits"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["identity_key"],
            ["sophikron.auth_rate_limits.key"],
            name=op.f("fk_login_attempts_identity_key_auth_rate_limits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
        schema="sophikron",
    )
    for column in ("ip_key", "identity_key", "expires_at"):
        op.create_index(
            op.f(f"ix_login_attempts_{column}"),
            "login_attempts",
            [column],
            unique=False,
            schema="sophikron",
        )
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
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
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("username_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("first_name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("last_name_encrypted", sa.LargeBinary(), nullable=True),
        sa.CheckConstraint(
            "is_bootstrap OR (first_name_encrypted IS NOT NULL AND "
            "last_name_encrypted IS NOT NULL)",
            name=op.f("ck_users_permanent_names"),
        ),
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
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "manually_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("profile_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("birth_date_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("city_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("postal_code_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("commune_code_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("previous_school_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("baccalaureate_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("orientation_project_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("phone_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("reference_adult_encrypted", sa.LargeBinary(), nullable=True),
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
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("issued_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("issuance_kind", sa.String(length=16), nullable=False),
        sa.Column("delivery_method", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(16), server_default="activation", nullable=False),
        sa.CheckConstraint(
            "purpose IN ('activation', 'reset')", name=op.f("ck_account_invitations_purpose")
        ),
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
        "sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
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
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
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
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
        schema="sophikron",
    )
    op.bulk_insert(
        roles,
        [
            {
                "code": "admin",
                "description": "Administrator",
            },
            {
                "code": "teacher",
                "description": "Teacher",
            },
            {
                "code": "kholleur",
                "description": "Oral examiner",
            },
            {
                "code": "user",
                "description": "User",
            },
        ],
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name=op.f("uq_permissions_code")),
        schema="sophikron",
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["sophikron.roles.id"],
            ondelete="CASCADE",
            name=op.f("fk_role_permissions_role_id_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["sophikron.permissions.id"],
            ondelete="CASCADE",
            name=op.f("fk_role_permissions_permission_id_permissions"),
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permissions")),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_role_permissions_permission_id"),
        "role_permissions",
        ["permission_id"],
        schema="sophikron",
    )
    for role, codes in {
        "admin": [
            "users.read",
            "users.manage",
            "promotions.read",
            "promotions.manage",
            "events.read",
            "statistics.read",
            "profiles.read",
            "profiles.manage",
        ],
        "teacher": ["teacher.access", "teaching.read", "profiles.read", "orientation.manage"],
        "user": ["user.access"],
        "kholleur": ["kholleur.access"],
    }.items():
        for code in codes:
            op.execute(
                sa.text(
                    "INSERT INTO sophikron.permissions (code, description) VALUES (:code, :code) "
                    "ON CONFLICT (code) DO NOTHING"
                ).bindparams(code=code)
            )
            op.execute(
                sa.text(
                    "INSERT INTO sophikron.role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM sophikron.roles r CROSS JOIN sophikron.permissions p "
                    "WHERE r.code = :role AND p.code = :code"
                ).bindparams(role=role, code=code)
            )
    op.execute("""
        CREATE FUNCTION sophikron.lock_role_account() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM id FROM sophikron.users WHERE id IN (
                CASE WHEN TG_OP <> 'INSERT' THEN OLD.user_id ELSE NULL END,
                CASE WHEN TG_OP <> 'DELETE' THEN NEW.user_id ELSE NULL END
            ) ORDER BY id FOR UPDATE;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER lock_role_account BEFORE INSERT OR UPDATE OR DELETE
        ON sophikron.user_roles FOR EACH ROW EXECUTE FUNCTION sophikron.lock_role_account()
    """)
    op.execute("""
        CREATE FUNCTION sophikron.validate_account_roles() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE account_id bigint;
        BEGIN
            FOR account_id IN SELECT DISTINCT id FROM (VALUES
                (CASE WHEN TG_OP <> 'INSERT' THEN OLD.user_id ELSE NULL END),
                (CASE WHEN TG_OP <> 'DELETE' THEN NEW.user_id ELSE NULL END)
            ) AS affected(id) WHERE id IS NOT NULL LOOP
                IF EXISTS (
                    SELECT 1 FROM sophikron.user_roles ur
                    JOIN sophikron.roles r ON r.id = ur.role_id
                    WHERE ur.user_id = account_id AND r.code = 'user'
                ) AND EXISTS (
                    SELECT 1 FROM sophikron.user_roles ur
                    JOIN sophikron.roles r ON r.id = ur.role_id
                    WHERE ur.user_id = account_id AND r.code <> 'user'
                ) THEN
                    RAISE EXCEPTION 'Incompatible account roles' USING ERRCODE = '23514';
                END IF;
            END LOOP;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER validate_roles AFTER INSERT OR UPDATE OR DELETE
        ON sophikron.user_roles DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION sophikron.validate_account_roles()
    """)
    op.execute("GRANT EXECUTE ON FUNCTION sophikron.lock_role_account() TO sophikron_app")
    op.execute("GRANT EXECUTE ON FUNCTION sophikron.validate_account_roles() TO sophikron_app")
    op.execute(
        "REVOKE INSERT, UPDATE, DELETE ON sophikron.roles, sophikron.permissions, "
        "sophikron.role_permissions FROM sophikron_app"
    )
    op.create_table(
        "activity_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("subject_user_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_role", sa.String(16), nullable=True),
        sa.Column("subject_role", sa.String(16), nullable=True),
        sa.Column("promotion_snapshot", JSONB(), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.BigInteger(), nullable=True),
        sa.Column("data", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["sophikron.users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_activity_events_actor_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["sophikron.users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_activity_events_subject_user_id_users"),
        ),
        sa.CheckConstraint(
            "event_type ~ '^[a-z][a-z0-9_.]{0,95}$'", name=op.f("ck_activity_events_event_type")
        ),
        sa.CheckConstraint("schema_version > 0", name=op.f("ck_activity_events_schema_version")),
        sa.CheckConstraint(
            "actor_role IN ('admin', 'teacher', 'kholleur', 'user')",
            name=op.f("ck_activity_events_actor_role"),
        ),
        sa.CheckConstraint(
            "subject_role IN ('admin', 'teacher', 'kholleur', 'user')",
            name=op.f("ck_activity_events_subject_role"),
        ),
        sa.CheckConstraint(
            "actor_user_id IS NOT NULL OR actor_role IS NULL",
            name=op.f("ck_activity_events_actor_snapshot"),
        ),
        sa.CheckConstraint(
            "subject_user_id IS NOT NULL OR subject_role IS NULL",
            name=op.f("ck_activity_events_subject_snapshot"),
        ),
        sa.CheckConstraint(
            "promotion_snapshot IS NULL OR (resource_type = 'promotion' AND "
            "jsonb_typeof(promotion_snapshot) = 'object' AND "
            "octet_length(promotion_snapshot::text) <= 1024)",
            name=op.f("ck_activity_events_promotion_snapshot"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(data) = 'object'", name=op.f("ck_activity_events_data_object")
        ),
        sa.CheckConstraint(
            "octet_length(data::text) <= 4096", name=op.f("ck_activity_events_data_size")
        ),
        sa.CheckConstraint(
            "(resource_type IS NULL AND resource_id IS NULL) OR "
            "(resource_type IS NOT NULL AND resource_id IS NOT NULL AND resource_id > 0)",
            name=op.f("ck_activity_events_resource"),
        ),
        schema="sophikron",
    )
    for name, columns in (
        ("ix_activity_events_time_id", ["occurred_at", "id"]),
        ("ix_activity_events_type_time_id", ["event_type", "occurred_at", "id"]),
        ("ix_activity_events_actor_time", ["actor_user_id", "occurred_at"]),
        ("ix_activity_events_subject_time", ["subject_user_id", "occurred_at"]),
        ("ix_activity_events_resource", ["resource_type", "resource_id", "id"]),
        ("ix_activity_events_event_type", ["event_type"]),
    ):
        op.create_index(name, "activity_events", columns, schema="sophikron")
    op.execute("REVOKE UPDATE, DELETE ON sophikron.activity_events FROM sophikron_app")


def downgrade() -> None:
    """Remove authentication data while preserving provisioned schema and database roles."""
    op.drop_table("activity_events", schema="sophikron")
    # Reverse dependency order preserves provisioned schema and unrelated objects.
    op.execute("DROP TRIGGER validate_roles ON sophikron.user_roles")
    op.execute("DROP TRIGGER lock_role_account ON sophikron.user_roles")
    op.execute("DROP FUNCTION sophikron.validate_account_roles()")
    op.execute("DROP FUNCTION sophikron.lock_role_account()")
    op.drop_table("role_permissions", schema="sophikron")
    op.drop_table("permissions", schema="sophikron")
    op.drop_index(op.f("ix_user_roles_role_id"), table_name="user_roles", schema="sophikron")
    op.drop_table("user_roles", schema="sophikron")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions", schema="sophikron")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions", schema="sophikron")
    op.drop_table("sessions", schema="sophikron")
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
