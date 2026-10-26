"""Add course pages, extensible content trees and revocable teaching/access associations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_lessons"
down_revision: str = "0004_subjects"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade_statistics() -> None:
    """Add only anonymous counters, also usable on an existing local 0005 installation."""
    op.create_table(
        "login_statistics",
        sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("failed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("limited", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "tracked_from", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("failed >= 0 AND limited >= 0", name=op.f("ck_login_statistics_counts")),
        schema="sophikron",
        if_not_exists=True,
    )
    op.execute("""INSERT INTO sophikron.login_statistics(bucket)
                  VALUES (date_trunc('hour', now(), 'UTC')) ON CONFLICT DO NOTHING""")


def upgrade_lesson_policies() -> None:
    """Normalize existing course policies without deleting content or recreating the database.

    Legacy private descendants promote their entire owning section to staff visibility.
    Obsolete structural dates and private-section resource dates are cleared transactionally.
    """
    op.execute("""
        LOCK TABLE sophikron.lessons, sophikron.lesson_elements IN SHARE ROW EXCLUSIVE MODE;
        WITH RECURSIVE tree AS (
            SELECT id, id AS root_id FROM sophikron.lesson_elements WHERE parent_id IS NULL
            UNION ALL
            SELECT child.id, tree.root_id FROM sophikron.lesson_elements child
            JOIN tree ON child.parent_id = tree.id
        ), private AS (
            SELECT DISTINCT tree.root_id FROM tree
            JOIN sophikron.lesson_elements e ON e.id = tree.id
            WHERE e.audience = 'staff'
        )
        UPDATE sophikron.lesson_elements SET audience = 'staff'
        WHERE id IN (SELECT root_id FROM private);
        WITH RECURSIVE tree AS (
            SELECT id, audience = 'staff' AS staff FROM sophikron.lesson_elements
            WHERE parent_id IS NULL
            UNION ALL
            SELECT child.id, tree.staff FROM sophikron.lesson_elements child
            JOIN tree ON child.parent_id = tree.id
        ), changed AS (
            UPDATE sophikron.lesson_elements e SET
                audience = CASE WHEN e.kind = 'section' THEN e.audience ELSE 'students' END,
                schedule_mode = CASE WHEN e.kind NOT IN ('file', 'youtube') OR tree.staff
                    THEN 'inherit' ELSE e.schedule_mode END,
                starts_on = CASE WHEN e.kind NOT IN ('file', 'youtube') OR tree.staff
                    THEN NULL ELSE e.starts_on END,
                ends_on = CASE WHEN e.kind NOT IN ('file', 'youtube') OR tree.staff
                    THEN NULL ELSE e.ends_on END
            FROM tree WHERE tree.id = e.id AND (
                (e.kind <> 'section' AND e.audience <> 'students') OR
                ((e.kind NOT IN ('file', 'youtube') OR tree.staff) AND e.schedule_mode <> 'inherit')
            ) RETURNING e.lesson_id
        )
        UPDATE sophikron.lessons SET version = version + 1, updated_at = now()
        WHERE id IN (SELECT lesson_id FROM changed);
        ALTER TABLE sophikron.lesson_elements
            DROP CONSTRAINT IF EXISTS ck_lesson_elements_section_audience;
        ALTER TABLE sophikron.lesson_elements ADD CONSTRAINT ck_lesson_elements_section_audience
            CHECK (kind = 'section' OR audience = 'students');
        ALTER TABLE sophikron.lesson_elements
            DROP CONSTRAINT IF EXISTS ck_lesson_elements_resource_dates;
        ALTER TABLE sophikron.lesson_elements ADD CONSTRAINT ck_lesson_elements_resource_dates
            CHECK (kind IN ('file', 'youtube') OR
                (schedule_mode = 'inherit' AND starts_on IS NULL AND ends_on IS NULL));
    """)


def upgrade() -> None:
    """Create course persistence without changing existing identities or applied migrations."""
    upgrade_statistics()
    op.create_table(
        "lessons",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "creator_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("title_key", sa.String(480), nullable=False, unique=True),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column(
            "subject_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.subjects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "responsible_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(btrim(title)) > 0", name=op.f("ck_lessons_title")),
        sa.CheckConstraint("version >= 0", name=op.f("ck_lessons_version")),
        schema="sophikron",
    )
    op.create_index("ix_lessons_creator_id", "lessons", ["creator_id"], schema="sophikron")
    op.create_index("ix_lessons_subject_id", "lessons", ["subject_id"], schema="sophikron")
    op.create_index("ix_lessons_responsible_id", "lessons", ["responsible_id"], schema="sophikron")
    op.create_table(
        "lesson_elements",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "lesson_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), server_default="", nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("schedule_mode", sa.String(16), server_default="inherit", nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("audience", sa.String(16), server_default="students", nullable=False),
        sa.Column("table_rows", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "table_columns", postgresql.JSONB(), server_default='["Colonne 1"]', nullable=False
        ),
        sa.Column("row_index", sa.Integer(), nullable=True),
        sa.Column("column_index", sa.Integer(), nullable=True),
        sa.UniqueConstraint("parent_id", "row_index", "column_index"),
        sa.UniqueConstraint("lesson_id", "id"),
        sa.ForeignKeyConstraint(
            ["lesson_id", "parent_id"],
            ["sophikron.lesson_elements.lesson_id", "sophikron.lesson_elements.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('section', 'subsection', 'text', 'youtube', 'file', 'table')",
            name=op.f("ck_lesson_elements_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'section') = (parent_id IS NULL)", name=op.f("ck_lesson_elements_root_section")
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_lesson_elements_position")),
        sa.CheckConstraint(
            "audience IN ('students', 'staff')", name=op.f("ck_lesson_elements_audience")
        ),
        sa.CheckConstraint(
            "table_rows BETWEEN 1 AND 20 AND jsonb_array_length(table_columns) BETWEEN 1 AND 6",
            name=op.f("ck_lesson_elements_table_dimensions"),
        ),
        sa.CheckConstraint(
            "(row_index IS NULL AND column_index IS NULL) OR "
            "(row_index IS NOT NULL AND column_index IS NOT NULL "
            "AND row_index BETWEEN 0 AND 19 AND column_index BETWEEN 0 AND 5)",
            name=op.f("ck_lesson_elements_cell_coordinates"),
        ),
        sa.CheckConstraint(
            "(schedule_mode = 'inherit' AND starts_on IS NULL AND ends_on IS NULL) OR "
            "(schedule_mode = 'from' AND starts_on IS NOT NULL AND ends_on IS NULL) OR "
            "(schedule_mode = 'range' AND starts_on IS NOT NULL AND ends_on IS NOT NULL "
            "AND ends_on >= starts_on)",
            name=op.f("ck_lesson_elements_schedule"),
        ),
        sa.CheckConstraint(
            "(kind IN ('section', 'subsection', 'table', 'file') "
            "AND length(btrim(title)) > 0 AND body = '') OR "
            "(kind IN ('text', 'youtube') AND length(btrim(body)) > 0)",
            name=op.f("ck_lesson_elements_content"),
        ),
        sa.CheckConstraint("length(body) <= 3000", name=op.f("ck_lesson_elements_body_length")),
        schema="sophikron",
    )
    for column in ("lesson_id", "parent_id"):
        op.create_index(
            f"ix_lesson_elements_{column}", "lesson_elements", [column], schema="sophikron"
        )
    op.create_table(
        "lesson_collaborators",
        sa.Column(
            "lesson_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.lessons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_lesson_collaborators_user_id", "lesson_collaborators", ["user_id"], schema="sophikron"
    )
    op.create_table(
        "lesson_promotions",
        sa.Column(
            "lesson_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.lessons.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "promotion_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.promotions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f("ck_lesson_promotions_period")),
        schema="sophikron",
    )
    op.create_index(
        "ix_lesson_promotions_promotion_id",
        "lesson_promotions",
        ["promotion_id"],
        schema="sophikron",
    )
    op.execute("""
        CREATE FUNCTION sophikron.check_lesson_parent() RETURNS trigger
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
                    IF NEW.kind NOT IN ('text', 'youtube', 'file') OR NEW.row_index IS NULL
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
        CREATE TRIGGER lesson_parent BEFORE INSERT OR UPDATE OF
            kind, parent_id, lesson_id, row_index, column_index
        ON sophikron.lesson_elements FOR EACH ROW EXECUTE FUNCTION sophikron.check_lesson_parent();
    """)
    op.create_table(
        "lesson_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("lesson_id", sa.BigInteger(), nullable=False),
        sa.Column("element_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column(
            "uploaded_by",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(32), nullable=False, unique=True),
        sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("extension", sa.String(8), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id", "element_id"],
            ["sophikron.lesson_elements.lesson_id", "sophikron.lesson_elements.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 52428800", name=op.f("ck_lesson_files_size")
        ),
        sa.CheckConstraint(
            "storage_key ~ '^[0-9a-f]{32}$' AND sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_lesson_files_digest_key"),
        ),
        schema="sophikron",
    )
    for column in ("lesson_id", "uploaded_by"):
        op.create_index(f"ix_lesson_files_{column}", "lesson_files", [column], schema="sophikron")
    op.create_table(
        "lesson_uploads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "lesson_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.lessons.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("sophikron.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema="sophikron",
    )
    for column in ("lesson_id", "user_id", "expires_at"):
        op.create_index(
            f"ix_lesson_uploads_{column}", "lesson_uploads", [column], schema="sophikron"
        )
    op.create_table(
        "lesson_file_deletions",
        sa.Column("storage_key", sa.String(32), primary_key=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="sophikron",
    )
    op.execute("""
        CREATE FUNCTION sophikron.queue_lesson_file_deletion() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            INSERT INTO sophikron.lesson_file_deletions(storage_key) VALUES (OLD.storage_key)
            ON CONFLICT DO NOTHING;
            RETURN OLD;
        END $$;
        CREATE TRIGGER lesson_file_cleanup AFTER DELETE ON sophikron.lesson_files
        FOR EACH ROW EXECUTE FUNCTION sophikron.queue_lesson_file_deletion();
    """)

    upgrade_lesson_policies()


def downgrade() -> None:
    """Remove course-owned data only when an operator explicitly downgrades this revision."""
    # Queue disk cleanup before removing file metadata; retain the queue until the worker drains it.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM sophikron.lesson_files")).scalar()
    queued = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM sophikron.lesson_file_deletions"))
        .scalar()
    )
    if count or queued:
        raise RuntimeError("Remove course files and drain document cleanup before downgrading 0005")
    op.drop_table("login_statistics", schema="sophikron")
    op.drop_table("lesson_uploads", schema="sophikron")
    op.drop_table("lesson_files", schema="sophikron")
    op.execute("DROP FUNCTION sophikron.queue_lesson_file_deletion()")
    op.drop_table("lesson_file_deletions", schema="sophikron")
    op.drop_table("lesson_promotions", schema="sophikron")
    op.drop_table("lesson_collaborators", schema="sophikron")
    op.drop_table("lesson_elements", schema="sophikron")
    op.execute("DROP FUNCTION sophikron.check_lesson_parent()")
    op.drop_table("lessons", schema="sophikron")
