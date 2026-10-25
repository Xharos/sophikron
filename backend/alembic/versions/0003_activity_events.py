"""Create a general append-only activity journal instead of login-specific events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_activity_events"
down_revision: str = "0002_promotions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create normalized event references, bounded JSON metadata and journal indexes."""
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
            "actor_role IN ('admin', 'teacher', 'user')", name=op.f("ck_activity_events_actor_role")
        ),
        sa.CheckConstraint(
            "subject_role IN ('admin', 'teacher', 'user')",
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
    """Remove the event journal only through an explicit migration operation."""
    op.drop_table("activity_events", schema="sophikron")
