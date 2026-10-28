"""Persist custom audience bubbles alongside standard promotion partitions."""

import sqlalchemy as sa
from alembic import op

revision = "0013_custom_group_positions"
down_revision = "0012_timetable_audiences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add bounded positions and arrange existing groups beside the full-class source."""
    op.add_column(
        "promotion_custom_groups",
        sa.Column("x", sa.Integer(), nullable=False, server_default="320"),
        schema="sophikron",
    )
    op.add_column(
        "promotion_custom_groups",
        sa.Column("y", sa.Integer(), nullable=False, server_default="20"),
        schema="sophikron",
    )
    op.execute("""
        WITH positions AS (
            SELECT id, row_number() OVER (PARTITION BY promotion_id ORDER BY name, id) - 1 AS n
            FROM sophikron.promotion_custom_groups
        )
        UPDATE sophikron.promotion_custom_groups AS groups
        SET x = 320 + (positions.n % 3) * 300, y = (positions.n / 3) * 350 + 20
        FROM positions WHERE groups.id = positions.id
    """)
    op.create_check_constraint(
        "position",
        "promotion_custom_groups",
        "x BETWEEN 0 AND 1000000 AND y BETWEEN 0 AND 1000000",
        schema="sophikron",
    )


def downgrade() -> None:
    """Drop layout fields without altering custom names or audience membership."""
    op.drop_constraint(
        op.f("ck_promotion_custom_groups_position"),
        "promotion_custom_groups",
        schema="sophikron",
        type_="check",
    )
    op.drop_column("promotion_custom_groups", "y", schema="sophikron")
    op.drop_column("promotion_custom_groups", "x", schema="sophikron")
