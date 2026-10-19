"""Run explicit schema migrations with a dedicated, unpooled connection."""

import asyncio
import sys

from alembic import context
from sqlalchemy import Connection

from app import models  # noqa: F401 -- register future model imports in app.models
from app.core.config import DatabaseSettings
from app.core.database import Base, build_engine


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Inspect only the application schema; leave other schemas outside migration ownership."""
    return type_ != "schema" or name == "sophikron"


def configure_migrations(connection: Connection | None = None) -> None:
    """Configure metadata and protect Alembic's version table from the runtime role.

    Parameters
    ----------
    connection
        Online connection, or None when generating SQL offline.
    """
    options = {
        "target_metadata": Base.metadata,
        "include_schemas": True,
        "version_table_schema": "sophikron",
        "compare_type": True,
        "include_name": include_name,
    }
    if connection is None:
        context.configure(
            url=DatabaseSettings().url, literal_binds=True, dialect_opts={"paramstyle": "named"},
            **options,
        )
    else:
        context.configure(connection=connection, **options)
    with context.begin_transaction():
        context.run_migrations()
        context.execute(
            "REVOKE ALL ON TABLE sophikron.alembic_version FROM sophikron_app"
        )


async def run_online() -> None:
    """Run migrations and release the dedicated connection even on failure."""
    engine = build_engine(DatabaseSettings(), pooled=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(configure_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    configure_migrations()
else:
    # psycopg's asynchronous connections require a selector event loop on Windows.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(run_online())
