"""Check deployment trust boundaries in resolved Compose configuration without starting services."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI required")
@pytest.mark.parametrize("local", [False, True], ids=["production", "local"])
@pytest.mark.parametrize("frontend_port", [3000, 3100])
def test_compose_trust_boundary(local: bool, frontend_port: int, tmp_path: Path) -> None:
    """Keep public ports on loopback and migration credentials out of the runtime service."""
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("DB_", "AUTH_", "SOPHIKRON_", "COMPOSE_", "BFF_", "API_"))
        and key not in {"FRONTEND_PORT", "BACKEND_PORT"}
    }
    environment.update(
        SOPHIKRON_SECRETS_DIRECTORY=str(tmp_path),
        DB_POOL_SIZE="7",
        AUTH_SESSION_SECONDS="3600",
        FRONTEND_PORT=str(frontend_port),
    )
    env_file = str(ROOT / ".env.example") if local else os.devnull
    command = ["docker", "compose", "--env-file", env_file, "-f", str(ROOT / "compose.yaml")]
    if local:
        command.extend(["-f", str(ROOT / "compose.local.yaml")])
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=True, timeout=30,
    )
    services = json.loads(result.stdout)["services"]
    for name in ("backend", "frontend", "migrate"):
        service = services[name]
        assert service["init"] is True
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"]
    for service in services.values():
        assert service["logging"] == {
            "driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}
        }
    for service in services.values():
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1"
    backend = services["backend"]
    document_mount = next(
        mount for mount in backend["volumes"]
        if mount["target"] == "/var/lib/sophikron/documents"
    )
    assert document_mount["type"] == "volume"
    assert document_mount.get("read_only", False) is False
    assert backend["environment"]["DB_POOL_SIZE"] == "7"
    assert backend["environment"]["AUTH_SESSION_SECONDS"] == "3600"
    assert backend["environment"]["AUTH_COOKIE_SECURE"] == ("false" if local else "true")
    assert {secret["source"] for secret in backend["secrets"]}.isdisjoint(
        {"db_admin_password", "db_migration_password"}
    )
    assert backend["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    if local:
        assert services["frontend"]["environment"]["ADDRESS_HEADER"] == ""
        expected_origin = f"http://localhost:{frontend_port}"
        assert services["frontend"]["environment"]["ORIGIN"] == expected_origin
        assert services["frontend"]["build"]["args"]["SITE_ORIGIN"] == expected_origin
        assert expected_origin in json.loads(backend["environment"]["AUTH_ALLOWED_ORIGINS"])
    else:
        assert "ports" not in services["db"]
        assert "ports" not in backend
        assert backend["environment"]["AUTH_CORS_ENABLED"] == "false"
