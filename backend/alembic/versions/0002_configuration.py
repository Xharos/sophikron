"""Create public site settings, bounded API monitoring and the shared release cache."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_configuration"
down_revision: str = "0001_authentication"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create settings and independent minute/category API aggregates."""
    op.create_table(
        "site_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(100), server_default="Sophikron", nullable=False),
        sa.Column("home_text", sa.Text(), server_default="", nullable=False),
        sa.Column("text_color", sa.String(7), server_default="#244BC1", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_site_settings_singleton")),
        schema="sophikron",
    )
    op.execute("INSERT INTO sophikron.site_settings (id) VALUES (1)")

    release_check = op.create_table(
        "release_check",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.String(100)),
        sa.Column("release_url", sa.String(500)),
        sa.Column("error", sa.String(200)),
        sa.CheckConstraint("id = 1", name="singleton"),
        schema="sophikron",
    )
    op.bulk_insert(release_check, [{"id": 1}])

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
    """Remove API measurements and public settings."""
    op.drop_table("api_metrics", schema="sophikron")
    op.drop_table("release_check", schema="sophikron")
    op.drop_table("site_settings", schema="sophikron")
