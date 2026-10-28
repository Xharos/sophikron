"""Retain precise weekly version activation instants alongside their civil dates."""

import sqlalchemy as sa
from alembic import op

revision = "0009_timetable_instants"
down_revision = "0008_timetable_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add activation instants and interpret existing dates as midnight in Paris."""
    op.add_column(
        "timetable_template_versions",
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        schema="sophikron",
    )
    op.execute(
        "UPDATE sophikron.timetable_template_versions "
        "SET effective_at = effective_on::timestamp AT TIME ZONE 'Europe/Paris'"
    )


def downgrade() -> None:
    """Keep version dates and contents when removing the finer activation metadata."""
    op.drop_column("timetable_template_versions", "effective_at", schema="sophikron")
