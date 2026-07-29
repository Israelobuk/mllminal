from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app
from mllminal.runtime_store import RuntimeStore
from mllminal.workflow.contracts import (
    WorkflowDefinition,
    WorkflowPermission,
    WorkflowStep,
    WorkflowVerification,
)


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str], WorkflowDefinition]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    client = TestClient(create_app(settings=settings, store=store, token="test-token"))
    definition = WorkflowDefinition(
        name="api fixture",
        permissions=[WorkflowPermission(capability="fixture.ok", scope="fixture")],
        steps=[
            WorkflowStep(
                capability="fixture.ok",
                order=1,
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            )
        ],
    )
    return client, {"Authorization": "Bearer test-token"}, definition


def test_workflow_execution_projection_and_stream_require_authentication(tmp_path: Path) -> None:
    client, headers, definition = _client(tmp_path)
    created = client.post(
        "/v1/workflows",
        headers={**headers, "Idempotency-Key": "api-create"},
        json={"definition": definition.model_dump(mode="json")},
    )
    workflow_id = created.json()["id"]
    client.post(
        f"/v1/workflows/{workflow_id}/activate",
        headers={**headers, "Idempotency-Key": "api-activate"},
    )
    run = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={**headers, "Idempotency-Key": "api-run"},
        json={"preview": True},
    ).json()

    assert client.get(f"/v1/workflow-runs/{run['id']}/execution").status_code == 401
    assert (
        client.get(f"/v1/workflow-runs/{run['id']}/execution", headers=headers).json()["id"]
        == run["id"]
    )
    assert client.get(f"/v1/workflow-runs/{run['id']}/attempts", headers=headers).json() == []

    with client.websocket_connect(
        f"/v1/workflow-runs/{run['id']}/events/stream?after_sequence=0"
    ) as socket:
        socket.send_json({"type": "authenticate", "token": "test-token"})
        assert socket.receive_json() == {"type": "authenticated"}
        event = socket.receive_json()

    assert event["event_type"] == "run.created"
