"""Consolidated kholloscope preparation, durable drafts and administrator capabilities.

This unreleased baseline replaces the former 0008 through 0014 revisions.
Apply it to a fresh database or one still at 0007; never stamp an old schema to match it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_kholloscope"
down_revision = "0007_timetable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create annual preparation and private jobs while preserving live timetable series."""
    op.add_column(
        "timetable_calendars",
        sa.Column("kholle_settings", postgresql.JSONB(), nullable=True),
        schema="sophikron",
    )
    op.add_column(
        "timetable_school_years",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        schema="sophikron",
    )
    op.alter_column(
        "timetable_school_years",
        "created_at",
        schema="sophikron",
        server_default=sa.text("clock_timestamp()"),
    )
    op.create_table(
        "kholle_wishes",
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("sessions", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("school_year", "user_id", "subject_id"),
        sa.CheckConstraint("sessions BETWEEN 0 AND 1000", name=op.f("ck_kholle_wishes_sessions")),
        sa.ForeignKeyConstraint(
            ["school_year"], ["sophikron.timetable_school_years.school_year"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sophikron.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["sophikron.subjects.id"], ondelete="RESTRICT"),
        schema="sophikron",
    )
    for name in ("kholle_max_hours", "kholle_min_hours"):
        op.drop_constraint(
            op.f(f"ck_teacher_availability_{name}"),
            "teacher_availability",
            type_="check",
            schema="sophikron",
        )
    for name in ("kholle_min_hours", "kholle_max_hours"):
        op.drop_column("teacher_availability", name, schema="sophikron")
    op.create_table(
        "kholloscope_workflows",
        sa.Column("school_year", sa.Integer(), primary_key=True),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["school_year"], ["sophikron.timetable_school_years.school_year"], ondelete="CASCADE"
        ),
        schema="sophikron",
    )
    op.add_column(
        "timetable_rooms",
        sa.Column("kholle_capacity", sa.Integer(), nullable=False, server_default="1"),
        schema="sophikron",
    )
    op.create_check_constraint(
        op.f("ck_timetable_rooms_kholle_capacity"),
        "timetable_rooms",
        "kholle_capacity BETWEEN 0 AND 100",
        schema="sophikron",
    )
    op.create_table(
        "kholloscope_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("school_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source_revision", sa.String(64), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("logs", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["school_year"], ["sophikron.timetable_school_years.school_year"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','infeasible',"
            "'timeout','failed','cancelled')",
            name="run_status",
        ),
        schema="sophikron",
    )
    op.create_index(
        "ix_kholloscope_runs_year_created",
        "kholloscope_runs",
        ["school_year", "created_at"],
        schema="sophikron",
    )
    op.create_index(
        "uq_kholloscope_active_run",
        "kholloscope_runs",
        ["school_year"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
        schema="sophikron",
    )
    for code in ("kholloscope.read", "kholloscope.write"):
        op.execute(
            sa.text(
                "INSERT INTO sophikron.permissions (code, description) VALUES (:code, :code) "
                "ON CONFLICT (code) DO NOTHING"
            ).bindparams(code=code)
        )
        op.execute(
            sa.text(
                "INSERT INTO sophikron.role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM sophikron.roles r CROSS JOIN sophikron.permissions p "
                "WHERE r.code = 'admin' AND p.code = :code ON CONFLICT DO NOTHING"
            ).bindparams(code=code)
        )


def downgrade() -> None:
    """Remove kholloscope storage and restore the 0007 availability contract."""
    op.execute(
        "DELETE FROM sophikron.permissions WHERE code IN ('kholloscope.read', 'kholloscope.write')"
    )
    op.drop_table("kholloscope_runs", schema="sophikron")
    op.drop_constraint(
        op.f("ck_timetable_rooms_kholle_capacity"),
        "timetable_rooms",
        type_="check",
        schema="sophikron",
    )
    op.drop_column("timetable_rooms", "kholle_capacity", schema="sophikron")
    op.drop_table("kholloscope_workflows", schema="sophikron")
    for name in ("kholle_min_hours", "kholle_max_hours"):
        op.add_column(
            "teacher_availability",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
            schema="sophikron",
        )
    op.create_check_constraint(
        op.f("ck_teacher_availability_kholle_min_hours"),
        "teacher_availability",
        "kholle_min_hours >= 0",
        schema="sophikron",
    )
    op.create_check_constraint(
        op.f("ck_teacher_availability_kholle_max_hours"),
        "teacher_availability",
        "kholle_max_hours >= kholle_min_hours",
        schema="sophikron",
    )
    op.drop_table("kholle_wishes", schema="sophikron")
    op.drop_column("timetable_school_years", "created_at", schema="sophikron")
    op.drop_column("timetable_calendars", "kholle_settings", schema="sophikron")
