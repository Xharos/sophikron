"""Local demo authentication without network calls or persistent credentials."""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def demo_seed(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the repository's demo entry point with isolated authentication inputs."""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "script"))
    monkeypatch.delenv("SOPHIKRON_SEED_EMAIL", raising=False)
    monkeypatch.delenv("SOPHIKRON_SEED_PASSWORD", raising=False)
    module = import_module("seed_demo_data")
    monkeypatch.setattr(module, "describe", Mock())
    monkeypatch.setattr(module, "seed", Mock())
    monkeypatch.setattr(module, "getpass", Mock(return_value="synthetic-test-password"))
    client = Mock()
    client.request.return_value = {
        "roles": ["admin"],
        "permissions": [
            "users.read",
            "users.manage",
            "promotions.read",
            "promotions.manage",
            "profiles.manage",
        ],
    }
    monkeypatch.setattr(module, "Client", Mock(return_value=client))
    return module


def test_demo_dry_run_needs_no_credentials_or_connection(demo_seed: ModuleType) -> None:
    """Validate scenario overrides without asking for credentials or contacting the API."""
    assert demo_seed.main(["--dry-run", "--classes", "4", "--namespace", "release"]) == 0
    scenario = demo_seed.describe.call_args.args[0]
    assert scenario.class_count == 4 and scenario.namespace == "release"
    assert demo_seed.CONFIG.class_count == 2 and demo_seed.CONFIG.namespace == "demo"
    demo_seed.Client.assert_not_called()
    demo_seed.getpass.assert_not_called()
    demo_seed.seed.assert_not_called()


@pytest.mark.parametrize("email_argument", [False, True], ids=["environment", "command-line"])
def test_demo_uses_supplied_credentials_and_logs_out(
    demo_seed: ModuleType, monkeypatch: pytest.MonkeyPatch, email_argument: bool
) -> None:
    """Respect the email override and process password, then revoke the session."""
    monkeypatch.setenv("SOPHIKRON_SEED_EMAIL", "environment@example.org")
    monkeypatch.setenv("SOPHIKRON_SEED_PASSWORD", "synthetic-environment-password")
    arguments = ["--email", "override@example.org"] if email_argument else []
    assert demo_seed.main(arguments) == 0
    client = demo_seed.Client.return_value
    assert client.request.call_args_list[0].args == (
        "POST",
        "/auth/login",
        {
            "identifier": "override@example.org" if email_argument else "environment@example.org",
            "password": "synthetic-environment-password",
        },
    )
    client.request.assert_called_with("POST", "/auth/logout")
    demo_seed.seed.assert_called_once()
    demo_seed.getpass.assert_not_called()


def test_demo_prompts_for_credentials(
    demo_seed: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prompt for a missing email and hide the password using getpass."""
    monkeypatch.setattr("builtins.input", Mock(return_value="  local@example.org  "))
    assert demo_seed.main([]) == 0
    demo_seed.getpass.assert_called_once()
    assert demo_seed.Client.return_value.request.call_args_list[0].args[2] == {
        "identifier": "local@example.org",
        "password": "synthetic-test-password",
    }


@pytest.mark.parametrize("failure", ["login", "permissions", "seed"])
def test_demo_failures_revoke_only_authenticated_sessions(
    demo_seed: ModuleType, failure: str
) -> None:
    """Skip seeding on denied access and log out even when later operations fail."""
    client = demo_seed.Client.return_value
    if failure == "login":
        client.request.side_effect = demo_seed.SeedError("Synthetic login failure")
    elif failure == "permissions":
        client.request.return_value = {"roles": ["teacher"], "permissions": []}
    else:
        demo_seed.seed.side_effect = demo_seed.SeedError("Synthetic scenario failure")
    assert demo_seed.main(["--email", "local@example.org"]) == 1
    if failure == "login":
        assert client.request.call_count == 1
    else:
        client.request.assert_called_with("POST", "/auth/logout")
    if failure != "seed":
        demo_seed.seed.assert_not_called()
