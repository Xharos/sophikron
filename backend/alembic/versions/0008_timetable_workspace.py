"""Add shared settings, reversible catalogue removal and dated weekly pattern versions."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_timetable_workspace"
down_revision = "0007_timetable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve every existing timetable and avoid choosing between differing legacy settings."""
    op.add_column(
        "timetable_calendars",
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="sophikron",
    )
    op.add_column(
        "timetable_calendars",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="sophikron",
    )
    op.add_column(
        "timetable_rooms",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="sophikron",
    )
    op.add_column(
        "timetable_rooms", sa.Column("revision", sa.String(32), nullable=True), schema="sophikron"
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE sophikron.timetable_rooms SET revision=md5(id::text || clock_timestamp()::text)"
        )
    )
    op.alter_column("timetable_rooms", "revision", nullable=False, schema="sophikron")
    op.create_table(
        "timetable_school_years",
        sa.Column("school_year", sa.Integer(), primary_key=True),
        sa.Column("settings", JSONB(none_as_null=True)),
        sa.Column("revision", sa.String(32), nullable=False),
        schema="sophikron",
    )
    grouped: dict[int, list[dict]] = {}
    for year, settings in connection.execute(
        sa.text("SELECT school_year, settings FROM sophikron.timetable_years")
    ):
        grouped.setdefault(year, []).append(settings)
    table = sa.table(
        "timetable_school_years",
        sa.column("school_year"),
        sa.column("settings", JSONB(none_as_null=True)),
        sa.column("revision"),
        schema="sophikron",
    )
    for year, settings in grouped.items():
        shared = settings[0] if all(item == settings[0] for item in settings) else None
        connection.execute(
            table.insert().values(school_year=year, settings=shared, revision=uuid4().hex)
        )
    op.create_foreign_key(
        "fk_timetable_years_school_year_timetable_school_years",
        "timetable_years",
        "timetable_school_years",
        ["school_year"],
        ["school_year"],
        source_schema="sophikron",
        referent_schema="sophikron",
    )
    op.create_table(
        "timetable_template_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("year_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("blocks", JSONB(), nullable=False),
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


def downgrade() -> None:
    """Remove workspace metadata while retaining the original timetable tables and snapshots."""
    op.drop_table("timetable_template_versions", schema="sophikron")
    op.drop_constraint(
        "fk_timetable_years_school_year_timetable_school_years",
        "timetable_years",
        schema="sophikron",
        type_="foreignkey",
    )
    op.drop_table("timetable_school_years", schema="sophikron")
    for column in ("is_active", "revision"):
        op.drop_column("timetable_rooms", column, schema="sophikron")
    for column in ("is_paused", "is_deleted"):
        op.drop_column("timetable_calendars", column, schema="sophikron")
