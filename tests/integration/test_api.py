import asyncio
import json
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
    app = create_app(settings=settings, store=store, token="test-token")
    return TestClient(app), {"Authorization": "Bearer test-token"}, workspace


def test_health_is_public_but_state_requires_authentication(tmp_path: Path) -> None:
    client, headers, _ = make_client(tmp_path)

    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/status").status_code == 401
    assert client.get("/v1/status", headers=headers).json()["mil"] == "Online"


def test_rest_flow_creates_approves_and_inspects_task(tmp_path: Path) -> None:
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()
    pending = client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers={**headers, "Idempotency-Key": "request-1"},
        json={"content": "open the project for inspection"},
    ).json()

    completed = client.post(
        f"/v1/approvals/{pending['approval']['id']}/decisions",
        headers={**headers, "Idempotency-Key": "approval-1"},
        json={"status": "APPROVED"},
    ).json()

    assert pending["task"]["state"] == "WAITING_FOR_APPROVAL"
    assert completed["state"] == "COMPLETED"
    assert client.get(f"/v1/tasks/{completed['id']}", headers=headers).status_code == 200
    assert len(client.get("/v1/tasks", headers=headers).json()) == 1


def test_websocket_authenticates_then_replays_ordered_events(tmp_path: Path) -> None:
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()

    with client.websocket_connect(
        f"/v1/events?session_id={session['id']}&after_sequence=0"
    ) as socket:
        socket.send_json({"type": "authenticate", "token": "test-token"})
        authenticated = socket.receive_json()
        event = socket.receive_json()

    assert authenticated == {"type": "authenticated"}
    assert event["sequence"] == 1
    assert event["event_type"] == "session.created"


def test_message_stream_emits_provider_events_before_pending_projection(tmp_path: Path) -> None:
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()

    response = client.post(
        f"/v1/sessions/{session['id']}/messages/stream",
        headers={**headers, "Idempotency-Key": "stream-request"},
        json={"content": "open the project for inspection"},
    )

    assert response.status_code == 200
    items = [json.loads(line) for line in response.text.splitlines()]
    events = [item["event"] for item in items if item["type"] == "event"]
    pending = [item["pending"] for item in items if item["type"] == "pending"]
    assert events
    assert "response.delta" in [event["event_type"] for event in events]
    assert pending[0]["task"]["state"] == "WAITING_FOR_APPROVAL"


def test_fast_chat_stream_repeats_conversation_without_generated_response_cache(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(daemon_api, "create_provider", lambda _config: ApiQwenProvider())
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()

    first = client.post(
        f"/v1/sessions/{session['id']}/messages/stream",
        headers={**headers, "Idempotency-Key": "chat-1"},
        json={"content": "hi"},
    )
    second = client.post(
        f"/v1/sessions/{session['id']}/messages/stream",
        headers={**headers, "Idempotency-Key": "chat-2"},
        json={"content": "hi"},
    )

    first_items = [json.loads(line) for line in first.text.splitlines()]
    second_items = [json.loads(line) for line in second.text.splitlines()]
    assert first.status_code == second.status_code == 200
    assert first_items[-1]["type"] == "chat"
    assert first_items[-1]["cached"] is False
    assert second_items[-1]["type"] == "chat"
    assert second_items[-1]["cached"] is False
    assert client.get("/v1/tasks", headers=headers).json() == []


def test_unknown_routes_return_typed_error(tmp_path: Path) -> None:
    client, headers, _ = make_client(tmp_path)

    response = client.get("/v1/tasks/missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_status_reports_persisted_provider_configuration(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    app = create_app(settings=settings, store=store, token="test-token")

    with TestClient(app) as client:
        status = client.get("/v1/status", headers={"Authorization": "Bearer test-token"}).json()

    assert status["provider"] == "deterministic"
    assert status["model"] == "fixture"
    assert status["streaming"] is True


def test_unavailable_qwen_returns_typed_error_without_breaking_daemon(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(
        ProviderConfig(
            provider="qwen",
            base_url="http://127.0.0.1:1",
            model="missing",
            request_timeout_seconds=0.1,
        )
    )
    store = RuntimeStore(settings.database_path)
    store.initialize()
    app = create_app(settings=settings, store=store, token="test-token")
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app, raise_server_exceptions=False) as client:
        session = client.post(
            "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
        ).json()
        response = client.post(
            f"/v1/sessions/{session['id']}/messages",
            headers={**headers, "Idempotency-Key": "unavailable-request"},
            json={"content": "open the project for inspection"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "provider_failed"
    assert client.get("/v1/health").status_code == 200


def test_two_clients_replay_identical_provider_events(tmp_path: Path) -> None:
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()
    client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers={**headers, "Idempotency-Key": "replay-request"},
        json={"content": "open the project for inspection"},
    )
    store = client.app.state.runtime.store
    expected_count = len(store.list_events(session["id"]))

    with (
        client.websocket_connect(
            f"/v1/events?session_id={session['id']}&after_sequence=0"
        ) as first,
        client.websocket_connect(
            f"/v1/events?session_id={session['id']}&after_sequence=0"
        ) as second,
    ):
        first.send_json({"type": "authenticate", "token": "test-token"})
        second.send_json({"type": "authenticate", "token": "test-token"})
        assert first.receive_json() == {"type": "authenticated"}
        assert second.receive_json() == {"type": "authenticated"}
        first_events = [first.receive_json() for _ in range(expected_count)]
        second_events = [second.receive_json() for _ in range(expected_count)]

    assert first_events == second_events
    assert "response.delta" in [event["event_type"] for event in first_events]
    assert "plan.proposed" in [event["event_type"] for event in first_events]


def test_approval_decision_offloads_blocking_runtime_work(tmp_path: Path, monkeypatch) -> None:
    client, headers, workspace = make_client(tmp_path)
    session = client.post(
        "/v1/sessions", headers=headers, json={"workspace_root": str(workspace)}
    ).json()
    pending = client.post(
        f"/v1/sessions/{session['id']}/messages",
        headers={**headers, "Idempotency-Key": "offload-request"},
        json={"content": "open the project for inspection"},
    ).json()

    calls: list[str] = []
    original_to_thread = asyncio.to_thread

    async def recording_to_thread(function, *args, **kwargs):
        calls.append(getattr(function, "__name__", "unknown"))
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)

    response = client.post(
        f"/v1/approvals/{pending['approval']['id']}/decisions",
        headers={**headers, "Idempotency-Key": "offload-approval"},
        json={"status": "APPROVED"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "COMPLETED"
    assert "decide" in calls
