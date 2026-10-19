"""Configuration validation and secret confidentiality tests."""

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import DatabaseSettings


def test_environment_and_secret(
    settings_factory: Callable[..., DatabaseSettings], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read separate environment variables and preserve special password characters."""
    settings_factory()
    secret = tmp_path / "special-password"
    password = " space@:/?#%'\\end "
    secret.write_bytes((password + "\r\n").encode())
    for name, value in {
        "DB_HOST": "db", "DB_NAME": "sophikron", "DB_USER": "app",
        "DB_PASSWORD_FILE": str(secret), "DB_POOL_SIZE": "3",
    }.items():
        monkeypatch.setenv(name, value)
    settings = DatabaseSettings()
    assert settings.url.password == password
    assert settings.url.host == "db"
    assert settings.pool_size == 3
    assert password not in repr(settings)
    assert password not in repr(settings.url)
    assert password not in settings.model_dump_json()


@pytest.mark.parametrize(
    "content",
    [b"", b"   ", b"private-secret\nsecond-line", b"private-secret\0suffix",
     b"\xffprivate-secret", b"private-secret" * 400],
    ids=["empty", "whitespace", "multiline", "null-byte", "invalid-encoding", "oversized"],
)
def test_invalid_secret(
    settings_factory: Callable[..., DatabaseSettings], tmp_path: Path, content: bytes,
) -> None:
    """Reject empty, multiline, non-UTF-8 and oversized secrets without echoing them."""
    secret = tmp_path / "invalid-password"
    secret.write_bytes(content)
    with pytest.raises(ValidationError) as error:
        settings_factory(password_file=secret)
    assert "private-secret" not in str(error.value)
    assert error.value.errors(include_input=False)[0]["type"] == "value_error"


def test_missing_secret(settings_factory: Callable[..., DatabaseSettings], tmp_path: Path) -> None:
    """Fail explicitly when the runtime secret cannot be read."""
    with pytest.raises(ValidationError, match="Cannot read the PostgreSQL password secret"):
        settings_factory(password_file=tmp_path / "missing")


@pytest.mark.parametrize("field", ["host", "name", "user", "password_file"])
def test_required_setting(
    settings_factory: Callable[..., DatabaseSettings],
    field: str,
) -> None:
    """Require each connection setting independently, without fallback credentials."""
    settings = settings_factory()
    values = {
        "host": settings.host, "name": settings.name, "user": settings.user,
        "password_file": settings.password_file,
    }
    del values[field]
    with pytest.raises(ValidationError) as error:
        DatabaseSettings(**values)
    errors = error.value.errors(include_input=False)
    assert len(errors) == 1
    assert errors[0]["loc"] == (field,)
    assert errors[0]["type"] == "missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [("pool_size", 0), ("max_overflow", -1), ("pool_timeout", 0),
     ("pool_timeout", "nan"), ("port", 65536), ("statement_timeout_ms", 0),
     ("health_timeout", -1), ("sslmode", "invalid")],
)
def test_invalid_settings(
    settings_factory: Callable[..., DatabaseSettings], field: str, value: object,
) -> None:
    """Reject invalid limits before opening any network connection."""
    with pytest.raises(ValidationError) as error:
        settings_factory(**{field: value})
    assert [item["loc"] for item in error.value.errors(include_input=False)] == [(field,)]
