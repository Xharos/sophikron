"""Create annual timetables, kholle bounds, audiences and revocable ICS subscriptions."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_timetable"
down_revision: str = "0006_promotion_groups"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create timetable storage, availability bounds, archive policy and personal calendar links."""
    op.create_table(
        "timetable_calendars",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False, unique=True),
        sa.Column("promotion_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("is_paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["promotion_id"], ["sophikron.promotions.id"], ondelete="RESTRICT"),
        schema="sophikron",
    )
    op.create_index(
        "uq_timetable_active_promotion",
        "timetable_calendars",
        ["promotion_id"],
        unique=True,
        postgresql_where=sa.text("NOT is_archived AND promotion_id IS NOT NULL"),
        schema="sophikron",
    )
    op.create_index(
        "ix_timetable_calendars_promotion_id",
        "timetable_calendars",
        ["promotion_id"],
        schema="sophikron",
    )
    op.create_table(
        "timetable_rooms",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("name_key", sa.String(80), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        schema="sophikron",
    )
    op.create_table(
        "timetable_school_years",
        sa.Column("school_year", sa.Integer(), primary_key=True),
        sa.Column("used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        schema="sophikron",
    )
    op.create_table(
        "teacher_availability",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("ranges", postgresql.JSONB(), nullable=True),
        sa.Column("kholle_min_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("kholle_max_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "kholle_min_hours >= 0", name=op.f("ck_teacher_availability_kholle_min_hours")
        ),
        sa.CheckConstraint(
            "kholle_max_hours >= kholle_min_hours",
            name=op.f("ck_teacher_availability_kholle_max_hours"),
        ),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "school_year"),
        sa.ForeignKeyConstraint(["user_id"], ["sophikron.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["school_year"], ["sophikron.timetable_school_years.school_year"], ondelete="CASCADE"
        ),
        schema="sophikron",
    )
    op.create_table(
        "timetable_years",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("calendar_id", sa.BigInteger(), nullable=False),
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("calendar_id"),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_timetable_years_period")),
        sa.ForeignKeyConstraint(
            ["calendar_id"], ["sophikron.timetable_calendars.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["school_year"], ["sophikron.timetable_school_years.school_year"]),
        schema="sophikron",
    )
    op.create_index(
        "ix_timetable_years_calendar_id", "timetable_years", ["calendar_id"], schema="sophikron"
    )
    op.create_table(
        "timetable_series",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("year_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("teacher_id", sa.BigInteger(), nullable=True),
        sa.Column("room_id", sa.BigInteger(), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["year_id"], ["sophikron.timetable_years.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["sophikron.subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["teacher_id"], ["sophikron.users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["room_id"], ["sophikron.timetable_rooms.id"], ondelete="RESTRICT"),
        schema="sophikron",
    )

    op.create_index(
        "ix_timetable_series_year_id", "timetable_series", ["year_id"], schema="sophikron"
    )
    op.create_table(
        "timetable_subscriptions",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_timetable_subscriptions_token_length")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sophikron.users.id"], ondelete="CASCADE"),
        schema="sophikron",
    )
    op.create_table(
        "promotion_custom_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("x", sa.Integer(), server_default="320", nullable=False),
        sa.Column("y", sa.Integer(), server_default="20", nullable=False),
        sa.ForeignKeyConstraint(["promotion_id"], ["sophikron.promotions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("promotion_id", "name_key"),
        sa.UniqueConstraint("id", "promotion_id"),
        sa.CheckConstraint(
            "x BETWEEN 0 AND 1000000 AND y BETWEEN 0 AND 1000000",
            name=op.f("ck_promotion_custom_groups_position"),
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_promotion_custom_groups_promotion_id",
        "promotion_custom_groups",
        ["promotion_id"],
        schema="sophikron",
    )
    op.create_table(
        "promotion_custom_group_members",
        sa.Column("group_id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "promotion_id"],
            [
                "sophikron.promotion_custom_groups.id",
                "sophikron.promotion_custom_groups.promotion_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "promotion_id"],
            ["sophikron.user_promotions.user_id", "sophikron.user_promotions.promotion_id"],
            ondelete="CASCADE",
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_promotion_custom_group_members_user_id",
        "promotion_custom_group_members",
        ["user_id"],
        schema="sophikron",
    )
    op.create_table(
        "timetable_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auto_archive", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_rollover_year", sa.Integer(), nullable=True),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_timetable_preferences_singleton")),
        schema="sophikron",
    )
    preferences = sa.table(
        "timetable_preferences",
        sa.column("id", sa.Integer()),
        sa.column("revision", sa.String(32)),
        schema="sophikron",
    )
    op.bulk_insert(preferences, [{"id": 1, "revision": uuid4().hex}])

    op.create_table(
        "calendar_usage_totals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requests", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1 AND requests >= 0", name="counts"),
        schema="sophikron",
    )


def downgrade() -> None:
    """Remove timetable and custom audience tables, retaining prior features and partitions."""
    for table in (
        "timetable_preferences",
        "promotion_custom_group_members",
        "promotion_custom_groups",
        "calendar_usage_totals",
        "timetable_subscriptions",
        "timetable_series",
        "timetable_years",
        "teacher_availability",
        "timetable_school_years",
        "timetable_rooms",
        "timetable_calendars",
    ):
        op.drop_table(table, schema="sophikron")
