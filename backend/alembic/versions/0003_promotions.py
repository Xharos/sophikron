"""Create promotions and role-independent memberships; prohibit application deletion."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_promotions"
down_revision: str = "0002_configuration"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the promotion catalogue and its account associations."""
    op.create_table(
        "promotions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(64), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_promotions")),
        sa.UniqueConstraint("year", "identifier", name=op.f("uq_promotions_year")),
        sa.CheckConstraint("year BETWEEN 1 AND 9999", name=op.f("ck_promotions_year")),
        sa.CheckConstraint(
            "identifier = btrim(identifier) AND length(identifier) > 0",
            name=op.f("ck_promotions_identifier"),
        ),
        sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_promotions_color")),
        schema="sophikron",
    )
    for column in ("year", "is_active"):
        op.create_index(op.f(f"ix_promotions_{column}"), "promotions", [column], schema="sophikron")
    op.create_table(
        "user_promotions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", "promotion_id", name=op.f("pk_user_promotions")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            ondelete="CASCADE",
            name=op.f("fk_user_promotions_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"],
            ["sophikron.promotions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_user_promotions_promotion_id_promotions"),
        ),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_user_promotions_promotion_id"),
        "user_promotions",
        ["promotion_id"],
        schema="sophikron",
    )
    op.create_table(
        "promotion_account_blocks",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "user_id", "promotion_id", name=op.f("pk_promotion_account_blocks")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["sophikron.users.id"],
            ondelete="CASCADE",
            name=op.f("fk_promotion_account_blocks_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id"],
            ["sophikron.promotions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_promotion_account_blocks_promotion_id_promotions"),
        ),
        schema="sophikron",
    )
    op.create_index(
        op.f("ix_promotion_account_blocks_promotion_id"),
        "promotion_account_blocks",
        ["promotion_id"],
        schema="sophikron",
    )
    op.execute("REVOKE DELETE ON sophikron.promotions FROM sophikron_app")


def downgrade() -> None:
    """Remove memberships before their catalogue; only the migration role can do this."""
    op.drop_table("promotion_account_blocks", schema="sophikron")
    op.drop_table("user_promotions", schema="sophikron")
    op.drop_table("promotions", schema="sophikron")
