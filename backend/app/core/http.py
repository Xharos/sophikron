"""Early bounded authentication bodies and application-scoped browser CORS policy."""

import anyio
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AuthRequestMiddleware:
    """Bound authentication request bytes and total body-read time before JSON parsing."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the application without loading configuration or secrets at import time."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Buffer at most the configured bytes, including requests without Content-Length."""
        if scope["type"] != "http" or not scope["path"].startswith(
            ("/api/v1/auth/", "/api/v1/admin/")
        ):
            await self.app(scope, receive, send)
            return
        settings = scope["app"].state.auth_settings
        limit = settings.request_max_bytes
        lengths = [value for key, value in scope["headers"] if key.lower() == b"content-length"]
        status = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                status = 400
            elif len(lengths[0]) > 20 or int(lengths[0]) > limit:
                status = 413
        chunks: list[bytes] = []
        size = 0
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
        if settings is not None and self.policy is None:
            self.policy = CORSMiddleware(
                self.app,
                allow_origins=settings.allowed_origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-CSRF-Protection"],
            )
        await (self.policy or self.app)(scope, receive, send)
