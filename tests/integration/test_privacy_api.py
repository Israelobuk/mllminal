from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app
from mllminal.privacy.contracts import CaptureCategory, CaptureMode
from mllminal.runtime_store import RuntimeStore


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    return TestClient(create_app(settings, store, "test-token")), {
        "Authorization": "Bearer test-token"
    }


def test_privacy_requires_auth_and_explicit_enable(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)

    assert client.get("/v1/privacy/status").status_code == 401
    initial = client.get("/v1/privacy/status", headers=headers).json()
    assert initial["observation_enabled"] is False
    assert initial["consent_granted"] is False

    enabled = client.post(
        "/v1/privacy/enable", headers={**headers, "Idempotency-Key": "api-enable"}
    )
    assert enabled.status_code == 200
    assert enabled.json()["consent_granted"] is True


def test_privacy_capture_policy_and_history_routes_are_durable(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    client.post("/v1/privacy/enable", headers={**headers, "Idempotency-Key": "enable"})
    policy = client.get("/v1/privacy/policy", headers=headers).json()
    policy["capture_modes"][CaptureCategory.SEMANTIC_POINTER] = CaptureMode.METADATA
    updated = client.put(
        "/v1/privacy/policy",
        headers={**headers, "Idempotency-Key": "policy"},
        json=policy,
    )
    assert updated.status_code == 200

    captured = client.post(
        "/v1/privacy/capture",
        headers={**headers, "Idempotency-Key": "capture"},
        json={
            "category": CaptureCategory.SEMANTIC_POINTER,
            "payload": {"application": "Excel", "name": "Export"},
            "context": {"application": "Excel"},
        },
    )
    assert captured.json()["accepted"] is True
    assert len(client.get("/v1/privacy/history", headers=headers).json()) == 1
    exported = client.post(
        "/v1/privacy/history/export",
        headers={**headers, "Idempotency-Key": "export"},
        json={},
    )
    assert exported.json()["history"][0]["payload"]["name"] == "Export"


def test_privacy_exclusion_emergency_and_history_delete_routes(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    client.post("/v1/privacy/enable", headers={**headers, "Idempotency-Key": "enable"})
    rule = client.post(
        "/v1/privacy/exclusions",
        headers={**headers, "Idempotency-Key": "rule"},
        json={"rule_type": "application", "pattern": "Password Manager"},
    ).json()
    rejected = client.post(
        "/v1/privacy/capture",
        headers={**headers, "Idempotency-Key": "rejected"},
        json={
            "category": "DEVICE_METADATA",
            "payload": {"secret": "never"},
            "context": {"application": "Password Manager"},
        },
    ).json()
    assert rejected["accepted"] is False
    assert rejected["decision"]["reason"] == "excluded_application"
    assert (
        "never"
        not in client.post(
            "/v1/privacy/history/export",
            headers={**headers, "Idempotency-Key": "export"},
            json={},
        ).text
    )
    assert client.delete(
        f"/v1/privacy/exclusions/{rule['rule_id']}",
        headers={**headers, "Idempotency-Key": "remove-rule"},
    ).json() == {"deleted": True}

    client.post("/v1/privacy/emergency-stop", headers={**headers, "Idempotency-Key": "stop"})
    status = client.get("/v1/privacy/status", headers=headers).json()
    assert status["emergency_stop_active"] is True
    deleted = client.post(
        "/v1/privacy/history/delete",
        headers={**headers, "Idempotency-Key": "delete"},
        json={},
    )
    assert deleted.status_code == 200


def test_two_privacy_websockets_replay_the_same_events(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    client.post("/v1/privacy/enable", headers={**headers, "Idempotency-Key": "enable"})
    client.post("/v1/privacy/pause", headers={**headers, "Idempotency-Key": "pause"})
    expected = client.app.state.privacy.events()

    with client.websocket_connect("/v1/privacy/events/stream?after_sequence=0") as first:
        first.send_json({"type": "authenticate", "token": "test-token"})
        assert first.receive_json() == {"type": "authenticated"}
        first_events = [first.receive_json() for _ in expected]

    with client.websocket_connect("/v1/privacy/events/stream?after_sequence=0") as second:
        second.send_json({"type": "authenticate", "token": "test-token"})
        assert second.receive_json() == {"type": "authenticated"}
        second_events = [second.receive_json() for _ in expected]

    assert first_events == second_events == expected

    with client.websocket_connect(
        f"/v1/privacy/events/stream?after_sequence={expected[0]['sequence']}"
    ) as reconnect:
        reconnect.send_json({"type": "authenticate", "token": "test-token"})
        assert reconnect.receive_json() == {"type": "authenticated"}
        assert reconnect.receive_json()["sequence"] == expected[-1]["sequence"]
