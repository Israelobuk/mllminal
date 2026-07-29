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


def test_active_policy_bindings_are_authenticated_domain_scoped_and_disableable(
    tmp_path: Path,
) -> None:
    client, headers = _client(tmp_path)
    repository = client.app.state.learning_repository
    candidate = repository.create_policy_version(
        checkpoint_sha256="a" * 64,
        policy_domain="SUGGESTION_RANKING",
        feature_schema_version="training_features_v1",
    )
    artifact = tmp_path / "data" / "learning" / "checkpoints" / f"{candidate.name}.pt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"artifact")
    import hashlib

    repository.update_policy_checkpoint(candidate.id, hashlib.sha256(b"artifact").hexdigest())

    assert client.get("/v1/learning/policies/active").status_code == 401
    assert client.get("/v1/learning/policies/active", headers=headers).json() == []
    enabled = client.post(
        "/v1/learning/policies/active/SUGGESTION_RANKING/enable",
        headers={**headers, "Idempotency-Key": "enable-suggestion"},
        json={"candidate_id": candidate.id, "activated_by": "operator"},
    )

    assert enabled.status_code == 200
    assert enabled.json()["status"] == "ACTIVE"
    assert (
        client.get("/v1/learning/policies/active/SUGGESTION_RANKING", headers=headers).json()[
            "candidate_id"
        ]
        == candidate.id
    )

    disabled = client.post(
        "/v1/learning/policies/active/SUGGESTION_RANKING/disable",
        headers={**headers, "Idempotency-Key": "disable-suggestion"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "INACTIVE"
    assert (
        client.get("/v1/learning/policies/active/SUGGESTION_RANKING", headers=headers).status_code
        == 404
    )


def test_aggregated_policy_runtime_status_is_authenticated_and_safety_explicit(
    tmp_path: Path,
) -> None:
    client, headers = _client(tmp_path)

    assert client.get("/v1/adaptive/policies/status").status_code == 401
    response = client.get("/v1/adaptive/policies/status", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["deterministic_safety_authoritative"] is True
    assert body["online_training_enabled"] is False
    assert body["domains"]["REPAIR_RANKING"]["shadow_only"] is True
    assert body["domains"]["VERIFICATION_RANKING"]["shadow_only"] is False
