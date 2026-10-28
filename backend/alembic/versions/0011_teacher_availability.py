"""Add annual teacher availability without changing existing agendas or publications."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_teacher_availability"
down_revision = "0010_timetable_optional_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create weekly patterns; absent rows mean all configured opening hours are available."""
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


def downgrade() -> None:
    """Remove only the availability patterns introduced by this revision."""
    op.drop_table("teacher_availability", schema="sophikron")
