from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app
from mllminal.runtime_store import RuntimeStore


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    client = TestClient(create_app(settings, store, "test-token"))
    return client, {"Authorization": "Bearer test-token"}


def test_learning_status_runs_and_policies_are_authenticated_and_durable(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)

    assert client.get("/v1/learning/status").status_code == 401
    status = client.get("/v1/learning/status", headers=headers)
    policies = client.get("/v1/learning/policies", headers=headers)
    runs = client.get("/v1/learning/runs", headers=headers)

    assert status.status_code == 200
    assert status.json()["automatic_promotion_enabled"] is False
    assert policies.json()[0]["name"] == "policy_v0"
    assert runs.json() == []


def test_learning_websocket_authenticates_and_replays_persisted_events(tmp_path: Path) -> None:
    client, _headers = _client(tmp_path)
    client.app.state.learning_repository.append_event("learning.training.started", {"run": "safe"})

    with client.websocket_connect("/v1/learning/events?after_sequence=0") as socket:
        socket.send_json({"type": "authenticate", "token": "test-token"})
        assert socket.receive_json() == {"type": "authenticated"}
        event = socket.receive_json()

    assert event["event_type"] == "learning.training.started"
    assert event["payload"] == {"run": "safe"}


def test_offline_training_job_endpoint_is_authenticated_and_advisory(tmp_path: Path) -> None:
    from mllminal.learning.contracts import TrainingExperience

    client, headers = _client(tmp_path)
    repository = client.app.state.learning_repository
    for source_id, action in (
        ("one", "present"),
        ("two", "present"),
        ("three", "defer"),
        ("four", "defer"),
    ):
        repository.save_training_experience(
            TrainingExperience(
                policy_domain="SUGGESTION_RANKING",
                source_record_type="suggestion_feedback",
                source_record_id=source_id,
                context_features={"occurrence_count": 0.5},
                candidate_actions=("present", "defer"),
                selected_action=action,
                baseline_score=0.5,
                reward=1.0,
                reward_components={"feedback": 1.0},
                privacy_approved=True,
                eligible_for_training=True,
            )
        )

    assert client.post("/v1/learning/offline/train").status_code == 401
    response = client.post(
        "/v1/learning/offline/train",
        headers=headers,
        json={"policy_domain": "SUGGESTION_RANKING", "epochs": 2, "hidden_size": 8},
    )

    assert response.status_code == 200
    assert response.json()["candidate"]["lifecycle"] == "TRAINED"
    assert response.json()["candidate"]["checkpoint_sha256"]
    assert response.json()["training_run"]["status"] == "COMPLETED"
