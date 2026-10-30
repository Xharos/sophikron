"""Shared guarded migration commands for PostgreSQL integration tests."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest


def run_alembic(*arguments: str) -> None:
    """Run migrations only on the dedicated test database and redact secret diagnostics."""
    if (
        os.environ.get("DB_INTEGRATION") != "1"
        or os.environ.get("DB_NAME") != "sophikron_test"
        or os.environ.get("DB_USER") != "sophikron_app"
    ):
        pytest.fail(
            "Integration tests require DB_INTEGRATION=1, DB_NAME=sophikron_test "
            "and DB_USER=sophikron_app",
            pytrace=False,
        )
    environment = os.environ.copy()
    environment["DB_USER"] = "sophikron_migrator"
    environment["DB_PASSWORD_FILE"] = environment["DB_TEST_MIGRATION_PASSWORD_FILE"]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        diagnostics = "\n".join((result.stdout, result.stderr)).strip()
        for secret_path in {os.environ.get("DB_PASSWORD_FILE"), environment["DB_PASSWORD_FILE"]}:
            if secret_path is None:
                continue
            try:
                secret = Path(secret_path).read_text(encoding="utf-8").rstrip("\r\n")
            except (OSError, UnicodeError):
                continue
            if secret:
                diagnostics = diagnostics.replace(secret, "[REDACTED]")
                diagnostics = diagnostics.replace(quote(secret, safe=""), "[REDACTED]")
        pytest.fail(
            f"Alembic {' '.join(arguments)} failed (exit {result.returncode}):\n{diagnostics}",
            pytrace=False,
        )
