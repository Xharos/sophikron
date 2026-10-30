"""Early bounded authentication bodies and application-scoped browser CORS policy."""

import logging

import anyio
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.documents import is_document_upload


class SearchAccessLogFilter(logging.Filter):
    """Remove personal search text from Uvicorn's access-log URL argument."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Preserve the access entry but omit search query strings from known URL arguments."""
        if isinstance(record.args, tuple) and len(record.args) == 5:
            address, method, target, protocol, status = record.args
            if isinstance(target, str) and target.startswith("/api/v1/timetable/feed/"):
                record.args = (
                    address,
                    method,
                    "/api/v1/timetable/feed/[redacted].ics",
                    protocol,
                    status,
                )
                return True
            if isinstance(target, str) and target.split("?", 1)[0] in {
                "/api/v1/admin/users/search",
                "/api/v1/teaching/users/search",
                "/api/v1/admin/communes",
            }:
                record.args = (address, method, target.split("?", 1)[0], protocol, status)
            elif isinstance(target, str) and target.split("?", 1)[0].endswith(
                ("/teacher-options", "/responsible-options")
            ):
                record.args = (address, method, target.split("?", 1)[0], protocol, status)
        return True


class AuthRequestMiddleware:
    """Bound authentication request bytes and total body-read time before JSON parsing."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application without loading configuration or secrets at import time."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Buffer at most the configured bytes, including requests without Content-Length."""
        if scope["type"] != "http" or not scope["path"].startswith(
            (
                "/api/v1/auth/",
                "/api/v1/admin/",
                "/api/v1/teaching/",
                "/api/v1/lessons",
                "/api/v1/timetable/",
            )
        ):
            await self.app(scope, receive, send)
            return
        settings = scope["app"].state.auth_settings
        limit = settings.request_max_bytes
        binary = is_document_upload(scope["path"], scope.get("method", ""))
        if binary:
            limit = scope["app"].state.document_settings.max_bytes
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        status = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                status = 400
            elif len(lengths[0]) > 20 or int(lengths[0]) > limit:
                status = 413
        chunks: list[bytes] = []
        size = 0
        if binary and status is None:
            # The authenticated document service counts/limits the raw stream; do not buffer it.
            await self.app(scope, receive, send)
            return
        if status is None:
            try:
                with anyio.fail_after(settings.request_body_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        size += len(chunk)
                        if size > limit:
                            status = 413
                            break
                        if chunk:
                            chunks.append(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                status = 408
        if status is not None:
            response = JSONResponse(
                {"detail": "La demande n’a pas pu être acceptée."},
                status_code=status,
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )
            await response(scope, receive, send)
            return
        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            """Replay the bounded body once, preserving downstream disconnect handling."""
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class ConfiguredCORSMiddleware:
    """Use exact validated origins without loading secrets during module import."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap an ASGI application and defer configuration until startup has completed."""
        self.app = app
        self.policy: CORSMiddleware | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Apply credentialed CORS to HTTP requests; pass lifespan and websocket scopes through."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = getattr(scope["app"].state, "auth_settings", None)
        if settings is not None and not settings.cors_enabled:
            await self.app(scope, receive, send)
            return
        if settings is not None and self.policy is None:
            self.policy = CORSMiddleware(
                self.app,
                allow_origins=settings.allowed_origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "X-CSRF-Protection"],
            )
        await (self.policy or self.app)(scope, receive, send)
