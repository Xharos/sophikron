"""Authenticated field encryption, keyed exact lookup and bounded Argon2id operations."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable
from pathlib import Path

import anyio
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from email_validator import EmailNotValidError, validate_email

from app.core.auth_config import AuthSettings
from app.core.security_policy import validate_password as validate_password

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


class PasswordCapacityError(Exception):
    """Indicate a full or timed-out password queue without consuming a login failure."""


def normalize_username(value: str) -> str:
    """Return an ASCII username suitable for unambiguous, case-insensitive login."""
    normalized = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", normalized):
        raise ValueError("Invalid username")
    return normalized


def normalize_email(value: str) -> str:
    """Validate without DNS calls and apply the application's case-insensitive policy."""
    try:
        normalized = validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ValueError("Invalid email") from None
    if len(normalized) > 254:
        raise ValueError("Invalid email")
    return normalized


def new_token() -> str:
    """Return a URL-safe secret containing 256 bits of operating-system randomness."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> bytes:
    """Return the full SHA-256 verifier for a high-entropy random token."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def write_private_file(path: Path, content: str) -> None:
    """Create a new owner-readable secret file without overwriting an existing file.

    Parameters
    ----------
    path
        A file in an existing directory protected by the operator's filesystem ACLs.
    content
        Secret material; never included in errors or logs.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)


class IdentityCipher:
    """Encrypt private account fields, binding each ciphertext to its owner and field."""

    def __init__(self, active: str, keys: dict[str, bytes], lookup_key: bytes) -> None:
        """Validate a versioned AES-256 keyring and an independent HMAC lookup key."""
        if (
            active not in keys
            or not keys
            or len(lookup_key) != 32
            or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", key) for key in keys)
            or any(len(value) != 32 or value == lookup_key for value in keys.values())
        ):
            raise ValueError("Invalid identity keyring")
        self.active = active
        self._keys = keys.copy()
        self._lookup_key = lookup_key

    @classmethod
    def from_file(cls, path: Path) -> "IdentityCipher":
        """Load a bounded keyring without exposing its contents on parse failure."""
        try:
            with path.open("rb") as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                raise ValueError
            data = json.loads(raw)
            keys = {
                key: base64.b64decode(value, validate=True)
                for key, value in data["encryption_keys"].items()
            }
            return cls(
                data["active_key"], keys, base64.b64decode(data["lookup_key"], validate=True)
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("Cannot load identity encryption keys") from None

    def lookup(self, field: str, value: str) -> bytes:
        """Return a domain-separated HMAC for exact lookup, uniqueness or rate limiting."""
        return hmac.digest(self._lookup_key, (field + "\0" + value).encode("utf-8"), "sha256")

    def encrypt(self, user_id: int, field: str, value: str) -> bytes:
        """Return a versioned ciphertext using a fresh 96-bit nonce and row-bound AAD."""
        nonce = os.urandom(12)
        aad = f"sophikron:users:{user_id}:{field}:{self.active}".encode()
        encrypted = AESGCM(self._keys[self.active]).encrypt(nonce, value.encode(), aad)
        return self.active.encode() + b":" + nonce + encrypted

    def decrypt(self, user_id: int, field: str, value: bytes) -> str:
        """Authenticate and decrypt a field; refuse unknown keys and transplanted values."""
        try:
            version, payload = value.split(b":", 1)
            key_id = version.decode("ascii")
            aad = f"sophikron:users:{user_id}:{field}:{key_id}".encode()
            return AESGCM(self._keys[key_id]).decrypt(payload[:12], payload[12:], aad).decode()
        except (ValueError, KeyError, UnicodeError, InvalidTag):
            raise ValueError("Cannot decrypt user identity") from None


class PasswordSecurity:
    """Run memory-hard password operations outside the event loop with a concurrency cap."""

    def __init__(self, settings: AuthSettings) -> None:
        """Configure explicit Argon2id parameters and a per-process capacity limiter."""
        self.hasher = PasswordHasher(
            memory_cost=settings.argon_memory_kib,
            time_cost=settings.argon_iterations,
            parallelism=settings.argon_parallelism,
            type=Type.ID,
        )
        self.limiter = anyio.CapacityLimiter(settings.password_workers)
        self._workers = anyio.Semaphore(settings.password_workers)
        self._admission = anyio.CapacityLimiter(
            settings.password_workers + settings.password_queue_size
        )
        self._queue_timeout = settings.password_queue_timeout_seconds
        self.dummy_hash: str | None = None

    async def _run[T](self, operation: Callable[[], T]) -> T:
        """Bound admitted jobs and queue wait while letting running Argon2 finish safely."""
        try:
            self._admission.acquire_nowait()
        except anyio.WouldBlock:
            raise PasswordCapacityError from None
        acquired = False
        try:
            try:
                with anyio.fail_after(self._queue_timeout):
                    await self._workers.acquire()
                    acquired = True
            except TimeoutError:
                raise PasswordCapacityError from None
            return await anyio.to_thread.run_sync(operation, limiter=self.limiter)
        finally:
            if acquired:
                self._workers.release()
            self._admission.release()

    async def initialize(self) -> None:
        """Create a random dummy verifier once at startup without blocking the event loop."""
        self.dummy_hash = await self.hash(new_token())

    async def hash(self, password: str) -> str:
        """Return a salted Argon2id PHC string using the bounded worker pool."""
        return await self._run(lambda: self.hasher.hash(password))

    async def verify(self, encoded: str | None, password: str) -> bool:
        """Perform a real or dummy verification without exposing account existence."""

        def verify_sync() -> bool:
            """Translate library verification failures into an authentication result."""
            try:
                valid = self.hasher.verify(encoded or self.dummy_hash or "", password)
                return bool(encoded and valid)
            except (VerificationError, InvalidHashError):
                return False

        return await self._run(verify_sync)
