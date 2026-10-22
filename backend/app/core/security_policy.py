"""Bounded installation-secret loading without application or database dependencies."""

from pathlib import Path
from string import ascii_lowercase, ascii_uppercase, digits, punctuation

PASSWORD_CATEGORIES = (ascii_lowercase, ascii_uppercase, digits, punctuation)
PASSWORD_CHARACTERS = frozenset("".join(PASSWORD_CATEGORIES))


def validate_password(password: str) -> None:
    """Require 10–128 ASCII characters and at least one from each permitted category."""
    if (
        not 10 <= len(password) <= 128
        or not set(password) <= PASSWORD_CHARACTERS
        or any(
            not any(character in category for character in password)
            for category in PASSWORD_CATEGORIES
        )
    ):
        raise ValueError("Invalid password length, characters or categories")


def read_bootstrap_password(path: Path | None) -> str:
    """Read a bounded installation secret independently of the permanent password policy.

    Parameters
    ----------
    path
        Mounted secret file required for an unfinished installation.

    Returns
    -------
    str
        The installation password, never included in diagnostics.
    """
    try:
        if path is None:
            raise ValueError
        with path.open("rb") as source:
            raw = source.read(513)
        password = raw.decode("utf-8").rstrip("\r\n")
        if (
            len(raw) > 512
            or len(password) > 128
            or any(character in password for character in "\r\n\x00")
        ):
            raise ValueError
        return password
    except (OSError, UnicodeError, ValueError):
        raise ValueError(
            "A valid bootstrap password secret is required for initial setup"
        ) from None
