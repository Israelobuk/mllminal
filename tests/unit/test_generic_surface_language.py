import asyncio
import json
from pathlib import Path
from types import MethodType

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.client.api import DaemonClient
from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app as create_daemon_app
from mllminal.runtime_store import RuntimeStore

runner = CliRunner()


def test_cli_exposes_bounded_generic_capability_discovery(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)

    result = runner.invoke(
        create_app(settings), ["applications", "capability-discovery", "filesystem"]
    )

    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["application"] == "filesystem"
    assert report["bounded"] is True
    assert report["capabilities"]
    assert all(item["source"] == "registered_adapter" for item in report["capabilities"])


def test_daemon_exposes_authenticated_generic_capability_discovery(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    client = TestClient(create_daemon_app(settings=settings, store=store, token="test-token"))

    response = client.get("/v1/apps/filesystem/capability-discovery")
    assert response.status_code == 401
    response = client.get(
        "/v1/apps/filesystem/capability-discovery",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["application"] == "filesystem"
    assert response.json()["bounded"] is True


def test_desktop_snapshot_includes_generic_application_status(tmp_path: Path) -> None:
    client = DaemonClient(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    async def fake_request(
        _self: DaemonClient,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict | list[dict]:
        values: dict[str, dict | list[dict]] = {
            "/v1/status": {"status": "ok"},
            "/v1/device/status": {},
            "/v1/privacy/status": {},
            "/v1/tasks": [],
            "/v1/workflows": [],
            "/v1/workflow-runs": [],
            "/v1/permissions": [],
            "/v1/apps": [{"application": "filesystem", "state": "available"}],
            "/v1/visual/latest": {},
            "/v1/suggestions": [],
            "/v1/suggestion-preferences": [],
            "/v1/adaptive/policy/status": {},
            "/v1/adaptive/verification-ranking/status": {},
            "/v1/adaptive/policies/status": {},
        }
        return values[path]

    client.request = MethodType(fake_request, client)
    snapshot = asyncio.run(client.snapshot())

    assert snapshot.applications == [{"application": "filesystem", "state": "available"}]
