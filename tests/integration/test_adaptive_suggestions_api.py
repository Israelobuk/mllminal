from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.contracts import utc_now
from mllminal.daemon.api import create_app
from mllminal.mining.contracts import MinedStep, WorkflowCandidate
from mllminal.runtime_store import RuntimeStore


def _candidate() -> WorkflowCandidate:
    now = utc_now()
    return WorkflowCandidate(
        id="candidate-api",
        application="explorer",
        steps=[
            MinedStep(application="explorer", kind="control.invoked"),
            MinedStep(application="explorer", kind="control.invoked"),
        ],
        occurrences=5,
        confidence=0.8,
        first_seen=now,
        last_seen=now,
        source_event_ids=["event-api"],
    )


def test_suggestion_api_is_authenticated_and_feedback_is_idempotent(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    app = create_app(settings, store, "test-token")
    headers = {"Authorization": "Bearer test-token"}

    with TestClient(app) as client:
        assert client.get("/v1/suggestions").status_code == 401
        proposed = client.post(
            "/v1/suggestions/propose",
            headers=headers,
            json={
                "candidate": _candidate().model_dump(mode="json"),
                "verification_available": True,
            },
        )
        assert proposed.status_code == 200
        suggestion_id = proposed.json()["suggestion_id"]
        first = client.post(
            f"/v1/suggestions/{suggestion_id}/feedback",
            headers={**headers, "Idempotency-Key": "feedback-1"},
            json={"kind": "reject"},
        )
        second = client.post(
            f"/v1/suggestions/{suggestion_id}/feedback",
            headers={**headers, "Idempotency-Key": "feedback-1"},
            json={"kind": "reject"},
        )
        preference = client.put(
            "/v1/suggestion-preferences",
            headers=headers,
            json={
                "preference": {
                    "scope": "workflow",
                    "candidate_id": "candidate-api",
                    "enabled": False,
                }
            },
        )

    assert first.status_code == second.status_code == preference.status_code == 200
    assert first.json()["feedback_id"] == second.json()["feedback_id"]
    assert preference.json()["enabled"] is False
