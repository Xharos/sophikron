"""Add private whole-class timetables and independent subscription verifiers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_timetable"
down_revision = "0006_promotion_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create additive agenda tables without altering existing data or permissions."""
    op.create_table(
        "timetable_calendars",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=True),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["promotion_id"], ["sophikron.promotions.id"], ondelete="RESTRICT"),
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
        sa.Column("published_revision", sa.String(32)),
        sa.Column("published", postgresql.JSONB(none_as_null=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("calendar_id", "school_year"),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_timetable_years_period")),
        sa.ForeignKeyConstraint(
            ["calendar_id"], ["sophikron.timetable_calendars.id"], ondelete="CASCADE"
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_timetable_years_calendar_id", "timetable_years", ["calendar_id"], schema="sophikron"
    )
    op.create_table(
        "timetable_series",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("year_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_timetable_subscriptions_token_length")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sophikron.users.id"], ondelete="CASCADE"),
        schema="sophikron",
    )


def downgrade() -> None:
    """Remove only timetable-specific data, retaining accounts and promotions."""
    for table in (
        "timetable_subscriptions",
        "timetable_series",
        "timetable_years",
        "timetable_rooms",
        "timetable_calendars",
    ):
        op.drop_table(table, schema="sophikron")
