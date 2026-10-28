"""Add overlapping audiences, archive preferences and detached recurrence nodes."""

from uuid import NAMESPACE_URL, uuid4, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_timetable_audiences"
down_revision = "0011_teacher_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve calendars and convert old exception replacements to independent series."""
    op.create_table(
        "promotion_custom_groups",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_key", sa.String(300), nullable=False),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.ForeignKeyConstraint(["promotion_id"], ["sophikron.promotions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "promotion_id"),
        sa.UniqueConstraint("promotion_id", "name_key"),
        schema="sophikron",
    )
    op.create_index(
        "ix_promotion_custom_groups_promotion_id",
        "promotion_custom_groups",
        ["promotion_id"],
        schema="sophikron",
    )
    op.create_table(
        "promotion_custom_group_members",
        sa.Column("group_id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("promotion_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id", "promotion_id"],
            [
                "sophikron.promotion_custom_groups.id",
                "sophikron.promotion_custom_groups.promotion_id",
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
        "ix_promotion_custom_group_members_user_id",
        "promotion_custom_group_members",
        ["user_id"],
        schema="sophikron",
    )
    op.create_table(
        "timetable_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auto_archive", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_rollover_year", sa.Integer(), nullable=True),
        sa.Column("revision", sa.String(32), nullable=False),
        sa.CheckConstraint("id = 1", name="singleton"),
        schema="sophikron",
    )
    prefs = sa.table(
        "timetable_preferences",
        sa.column("id", sa.Integer()),
        sa.column("revision", sa.String()),
        schema="sophikron",
    )
    op.bulk_insert(prefs, [{"id": 1, "revision": uuid4().hex}])
    series = sa.table(
        "timetable_series",
        sa.column("id", sa.String()),
        sa.column("year_id", sa.BigInteger()),
        sa.column("subject_id", sa.BigInteger()),
        sa.column("teacher_id", sa.BigInteger()),
        sa.column("room_id", sa.BigInteger()),
        sa.column("data", JSONB()),
        schema="sophikron",
    )
    connection = op.get_bind()
    for row in list(connection.execute(sa.select(series)).mappings()):
        document = dict(row["data"])
        exceptions = dict(document.get("exceptions", {}))
        changed = False
        for day, block in list(exceptions.items()):
            if block is None:
                continue
            identifier = uuid5(NAMESPACE_URL, f"sophikron:{row['id']}:{day}").hex
            detached = {
                **block,
                "id": identifier,
                "lineage": identifier,
                "uid_lineage": document["lineage"],
                "uid_date": day,
                "interval": 0,
                "until": None,
                "exceptions": {},
            }
            connection.execute(
                series.insert().values(
                    id=identifier,
                    year_id=row["year_id"],
                    data=detached,
                    **{key: block.get(key) for key in ("subject_id", "teacher_id", "room_id")},
                )
            )
            exceptions[day], changed = None, True
        if changed:
            connection.execute(
                series.update()
                .where(series.c.id == row["id"])
                .values(data={**document, "exceptions": exceptions})
            )


def downgrade() -> None:
    """Refuse to discard named audiences still referenced by calendars."""
    used = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM sophikron.timetable_series "
            "WHERE data->>'target_kind' = 'custom')"
        )
    )
    if used:
        raise RuntimeError("Remove custom-group session assignments before downgrading.")
    op.execute(
        "UPDATE sophikron.timetable_series SET data = data - 'uid_lineage' - 'uid_date' "
        "WHERE data ? 'uid_lineage' OR data ? 'uid_date'"
    )
    op.drop_table("timetable_preferences", schema="sophikron")
    op.drop_table("promotion_custom_group_members", schema="sophikron")
    op.drop_table("promotion_custom_groups", schema="sophikron")
