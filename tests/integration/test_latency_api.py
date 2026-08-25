from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.agent.provider import MilProviderEvent, MilRequest
from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon import api as daemon_api
from mllminal.daemon.api import create_app
from mllminal.runtime_store import RuntimeStore


class ApiQwenProvider:
    async def stream_conversation(self, request: MilRequest):
        response = f"Model answer for: {request.user_message}"
        yield MilProviderEvent(event_type="response.started")
        yield MilProviderEvent(event_type="response.delta", text=response)
        yield MilProviderEvent(event_type="response.completed", text=response)

    async def stream_response(self, _request: MilRequest):
        raise AssertionError("these API checks must use the conversational model path")
        yield


def test_latency_diagnostics_returns_last_safe_request_trace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(daemon_api, "create_provider", lambda _config: ApiQwenProvider())
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
