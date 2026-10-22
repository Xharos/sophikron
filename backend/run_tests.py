"""Run the whole backend suite locally with disposable Docker services and secrets."""

import os
import re
import secrets
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import FrameType
from uuid import uuid4

import pytest

BACKEND = Path(__file__).resolve().parent
PROJECT = BACKEND.parent


def compose(
    project: str,
    environment: dict[str, str],
    *arguments: str,
    capture: bool = False,
    timeout: int = 600,
) -> str:
    """Execute Compose only for this runner's unique disposable project.

    Parameters
    ----------
    project
        Generated test project name; ordinary development projects are rejected.
    environment
        Isolated settings pointing exclusively to synthetic secrets and a test database.
    arguments
        Compose subcommand and arguments, passed without a shell.
    capture
        Capture stdout for published-port discovery.
    timeout
        Maximum command duration in seconds.

    Returns
    -------
    str
        Captured stdout, or an empty string for streamed commands.
    """
    if not re.fullmatch(r"sophikron-tests-[0-9a-f]{12}", project):
        raise ValueError("Refusing to operate on a non-disposable Docker project")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            os.devnull,
            "-f",
            str(PROJECT / "compose.yaml"),
            "--project-name",
            project,
            *arguments,
        ],
        cwd=PROJECT,
        env=environment,
        check=True,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout or ""


def prepare_environment(directory: Path) -> dict[str, str]:
    """Create independent test credentials without reading or modifying the project's .env."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DB_", "AUTH_", "SOPHIKRON_", "COMPOSE_", "PYTEST_"))
    }
    for name in (
        "db_admin_password",
        "db_app_password",
        "db_migration_password",
        "bootstrap_password",
    ):
        with (directory / name).open("x", encoding="utf-8") as output:
            output.write(secrets.token_hex(32))
    (directory / "smtp_password").touch(exist_ok=False)
    # Keep application/AnyIO imports outside this process until pytest loads its plugins.
    # Reuse the actual key-generation CLI rather than duplicating its keyring format.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "generate-keys",
            "--output",
            str(directory / "identity_keys.json"),
        ],
        cwd=BACKEND,
        env=environment,
        check=True,
        timeout=30,
    )
    # The parent directory is private; individual bind-mounted files must be readable by UID 10001.
    for path in directory.iterdir():
        path.chmod(0o644)
    environment.update(
        {
            "SOPHIKRON_SECRETS_DIRECTORY": str(directory),
            "DB_NAME": "sophikron_test",
            "DB_PUBLISHED_PORT": "0",
            "BACKEND_PORT": "127.0.0.1:0",
            "DB_HOST": "127.0.0.1",
            "DB_USER": "sophikron_app",
            "DB_SSLMODE": "disable",
            "DB_PASSWORD_FILE": str(directory / "db_app_password"),
            "DB_TEST_MIGRATION_PASSWORD_FILE": str(directory / "db_migration_password"),
            "DB_INTEGRATION": "1",
            "AUTH_ENVIRONMENT": "test",
            "AUTH_COOKIE_SECURE": "false",
            "AUTH_ALLOWED_ORIGINS": '["http://localhost"]',
            "AUTH_BOOTSTRAP_USERNAME": "verification_setup",
            "AUTH_MAIL_TRANSPORT": "disabled",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment


def published_port(project: str, environment: dict[str, str], service: str, port: str) -> str:
    """Discover a Docker-assigned loopback port instead of reserving fixed host ports."""
    address = compose(project, environment, "port", service, port, capture=True).strip()
    match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", address)
    if match is None or not 1 <= int(match[1]) <= 65535:
        raise ValueError("Docker did not publish the test service on a valid loopback port")
    return match[1]


def interrupted(signum: int, frame: FrameType | None) -> None:
    """Turn a normal termination signal into an interrupt so the cleanup block can run."""
    raise KeyboardInterrupt


def main(arguments: list[str] | None = None) -> int:
    """Start isolated services, run pytest in this debuggable process and remove test volumes.

    Parameters
    ----------
    arguments
        Optional additional pytest arguments; defaults to command-line arguments.

    Returns
    -------
    int
        Pytest's exit code, or a failure code when startup or cleanup fails.
    """
    project = "sophikron-tests-" + uuid4().hex[:12]
    print(f"Docker test project: {project}", flush=True)
    original_environment = os.environ.copy()
    original_sigterm = signal.signal(signal.SIGTERM, interrupted)
    result = 1
    try:
        with TemporaryDirectory(prefix="sophikron-tests-") as temporary:
            environment = prepare_environment(Path(temporary))
            attempted_start = False
            try:
                attempted_start = True
                compose(
                    project,
                    environment,
                    "up",
                    "--detach",
                    "--build",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "db",
                    "backend",
                )
                environment["DB_PORT"] = published_port(project, environment, "db", "5432")
                api_port = published_port(project, environment, "backend", "8000")
                environment["DB_TEST_API_URL"] = f"http://127.0.0.1:{api_port}"
                os.environ.clear()
                os.environ.update(environment)
                print("Running all backend tests in the local Python interpreter.", flush=True)
                result = int(
                    pytest.main(
                        [
                            "-q",
                            str(BACKEND / "tests"),
                            *(sys.argv[1:] if arguments is None else arguments),
                        ]
                    )
                )
            except KeyboardInterrupt:
                print("Test run interrupted; cleaning up Docker services.", flush=True)
                result = 130
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"Test infrastructure failed: {error}", file=sys.stderr, flush=True)
                result = 1
            finally:
                os.environ.clear()
                os.environ.update(original_environment)
                if attempted_start:
                    print(f"Removing test containers and volumes: {project}", flush=True)
                    try:
                        compose(
                            project,
                            environment,
                            "down",
                            "--volumes",
                            "--remove-orphans",
                            "--rmi",
                            "local",
                            timeout=120,
                        )
                    except (OSError, ValueError, subprocess.SubprocessError) as error:
                        print(f"Docker cleanup failed for {project}: {error}", file=sys.stderr)
                        result = 1
    finally:
        signal.signal(signal.SIGTERM, original_sigterm)
    return result


if __name__ == "__main__":
    sys.exit(main())
