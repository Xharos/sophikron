"""Allow titled timetable events without a subject, teacher or room assignment."""

import sqlalchemy as sa
from alembic import op

revision = "0010_timetable_optional_fields"
down_revision = "0009_timetable_instants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Permit null references while retaining existing records and foreign keys."""
    for column in ("subject_id", "teacher_id", "room_id"):
        op.alter_column(
            "timetable_series",
            column,
            existing_type=sa.BigInteger(),
            nullable=True,
            schema="sophikron",
        )


def downgrade() -> None:
    """Restore required references, failing transactionally if unassigned events remain."""
    for column in ("subject_id", "teacher_id", "room_id"):
        op.alter_column(
            "timetable_series",
            column,
            existing_type=sa.BigInteger(),
            nullable=False,
            schema="sophikron",
        )
