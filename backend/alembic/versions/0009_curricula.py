"""Release baseline for curricula, competency DAGs, optional promotions and bounded undo."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_curricula"
down_revision = "0008_kholloscope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add programme storage without changing calendars or existing promotions."""
    op.create_table(
        "curricula",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source_url", sa.String(2000)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="title"),
        schema="sophikron",
    )
    op.create_table(
        "curriculum_subjects",
        sa.Column("curriculum_id", sa.BigInteger(), primary_key=True),
        sa.Column("subject_id", sa.BigInteger(), primary_key=True),
        sa.ForeignKeyConstraint(["curriculum_id"], ["sophikron.curricula.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["sophikron.subjects.id"], ondelete="RESTRICT"),
        schema="sophikron",
    )
    op.create_table(
        "competencies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("curriculum_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("semester", sa.Integer()),
        sa.Column("knowledge", sa.Text()),
        sa.Column("comment", sa.Text()),
        sa.Column("color", sa.String(7)),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["curriculum_id", "subject_id"],
            [
                "sophikron.curriculum_subjects.curriculum_id",
                "sophikron.curriculum_subjects.subject_id",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("curriculum_id", "subject_id", "id", name="uq_competency_scope"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name"),
        sa.CheckConstraint("semester BETWEEN 1 AND 4", name="semester"),
        sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color"),
        sa.CheckConstraint("position >= 0", name="position"),
        schema="sophikron",
    )
    op.create_index(
        "ix_competencies_curriculum_id", "competencies", ["curriculum_id"], schema="sophikron"
    )
    op.create_table(
        "competency_links",
        sa.Column("curriculum_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), primary_key=True),
        sa.Column("child_id", sa.BigInteger(), primary_key=True),
        *(
            sa.ForeignKeyConstraint(
                ["curriculum_id", "subject_id", endpoint],
                [
                    "sophikron.competencies.curriculum_id",
                    "sophikron.competencies.subject_id",
                    "sophikron.competencies.id",
                ],
                ondelete="CASCADE",
                name=f"fk_competency_links_{endpoint}",
            )
            for endpoint in ("parent_id", "child_id")
        ),
        sa.CheckConstraint("parent_id <> child_id", name="different_nodes"),
        schema="sophikron",
    )
    op.create_index(
        "ix_competency_links_child_id", "competency_links", ["child_id"], schema="sophikron"
    )
    op.add_column("promotions", sa.Column("curriculum_id", sa.BigInteger()), schema="sophikron")
    op.create_foreign_key(
        "fk_promotions_curriculum_id_curricula",
        "promotions",
        "curricula",
        ["curriculum_id"],
        ["id"],
        source_schema="sophikron",
        referent_schema="sophikron",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_promotions_curriculum_id", "promotions", ["curriculum_id"], schema="sophikron"
    )
    op.create_table(
        "curriculum_undo",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "curriculum_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.curricula.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("after_version", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        schema="sophikron",
    )

    for code, roles in (
        ("curricula.read", ("admin", "teacher", "kholleur")),
        ("curricula.edit", ("teacher",)),
        ("curricula.manage", ("admin",)),
    ):
        op.execute(
            sa.text(
                "INSERT INTO sophikron.permissions (code, description) VALUES (:c, :c)"
            ).bindparams(c=code)
        )
        for role in roles:
            op.execute(
                sa.text(
                    "INSERT INTO sophikron.role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM sophikron.roles r CROSS JOIN sophikron.permissions p "
                    "WHERE r.code = :r AND p.code = :c"
                ).bindparams(r=role, c=code)
            )


def downgrade() -> None:
    """Remove only programme storage and the optional promotion association."""
    op.execute("DELETE FROM sophikron.permissions WHERE code LIKE 'curricula.%'")
    op.drop_index("ix_promotions_curriculum_id", table_name="promotions", schema="sophikron")
    op.drop_constraint(
        "fk_promotions_curriculum_id_curricula",
        "promotions",
        schema="sophikron",
        type_="foreignkey",
    )
    op.drop_column("promotions", "curriculum_id", schema="sophikron")
    for table in (
        "curriculum_undo",
        "competency_links",
        "competencies",
        "curriculum_subjects",
        "curricula",
    ):
        op.drop_table(table, schema="sophikron")
