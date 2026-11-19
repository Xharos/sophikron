"""Add the private question bank and versioned course quizzes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_quiz_bank"
down_revision = "0009_curricula"
branch_labels = None
depends_on = None

SCHEMA = "sophikron"


def _replace_element_constraints(*, quiz: bool) -> None:
    """Replace the element type, dates and content checks together.

    Parameters
    ----------
    quiz
        Whether to permit quiz blocks.
    """
    table = "lesson_elements"
    for name in ("kind", "resource_dates", "content"):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, schema=SCHEMA, type_="check")
    extra = ", 'quiz'" if quiz else ""
    checks = {
        "kind": f"kind IN ('section', 'subsection', 'text', 'youtube', 'file', 'table'{extra})",
        "resource_dates": (
            f"kind IN ('file', 'youtube'{extra}) OR "
            "(schedule_mode = 'inherit' AND starts_on IS NULL AND ends_on IS NULL)"
        ),
        "content": (
            f"(kind IN ('section', 'subsection', 'table', 'file'{extra}) "
            "AND length(btrim(title)) > 0 AND body = '') OR "
            "(kind IN ('text', 'youtube') AND length(btrim(body)) > 0)"
        ),
    }
    for name, condition in checks.items():
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition, schema=SCHEMA)


def _replace_parent_check(*, quiz: bool) -> None:
    """Update allowed cell kinds while preserving hierarchy and coordinate checks.

    Parameters
    ----------
    quiz
        Whether to permit quiz blocks.
    """
    extra = ", 'quiz'" if quiz else ""
    op.execute(f"""
        CREATE OR REPLACE FUNCTION sophikron.check_lesson_parent() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE parent_kind text; parent_rows integer; parent_columns integer;
        BEGIN
            IF TG_OP = 'UPDATE' AND (NEW.kind, NEW.parent_id, NEW.lesson_id)
                IS DISTINCT FROM (OLD.kind, OLD.parent_id, OLD.lesson_id) THEN
                RAISE EXCEPTION 'Element structure is immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.parent_id IS NOT NULL THEN
                SELECT kind, table_rows, jsonb_array_length(table_columns)
                INTO parent_kind, parent_rows, parent_columns FROM sophikron.lesson_elements
                WHERE id = NEW.parent_id AND lesson_id = NEW.lesson_id;
                IF parent_kind IS NULL OR parent_kind NOT IN ('section', 'subsection', 'table')
                    OR (NEW.kind = 'subsection' AND parent_kind <> 'section') THEN
                    RAISE EXCEPTION 'Invalid lesson parent' USING ERRCODE = '23514';
                END IF;
                IF parent_kind = 'table' THEN
                    IF NEW.kind NOT IN ('text', 'youtube', 'file'{extra}) OR NEW.row_index IS NULL
                        OR NEW.column_index IS NULL OR NEW.row_index >= parent_rows
                        OR NEW.column_index >= parent_columns THEN
                        RAISE EXCEPTION 'Invalid table cell' USING ERRCODE = '23514';
                    END IF;
                ELSIF NEW.row_index IS NOT NULL OR NEW.column_index IS NOT NULL THEN
                    RAISE EXCEPTION 'Unexpected cell coordinates' USING ERRCODE = '23514';
                END IF;
            ELSIF NEW.row_index IS NOT NULL OR NEW.column_index IS NOT NULL THEN
                RAISE EXCEPTION 'Unexpected root coordinates' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
    """)


def upgrade() -> None:
    """Create the question bank, course quiz versions and first passages."""
    op.create_table(
        "quiz_questions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("statement", sa.String(4000), nullable=False, server_default=""),
        sa.Column("prompt", sa.String(4000), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("rule", postgresql.JSONB(), nullable=False),
        sa.Column("image", sa.Text()),
        sa.Column("image_alt", sa.String(300), nullable=False, server_default=""),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("length(btrim(title)) > 0", name="title"),
        sa.CheckConstraint("length(btrim(prompt)) > 0", name="prompt"),
        sa.CheckConstraint("kind IN ('choice', 'number', 'text')", name="kind"),
        schema=SCHEMA,
    )
    op.create_index("ix_quiz_questions_subject_id", "quiz_questions", ["subject_id"], schema=SCHEMA)
    op.create_table(
        "quiz_question_competencies",
        sa.Column(
            "question_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.quiz_questions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "competency_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.competencies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_quiz_question_competencies_competency_id",
        "quiz_question_competencies",
        ["competency_id"],
        schema=SCHEMA,
    )
    _replace_element_constraints(quiz=True)
    _replace_parent_check(quiz=True)
    op.create_table(
        "lesson_quiz_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "element_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.lesson_elements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refs", postgresql.JSONB(), nullable=False),
        sa.Column("cards", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("element_id", "id"),
        sa.CheckConstraint("jsonb_array_length(refs) BETWEEN 1 AND 50", name="size"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_lesson_quiz_versions_element_id", "lesson_quiz_versions", ["element_id"], schema=SCHEMA
    )
    op.create_table(
        "lesson_quiz_passages",
        sa.Column("element_id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version_id", sa.BigInteger(), nullable=False),
        sa.Column("card_order", postgresql.JSONB(), nullable=False),
        sa.Column("trials", postgresql.JSONB(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["element_id", "version_id"],
            ["sophikron.lesson_quiz_versions.element_id", "sophikron.lesson_quiz_versions.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "position >= 0 AND position <= jsonb_array_length(card_order)", name="position"
        ),
        sa.CheckConstraint(
            "jsonb_array_length(card_order) = jsonb_array_length(trials)", name="trial_count"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_lesson_quiz_passages_user_id", "lesson_quiz_passages", ["user_id"], schema=SCHEMA
    )


def downgrade() -> None:
    """Restore the previous lesson rules and remove quiz data."""
    _replace_element_constraints(quiz=False)
    _replace_parent_check(quiz=False)
    op.drop_table("lesson_quiz_passages", schema=SCHEMA)
    op.drop_table("lesson_quiz_versions", schema=SCHEMA)
    op.drop_table("quiz_question_competencies", schema=SCHEMA)
    op.drop_table("quiz_questions", schema=SCHEMA)
