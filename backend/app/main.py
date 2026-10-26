"""FastAPI application lifecycle and infrastructure endpoints."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint

from app.api.router import router
from app.core.auth_config import AuthSettings
from app.core.config import DatabaseSettings
from app.core.database import Database, get_database
from app.core.documents import DocumentSettings
from app.core.http import AuthRequestMiddleware, ConfiguredCORSMiddleware, SearchAccessLogFilter
from app.core.security import IdentityCipher, PasswordCapacityError, PasswordSecurity
from app.services.auth import AuthService
from app.services.document_storage import DocumentStorage, document_maintenance
from app.services.errors import INVALID_REQUEST, AuthError
from app.services.mail import DisabledMailer, InvitationMailer, SmtpMailer
from app.services.search import NameSearchCache

logger = logging.getLogger(__name__)


def create_app(
    settings: DatabaseSettings | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    mailer: InvitationMailer | None = None,
) -> FastAPI:
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

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, SearchAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(SearchAccessLogFilter())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Allocate database resources at startup and dispose them at shutdown."""
        authentication = auth_settings if auth_settings is not None else AuthSettings()
        cipher = IdentityCipher.from_file(authentication.keys_file)
        passwords = PasswordSecurity(authentication)
        await passwords.initialize()
        delivery = (
            mailer
            if mailer is not None
            else (
                SmtpMailer(authentication)
                if authentication.mail_transport == "smtp"
                else DisabledMailer()
            )
        )
        database = Database(settings if settings is not None else DatabaseSettings())
        application.state.database = database
        application.state.auth_settings = authentication
        application.state.identity_cipher = cipher
        application.state.passwords = passwords
        application.state.mailer = delivery
        application.state.name_search_cache = NameSearchCache()
        documents = DocumentSettings()
        application.state.document_settings = documents
        application.state.document_download_slots = anyio.Semaphore(
            documents.max_concurrent_downloads, max_value=documents.max_concurrent_downloads
        )
        maintenance = None
        try:
            async with database.sessions() as session:
                service = AuthService(session, authentication, cipher, passwords, delivery)
                await service.initialize_installation()
            if documents.maintenance_enabled:
                maintenance = asyncio.create_task(
                    document_maintenance(database, DocumentStorage(documents))
                )
            yield
        finally:
            if maintenance is not None:
                maintenance.cancel()
                with suppress(asyncio.CancelledError):
                    await maintenance
            application.state.name_search_cache.clear()
            await database.close()
            del application.state.database

    application = FastAPI(
        title="Sophikron API",
        description="API for the Sophikron educational platform.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(router)
    application.get("/health")(health_check)

    @application.middleware("http")
    async def security_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Prevent caching of identity responses and apply configured credentialed CORS."""
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    application.add_middleware(AuthRequestMiddleware)
    application.add_middleware(ConfiguredCORSMiddleware)

    @application.exception_handler(PasswordCapacityError)
    async def password_capacity_error(
        request: Request, error: PasswordCapacityError
    ) -> JSONResponse:
        """Reject excess password work promptly without revealing account existence."""
        return JSONResponse(
            {"detail": "Service occupé. Réessayez plus tard."},
            status_code=503,
            headers={"Retry-After": "1"},
        )

    @application.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError) -> JSONResponse:
        """Expose only nontechnical domain messages and optional rate-limit retry time."""
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        response = JSONResponse(
            {"detail": error.message}, status_code=error.status, headers=headers
        )
        if error.status == 401:
            configuration = request.app.state.auth_settings
            response.delete_cookie(
                configuration.cookie_name,
                path="/",
                secure=configuration.cookie_secure,
                httponly=True,
                samesite="lax",
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        """Never echo request inputs, passwords, tokens or validator exception contexts."""
        return JSONResponse({"detail": INVALID_REQUEST}, status_code=422)

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        """Hide SQL, bound data and connection details on persistence failure."""
        logger.warning("Application database operation failed")
        return JSONResponse(
            {"detail": "Service indisponible. Réessayez plus tard."}, status_code=503
        )

    return application


async def health_check(database: Annotated[Database, Depends(get_database)]) -> dict[str, str]:
    """Return readiness or an anonymous 503 response when PostgreSQL is unavailable."""
    try:
        await database.check_health()
    except (SQLAlchemyError, OSError, TimeoutError):
        logger.warning("PostgreSQL readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return {"status": "ok", "database": "connected"}


app = create_app()
