from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app
from mllminal.runtime_store import RuntimeStore


def test_latency_diagnostics_returns_last_safe_request_trace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(create_app(settings=settings, store=store, token="test-token")) as client:
        session = client.post(
            "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
        ).json()
        client.post(
            f"/v1/sessions/{session['id']}/messages",
            headers={**headers, "Idempotency-Key": "latency-api"},
            json={"content": "hello"},
        )
        response = client.get("/v1/diagnostics/latency", headers=headers)

    assert response.status_code == 200
    assert response.json()["route"] == "chat"
