"""Administration and validation entry points with synthetic inputs only."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import cli
from app.services import file_validation


@pytest.mark.parametrize("failure", [False, True])
def test_cli_reports_sanitized_outcome(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: bool,
) -> None:
    """Report success or a generic failure without exposing internal exception details."""
    monkeypatch.setattr(sys, "argv", ["cli", "prune-rate-limits"])
    execute = AsyncMock(side_effect=ValueError("private-diagnostic") if failure else None)
    monkeypatch.setattr(cli, "execute", execute)
    if failure:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
    else:
        cli.main()
    execute.assert_awaited_once()
    assert "private-diagnostic" not in str(capsys.readouterr())


@pytest.mark.parametrize("valid", [False, True])
def test_validation_entrypoint_emits_only_mime_or_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    valid: bool,
) -> None:
    """Validate real text bytes and reject invalid content without parser diagnostics."""
    path = tmp_path / "sample.py"
    path.write_bytes(b"print('hello')\n" if valid else b"\x00")
    monkeypatch.setattr(sys, "argv", ["validator", str(path), "py"])
    # Never apply subprocess OS resource limits to the pytest process.
    if file_validation.os.name == "posix":
        import resource

        monkeypatch.setattr(resource, "setrlimit", lambda *_arguments: None)
    assert file_validation.main() == (0 if valid else 1)
    output = capsys.readouterr()
    assert output.err == ""
    assert bool(output.out.strip()) == valid
