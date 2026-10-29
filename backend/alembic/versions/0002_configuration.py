"""Create site configuration, shared calendar events and bounded API monitoring."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_configuration"
down_revision: str = "0001_authentication"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create settings, public calendars and independent minute/category API aggregates."""
    op.create_table(
        "site_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), server_default="Sophikron", nullable=False),
        sa.Column("home_text", sa.Text(), server_default="", nullable=False),
        sa.Column("text_color", sa.String(7), server_default="#244BC1", nullable=False),
        sa.Column("holiday_color", sa.String(7), server_default="#244BC1", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_site_settings_singleton")),
        sa.CheckConstraint(
            "holiday_color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_site_settings_holiday_color")
        ),
        schema="sophikron",
    )
    op.execute("INSERT INTO sophikron.site_settings (id) VALUES (1)")
    for table in ("timelines", "timeline_events"):
        columns = [
            sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("starts_on", sa.Date(), nullable=False),
            sa.Column("ends_on", sa.Date(), nullable=False),
            sa.Column("color", sa.String(7), nullable=False),
            sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
            sa.CheckConstraint("ends_on >= starts_on", name=op.f(f"ck_{table}_period")),
        ]
        if table == "timeline_events":
            columns.append(sa.Column("kind", sa.String(16), nullable=False))
        op.create_table(table, *columns, schema="sophikron")
    op.create_table(
        "timeline_event_bars",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.timeline_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "timeline_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.timelines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_timeline_event_bars_timeline_id",
        "timeline_event_bars",
        ["timeline_id"],
        schema="sophikron",
    )

    columns = [
        sa.Column(name, sa.BigInteger(), nullable=False)
        for name in (
            "requests",
            "duration_us",
            "max_us",
            "successes",
            "redirects",
            "client_errors",
            "server_errors",
            "incomplete",
            "ics_refused",
        )
    ]
    op.create_table(
        "api_metrics",
        sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("category", sa.String(24), primary_key=True),
        *columns,
        sa.Column("statuses", postgresql.JSONB(), nullable=False),
        sa.Column("histogram", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "category IN ('auth','timetable_read','timetable_check','timetable_write',"
            "'ics','administration','documents','statistics','other')",
            name="category",
        ),
        sa.CheckConstraint("requests >= 0 AND duration_us >= 0 AND max_us >= 0", name="counts"),
        schema="sophikron",
    )


def downgrade() -> None:
    """Remove API measurements and calendar associations before events and settings."""
    op.drop_table("api_metrics", schema="sophikron")
    op.drop_table("timeline_event_bars", schema="sophikron")
    op.drop_table("timeline_events", schema="sophikron")
    op.drop_table("timelines", schema="sophikron")
    op.drop_table("site_settings", schema="sophikron")
