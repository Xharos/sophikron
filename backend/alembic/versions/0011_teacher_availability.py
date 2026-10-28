"""Rebuild timetable business storage as live annual calendars (authorized data reset)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_teacher_availability"
down_revision = "0010_timetable_optional_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reset timetable-only storage and install live calendars with independent availability."""
    # Allows explicitly replaying this rewritten revision over its former version.
    op.execute("DROP TABLE IF EXISTS sophikron.teacher_availability")
    op.create_table(
        "teacher_availability",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("ranges", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sophikron.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["school_year"], ["sophikron.timetable_school_years.school_year"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "school_year"),
        schema="sophikron",
    )
    # Explicitly authorized reset of timetable data only. Accounts, promotions,
    # subjects and their groups are preserved. No database or volume is reset.
    for table in (
        "timetable_template_versions",
        "timetable_series",
        "timetable_years",
        "timetable_calendars",
        "teacher_availability",
        "timetable_school_years",
        "timetable_subscriptions",
        "timetable_rooms",
    ):
        op.execute(sa.text(f"DELETE FROM sophikron.{table}"))
    op.drop_table("timetable_template_versions", schema="sophikron")
    op.alter_column(
        "timetable_calendars", "is_deleted", new_column_name="is_archived", schema="sophikron"
    )
    op.add_column(
        "timetable_calendars",
        sa.Column("name_key", sa.String(300), nullable=False),
        schema="sophikron",
    )
    op.create_unique_constraint(
        "uq_timetable_calendars_name_key", "timetable_calendars", ["name_key"], schema="sophikron"
    )
    op.create_index(
        "uq_timetable_active_promotion",
        "timetable_calendars",
        ["promotion_id"],
        unique=True,
        postgresql_where=sa.text("NOT is_archived AND promotion_id IS NOT NULL"),
        schema="sophikron",
    )
    op.drop_column("timetable_school_years", "settings", schema="sophikron")
    op.add_column(
        "timetable_school_years",
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="sophikron",
    )
    op.drop_constraint(
        "uq_timetable_years_calendar_id", "timetable_years", type_="unique", schema="sophikron"
    )
    op.create_unique_constraint(
        "uq_timetable_years_calendar_id", "timetable_years", ["calendar_id"], schema="sophikron"
    )
    for column in ("published_revision", "published", "published_at"):
        op.drop_column("timetable_years", column, schema="sophikron")
    op.add_column(
        "timetable_years",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="sophikron",
    )


def downgrade() -> None:
    """Restore the previous schema; intentionally discarded timetable data cannot be recovered."""
    op.add_column(
        "timetable_years", sa.Column("published_revision", sa.String(32)), schema="sophikron"
    )
    op.add_column(
        "timetable_years",
        sa.Column("published", postgresql.JSONB(none_as_null=True)),
        schema="sophikron",
    )
    op.add_column(
        "timetable_years", sa.Column("published_at", sa.DateTime(timezone=True)), schema="sophikron"
    )
    op.drop_column("timetable_years", "updated_at", schema="sophikron")
    op.drop_constraint(
        "uq_timetable_years_calendar_id", "timetable_years", type_="unique", schema="sophikron"
    )
    op.create_unique_constraint(
        "uq_timetable_years_calendar_id",
        "timetable_years",
        ["calendar_id", "school_year"],
        schema="sophikron",
    )
    op.drop_index(
        "uq_timetable_active_promotion", table_name="timetable_calendars", schema="sophikron"
    )
    op.drop_column("timetable_calendars", "name_key", schema="sophikron")
    op.alter_column(
        "timetable_calendars", "is_archived", new_column_name="is_deleted", schema="sophikron"
    )
    op.drop_column("timetable_school_years", "used", schema="sophikron")
    op.add_column(
        "timetable_school_years",
        sa.Column("settings", postgresql.JSONB(none_as_null=True)),
        schema="sophikron",
    )
    op.create_table(
        "timetable_template_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("year_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("blocks", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["year_id"], ["sophikron.timetable_years.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("year_id", "number"),
        sa.CheckConstraint("number > 0", name=op.f("ck_timetable_template_versions_number")),
        schema="sophikron",
    )
    op.create_index(
        "ix_timetable_template_versions_year_id",
        "timetable_template_versions",
        ["year_id"],
        schema="sophikron",
    )
    op.drop_table("teacher_availability", schema="sophikron")
