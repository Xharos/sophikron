"""Integration tests against the full services with an explicitly selected test database."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy import Column, Identity, Integer, MetaData, String, Table, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.config import DatabaseSettings
from app.core.database import Database, get_db
from app.main import create_app
from app.models import Promotion, PromotionGroup, PromotionPartition, TimetablePreferences
from tests.postgres import run_alembic

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("migrated_database"),
    pytest.mark.skipif(
        os.environ.get("DB_INTEGRATION") != "1", reason="Configure the dedicated test database"
    ),
]


@pytest_asyncio.fixture
async def databases(migrated_database: None) -> AsyncIterator[tuple[Database, Database]]:
    """Own application and migration engines for one test and release both pools."""
    application = Database(DatabaseSettings())
    migration = Database(
        DatabaseSettings(
            user="sophikron_migrator",
            password_file=Path(os.environ["DB_TEST_MIGRATION_PASSWORD_FILE"]),
        )
    )
    try:
        yield application, migration
    finally:
        try:
            await application.close()
        finally:
            await migration.close()


@pytest_asyncio.fixture
async def records(databases: tuple[Database, Database]) -> AsyncIterator[Table]:
    """Create and remove a uniquely named table only for tests that need stored data."""
    _, migration = databases
    metadata = MetaData(schema="sophikron")
    table = Table(
        f"test_{uuid4().hex}",
        metadata,
        Column("id", Integer, Identity(), primary_key=True),
        Column("value", String, unique=True, nullable=False),
    )
    try:
        async with migration.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        yield table
    finally:
        async with migration.engine.begin() as connection:
            await connection.run_sync(metadata.drop_all)


@pytest.fixture
def database_request(databases: tuple[Database, Database]) -> Request:
    """Provide a request using the actual application session dependency."""
    application = create_app()
    application.state.database = databases[0]
    return Request({"type": "http", "app": application})


def test_migration_roundtrip(migrated_database: None) -> None:
    """Smoke-test migration rollback, reapplication and final metadata consistency."""
    run_alembic("downgrade", "base")
    run_alembic("upgrade", "head")
    run_alembic("check")


@pytest.mark.asyncio
async def test_timetable_migration_roundtrip_preserves_partitions(
    databases: tuple[Database, Database],
) -> None:
    """Rollback timetable storage without removing prior promotion and partition data."""
    _, migration = databases
    timetable_tables = {
        "timetable_calendars",
        "timetable_rooms",
        "timetable_school_years",
        "teacher_availability",
        "timetable_years",
        "timetable_series",
        "timetable_subscriptions",
        "promotion_custom_groups",
        "promotion_custom_group_members",
        "timetable_preferences",
    }
    async with migration.sessions.begin() as session:
        promotion_id = await session.scalar(
            Promotion.__table__.insert()
            .values(year=2026, identifier=f"migration-{uuid4().hex}", color="#244BC1")
            .returning(Promotion.id)
        )
        await session.execute(
            PromotionPartition.__table__.insert().values(
                promotion_id=promotion_id, kind="halves", revision=uuid4().hex, target_size=3
            )
        )
        await session.execute(
            PromotionGroup.__table__.insert().values(
                promotion_id=promotion_id, kind="halves", number=1, x=123, y=456
            )
        )
    try:
        run_alembic("downgrade", "0006_promotion_groups")
        async with migration.sessions() as session:
            tables = set(
                await session.scalars(
                    text(
                        "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'sophikron'"
                    )
                )
            )
            assert timetable_tables.isdisjoint(tables)
            assert {"promotion_partitions", "promotion_groups", "promotion_group_members"} <= tables
            assert await session.scalar(select(Promotion.id).where(Promotion.id == promotion_id))
            assert (
                await session.execute(
                    select(PromotionGroup.x, PromotionGroup.y).where(
                        PromotionGroup.promotion_id == promotion_id
                    )
                )
            ).one() == (123, 456)
    finally:
        run_alembic("upgrade", "head")
        async with migration.sessions.begin() as session:
            await session.execute(Promotion.__table__.delete().where(Promotion.id == promotion_id))
    async with migration.sessions() as session:
        tables = set(
            await session.scalars(
                text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'sophikron'")
            )
        )
        assert timetable_tables <= tables
        assert "timetable_template_versions" not in tables
        preference = await session.get(TimetablePreferences, 1)
        assert preference is not None and preference.auto_archive
        assert len(preference.revision) == 32
    run_alembic("check")


def test_running_api() -> None:
    """Verify the root and readiness JSON responses of the running API."""
    base_url = os.environ["DB_TEST_API_URL"]
    for path, expected in (
        ("/api/v1", {"message": "Welcome to Sophikron API"}),
        ("/health", {"status": "ok", "database": "connected"}),
    ):
        with urlopen(base_url + path, timeout=5) as response:
            assert response.status == 200
            assert json.load(response) == expected


@pytest.mark.asyncio
async def test_commit_and_parameters(databases: tuple[Database, Database], records: Table) -> None:
    """Commit application DML and treat SQL-looking input as a bound value."""
    application, _ = databases
    table = records
    value = "O'Reilly'); DROP SCHEMA sophikron CASCADE; --"
    async with application.sessions.begin() as session:
        identifier = await session.scalar(table.insert().values(value=value).returning(table.c.id))
    async with application.sessions.begin() as session:
        assert await session.scalar(select(table.c.value).where(table.c.id == identifier)) == value
        await session.execute(
            table.update().where(table.c.id == identifier).values(value="changed")
        )
    async with application.sessions.begin() as session:
        updated = await session.scalar(select(table.c.value).where(table.c.id == identifier))
        assert updated == "changed"
        await session.execute(table.delete().where(table.c.id == identifier))
    async with application.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.asyncio
async def test_transaction_rollback(databases: tuple[Database, Database], records: Table) -> None:
    """Roll back the entire operation on constraint failure and permit subsequent transactions."""
    application, _ = databases
    table = records
    async with application.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(table.insert().values(value="duplicate"))
                await session.execute(table.insert().values(value="duplicate"))
        async with session.begin():
            assert await session.scalar(select(func.count()).select_from(table)) == 0
            await session.execute(table.insert().values(value="recovered"))
    async with application.sessions() as session:
        assert (await session.scalars(select(table.c.value))).all() == ["recovered"]


@pytest.mark.asyncio
async def test_request_session_isolation_and_rollback(
    databases: tuple[Database, Database],
    records: Table,
    database_request: Request,
) -> None:
    """Isolate uncommitted writes and roll them back when the real request dependency closes."""
    application, _ = databases
    async with aclosing(get_db(database_request)) as dependency:
        session = await anext(dependency)
        await session.execute(records.insert().values(value="uncommitted"))
        async with application.sessions() as observer:
            assert await observer.scalar(select(func.count()).select_from(records)) == 0
    async with application.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(records)) == 0
    assert application.engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_cancelled_transaction(
    databases: tuple[Database, Database],
    records: Table,
    database_request: Request,
) -> None:
    """Release the connection and roll back writes when a request task is cancelled."""
    application, _ = databases
    inserted = asyncio.Event()

    async def work() -> None:
        """Pause an open transaction after writing a row."""
        async with aclosing(get_db(database_request)) as dependency:
            session = await anext(dependency)
            async with session.begin():
                await session.execute(records.insert().values(value="cancelled"))
                inserted.set()
                await asyncio.Event().wait()

    task = asyncio.create_task(work())
    try:
        await asyncio.wait_for(inserted.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with application.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(records)) == 0
    assert application.engine.pool.checkedout() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE sophikron.forbidden (id integer)",
        "CREATE TABLE public.forbidden (id integer)",
        "CREATE SCHEMA forbidden",
        "CREATE ROLE forbidden_role",
        "SET ROLE sophikron_migrator",
        "SELECT * FROM sophikron.alembic_version",
        "DELETE FROM sophikron.alembic_version",
    ],
)
async def test_application_permissions(
    databases: tuple[Database, Database],
    statement: str,
) -> None:
    """Deny runtime DDL, privilege escalation and access to migration tracking."""
    application, _ = databases
    async with application.sessions() as session:
        try:
            with pytest.raises(DBAPIError) as error:
                await session.execute(text(statement))
        finally:
            # Also undo accidental DDL if a permission regression lets a statement succeed.
            await session.rollback()
        assert error.value.orig.sqlstate == "42501"


@pytest.mark.asyncio
async def test_roles_are_not_administrators(databases: tuple[Database, Database]) -> None:
    """Keep both application and migration roles free of cluster administration powers."""
    application, migration = databases
    for database in (application, migration):
        async with database.sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
                        "FROM pg_catalog.pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
            assert not any(row)


@pytest.mark.asyncio
async def test_statement_timeout_and_recovery(migrated_database: None) -> None:
    """Cancel slow statements server-side and recover on a new transaction."""
    database = Database(DatabaseSettings(statement_timeout_ms=200))
    try:
        async with database.sessions() as session:
            with pytest.raises(DBAPIError) as error:
                async with session.begin():
                    await session.execute(text("SELECT pg_sleep(1)"))
            assert error.value.orig.sqlstate == "57014"
            async with session.begin():
                assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_pool_timeout(migrated_database: None) -> None:
    """Bound pool acquisition and recover after the held connection is returned."""
    database = Database(DatabaseSettings(pool_size=1, max_overflow=0, pool_timeout=0.1))
    try:
        async with database.engine.connect():
            with pytest.raises(PoolTimeoutError):
                async with database.engine.connect():
                    pytest.fail("Pool unexpectedly exceeded its configured limit")
        await database.check_health()
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_disconnected_idle_connection(databases: tuple[Database, Database]) -> None:
    """Replace a dead pooled connection before handing it to the next transaction."""
    application, _ = databases
    async with application.engine.connect() as connection:
        previous_pid = await connection.scalar(text("SELECT pg_backend_pid()"))
        driver_connection = (await connection.get_raw_connection()).driver_connection
    await driver_connection.close()
    async with application.engine.connect() as connection:
        assert await connection.scalar(text("SELECT pg_backend_pid()")) != previous_pid


@pytest.mark.asyncio
async def test_lock_timeout(databases: tuple[Database, Database], records: Table) -> None:
    """Bound lock contention independently from the statement execution timeout."""
    application, migration = databases
    table = records
    async with application.sessions.begin() as session:
        identifier = await session.scalar(
            table.insert().values(value="locked").returning(table.c.id)
        )
    limited = Database(DatabaseSettings(lock_timeout_ms=200))
    try:
        async with migration.sessions.begin() as holder:
            await holder.execute(select(table).where(table.c.id == identifier).with_for_update())
            async with limited.sessions() as session:
                with pytest.raises(DBAPIError) as error:
                    async with session.begin():
                        await session.execute(table.update().values(value="blocked"))
                assert error.value.orig.sqlstate == "55P03"
    finally:
        await limited.close()


@pytest.mark.asyncio
async def test_feature_migration_stages(databases: tuple[Database, Database]) -> None:
    """Create each feature only at its revision and enforce configuration constraints."""
    _, migration = databases
    try:
        run_alembic("downgrade", "0001_authentication")
        async with migration.sessions() as session:
            assert await session.scalar(text("SELECT to_regclass('sophikron.activity_events')"))
            assert await session.scalar(text("SELECT to_regclass('sophikron.api_metrics')")) is None
            assert (
                await session.scalar(text("SELECT to_regclass('sophikron.release_check')")) is None
            )
            assert (
                await session.scalar(text("SELECT to_regclass('sophikron.site_settings')")) is None
            )
        run_alembic("upgrade", "0002_configuration")
        async with migration.sessions() as session:
            assert await session.scalar(text("SELECT id FROM sophikron.release_check")) == 1
            assert await session.scalar(
                text("SELECT attempted_at FROM sophikron.release_check WHERE id = 1")
            ) is None
            assert await session.scalar(text("SELECT to_regclass('sophikron.api_metrics')"))
            assert (
                await session.scalar(text("SELECT to_regclass('sophikron.calendar_usage_totals')"))
                is None
            )
            assert (
                await session.scalar(
                    text("SELECT text_color FROM sophikron.site_settings WHERE id = 1")
                )
                == "#244BC1"
            )
            for name in (
                "promotions",
                "subjects",
                "lessons",
                "timelines",
                "timeline_events",
                "timeline_event_bars",
            ):
                assert (
                    await session.scalar(
                        text("SELECT to_regclass(:name)"), {"name": "sophikron." + name}
                    )
                    is None
                )
            assert (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'sophikron' AND table_name = 'site_settings' "
                        "AND column_name = 'holiday_color'"
                    )
                )
                == 0
            )
        run_alembic("upgrade", "0003_promotions")
        async with migration.sessions() as session:
            assert await session.scalar(text("SELECT to_regclass('sophikron.user_promotions')"))
            assert await session.scalar(text("SELECT to_regclass('sophikron.subjects')")) is None
        run_alembic("upgrade", "0004_subjects")
        async with migration.sessions() as session:
            assert await session.scalar(text("SELECT to_regclass('sophikron.teacher_subjects')"))
            assert await session.scalar(text("SELECT to_regclass('sophikron.lessons')")) is None
        run_alembic("upgrade", "0006_promotion_groups")
        async with migration.sessions() as session:
            assert (
                await session.scalar(
                    text("SELECT to_regclass('sophikron.timetable_subscriptions')")
                )
                is None
            )
        run_alembic("upgrade", "head")
        async with migration.sessions() as session:
            assert await session.scalar(
                text("SELECT to_regclass('sophikron.calendar_usage_totals')")
            )
            assert await session.scalar(
                text("""
                SELECT is_nullable = 'YES' FROM information_schema.columns
                WHERE table_schema = 'sophikron' AND table_name = 'teacher_availability'
                AND column_name = 'ranges'
            """)
            )
    finally:
        run_alembic("upgrade", "head")
