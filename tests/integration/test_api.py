from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import Settings
from mllminal.daemon.api import create_app
from mllminal.runtime_store import RuntimeStore


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
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
        json={"content": "inspect this project"},
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


def test_unknown_routes_return_typed_error(tmp_path: Path) -> None:
    client, headers, _ = make_client(tmp_path)

    response = client.get("/v1/tasks/missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
