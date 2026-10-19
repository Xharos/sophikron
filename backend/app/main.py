"""FastAPI application lifecycle and infrastructure endpoints."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import DatabaseSettings
from app.core.database import Database, get_database

logger = logging.getLogger(__name__)


def create_app(settings: DatabaseSettings | None = None) -> FastAPI:
    """Create an application with independently owned database resources.

    Parameters
    ----------
    settings
        Optional settings override for tests; otherwise read at startup.

    Returns
    -------
    FastAPI
        The configured application, with no import-time database initialization.
    """

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Allocate database resources at startup and dispose them at shutdown."""
        database = Database(settings if settings is not None else DatabaseSettings())
        application.state.database = database
        try:
            yield
        finally:
            await database.close()
            del application.state.database

    application = FastAPI(
        title="Sophikron API",
        description="API for the Sophikron educational platform.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.get("/")(read_root)
    application.get("/health")(health_check)
    return application


async def read_root() -> dict[str, str]:
    """Return basic API information without requiring database availability."""
    return {"message": "Welcome to Sophikron API"}


async def health_check(database: Annotated[Database, Depends(get_database)]) -> dict[str, str]:
    """Return readiness or an anonymous 503 response when PostgreSQL is unavailable."""
    try:
        await database.check_health()
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.warning("PostgreSQL readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok", "database": "connected"}


app = create_app()
