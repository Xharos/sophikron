"""Application-scoped asynchronous PostgreSQL engines and request-scoped sessions."""

import asyncio
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import DatabaseSettings


class Base(DeclarativeBase):
    """Shared metadata for application models and Alembic migrations."""

    metadata = MetaData(
        schema="sophikron",
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


def build_engine(settings: DatabaseSettings, *, pooled: bool = True) -> AsyncEngine:
    """Build an engine without connecting to PostgreSQL.

    Parameters
    ----------
    settings
        Validated connection, pool and timeout settings.
    pooled
        Disable connection reuse for migration commands.

    Returns
    -------
    AsyncEngine
        A psycopg asynchronous engine owned by the caller.
    """
    connect_args: dict[str, object] = {
        "connect_timeout": settings.connect_timeout,
        "sslmode": settings.sslmode,
        "target_session_attrs": settings.target_session_attrs,
        "application_name": "sophikron",
        "options": (
            f"-c statement_timeout={settings.statement_timeout_ms} "
            f"-c lock_timeout={settings.lock_timeout_ms} "
            f"-c idle_in_transaction_session_timeout={settings.idle_transaction_timeout_ms} "
            "-c search_path=pg_catalog"
        ),
    }
    if settings.sslrootcert is not None:
        connect_args["sslrootcert"] = str(settings.sslrootcert)
    common = {"connect_args": connect_args, "hide_parameters": True, "echo": False}
    if not pooled:
        return create_async_engine(settings.url, poolclass=NullPool, **common)
    return create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout,
        pool_recycle=settings.pool_recycle,
        pool_pre_ping=True,
        **common,
    )


class Database:
    """Own one engine and session factory per application process."""

    def __init__(self, settings: DatabaseSettings) -> None:
        """Initialize resources from validated settings without a network connection."""
        self.engine = build_engine(settings)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.health_timeout = settings.health_timeout

    async def check_health(self) -> None:
        """Check connectivity within a bounded deadline; propagate database errors."""
        async with asyncio.timeout(self.health_timeout):
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        """Release the pool when the owning application shuts down."""
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    """Return the database resource initialized by the application lifespan."""
    return cast(Database, request.app.state.database)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield an isolated session; services must explicitly delimit transactions.

    Parameters
    ----------
    request
        Request belonging to the application that owns the engine.

    Yields
    ------
    AsyncSession
        A session closed on completion, error or cancellation, without implicit commit.
    """
    async with get_database(request).sessions() as session:
        yield session
