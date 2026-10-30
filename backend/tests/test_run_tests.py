"""Verify orchestration failure paths without starting Docker from unit tests."""

import subprocess
from pathlib import Path

import pytest

import run_tests


@pytest.mark.parametrize("pytest_status", [0, 1])
def test_runner_cleans_up_after_pytest(
    monkeypatch: pytest.MonkeyPatch,
    pytest_status: int,
) -> None:
    """Preserve pytest's result and always delete only the generated disposable project."""
    commands: list[list[str]] = []
    secrets_directory: Path | None = None

    def command(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Record subprocess calls and simulate dynamically published service ports."""
        commands.append(arguments)
        if "generate-keys" in arguments:
            Path(arguments[-1]).write_text("{}")
        stdout = "127.0.0.1:55432\n" if "5432" in arguments else "127.0.0.1:18000\n"
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout)

    def pytest_run(arguments: list[str]) -> int:
        """Verify isolation before returning a synthetic test outcome."""
        nonlocal secrets_directory
        import os

        secrets_directory = Path(os.environ["SOPHIKRON_SECRETS_DIRECTORY"])
        assert (secrets_directory / "identity_keys.json").is_file()
        assert os.environ["DB_NAME"] == "sophikron_test"
        assert os.environ["DB_PORT"] == "55432"
        assert os.environ["DB_TEST_API_URL"] == "http://127.0.0.1:18000"
        assert "-m" not in arguments
        return pytest_status

    monkeypatch.setenv("DB_NAME", "valuable_database")
    monkeypatch.setattr(run_tests.subprocess, "run", command)
    monkeypatch.setattr(run_tests.pytest, "main", pytest_run)
    assert run_tests.main([]) == pytest_status
    assert secrets_directory is not None and not secrets_directory.exists()
    cleanup = commands[-1]
    assert "down" in cleanup and "--volumes" in cleanup
    assert cleanup[cleanup.index("--project-name") + 1].startswith("sophikron-tests-")
    import os

    assert os.environ["DB_NAME"] == "valuable_database"


def test_runner_cleans_up_after_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove resources even when Docker partially starts the stack and returns an error."""
    commands: list[list[str]] = []

    def command(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Fail startup but allow the cleanup command to complete."""
        commands.append(arguments)
        if "generate-keys" in arguments:
            Path(arguments[-1]).write_text("{}")
        if "up" in arguments:
            raise subprocess.CalledProcessError(1, arguments)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(run_tests.subprocess, "run", command)
    assert run_tests.main([]) == 1
    assert "down" in commands[-1] and "--volumes" in commands[-1]


def test_runner_refuses_non_test_project() -> None:
    """Reject cleanup requests that could target the normal development stack."""
    with pytest.raises(ValueError, match="non-disposable"):
        run_tests.compose("sophikron", {}, "down", "--volumes")
