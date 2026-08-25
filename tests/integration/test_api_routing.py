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


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    return (
        TestClient(create_app(settings=settings, store=store, token="test-token")),
        {"Authorization": "Bearer test-token"},
        workspace,
    )


def test_natural_read_only_message_returns_route_without_pending_task(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(daemon_api, "create_provider", lambda _config: ApiQwenProvider())
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()

    response = client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers={**headers, "Idempotency-Key": "natural-read-only"},
        json={"content": "summarize this project"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["route"] == "read_only_tool"
    assert "task" not in payload
    assert client.get("/v1/tasks", headers=headers).json() == []
