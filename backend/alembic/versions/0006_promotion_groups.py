"""Add independent promotion partitions without changing existing memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0006_promotion_groups"
down_revision = "0005_lessons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create versioned partitions, positioned bubbles and unique pupil assignments."""
    op.create_table(
        "promotion_partitions",
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("target_size", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("promotion_id", "kind"),
        sa.ForeignKeyConstraint(["promotion_id"], ["sophikron.promotions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('halves', 'thirds', 'kholles')", name=op.f("ck_promotion_partitions_kind")
        ),
        sa.CheckConstraint(
            "target_size BETWEEN 2 AND 5", name=op.f("ck_promotion_partitions_target_size")
        ),
        schema="sophikron",
    )
    op.create_table(
        "promotion_groups",
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("x", sa.Integer(), nullable=False),
        sa.Column("y", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("promotion_id", "kind", "number"),
        sa.ForeignKeyConstraint(
            ["promotion_id", "kind"],
            ["sophikron.promotion_partitions.promotion_id", "sophikron.promotion_partitions.kind"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("number BETWEEN 1 AND 1000", name=op.f("ck_promotion_groups_number")),
        sa.CheckConstraint(
            "x BETWEEN 0 AND 1000000 AND y BETWEEN 0 AND 1000000",
            name=op.f("ck_promotion_groups_position"),
        ),
        schema="sophikron",
    )
    op.create_table(
        "promotion_group_members",
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("promotion_id", "kind", "user_id"),
        sa.ForeignKeyConstraint(
            ["promotion_id", "kind", "group_number"],
            [
                "sophikron.promotion_groups.promotion_id",
                "sophikron.promotion_groups.kind",
                "sophikron.promotion_groups.number",
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
        "ix_promotion_group_members_user_id",
        "promotion_group_members",
        ["user_id"],
        schema="sophikron",
    )


def downgrade() -> None:
    """Remove only group assignments and partitions, preserving promotions and pupils."""
    op.drop_table("promotion_group_members", schema="sophikron")
    op.drop_table("promotion_groups", schema="sophikron")
    op.drop_table("promotion_partitions", schema="sophikron")
