"""Create the subject catalogue and staff subject assignments."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_subjects"
down_revision: str = "0003_promotions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create subject identities and their explicit account associations."""
    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False, unique=True),
        sa.Column("icon", sa.String(32), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_subjects_name")),
        sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f("ck_subjects_color")),
        schema="sophikron",
    )
    op.create_table(
        "teacher_subjects",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_teacher_subjects_subject_id", "teacher_subjects", ["subject_id"], schema="sophikron"
    )


def downgrade() -> None:
    """Remove subject assignments before their catalogue."""
    op.drop_table("teacher_subjects", schema="sophikron")
    op.drop_table("subjects", schema="sophikron")
