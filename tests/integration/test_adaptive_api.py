from pathlib import Path

from fastapi.testclient import TestClient

from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.daemon.api import create_app
from mllminal.learning.adaptive import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionRequest,
)
from mllminal.learning.profile_contracts import ApplicationInteractionProfile
from mllminal.runtime_store import RuntimeStore


def test_adaptive_decisions_are_authenticated_and_explainable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=workspace)
    ProviderConfigStore(settings).save(ProviderConfig(provider="deterministic", model="fixture"))
    store = RuntimeStore(settings.database_path)
    store.initialize()
    app = create_app(settings, store, "test-token")
    profile = ApplicationInteractionProfile(
        application_identity="explorer",
        executable_name="explorer.exe",
        stable_automation_ids=["open-button"],
    )
    app.state.learning_repository.save_interaction_profile(profile, identity_key="explorer")
    decision = app.state.adaptive.decide(
        AdaptiveExecutionRequest(
            workflow_run_id="run-1",
            workflow_step_id="step-1",
            application_profile_id=profile.profile_id,
            abstract_action="control.invoke",
            target_signature="automation_id:open-button",
            candidates=[AdaptiveBackendCandidate(backend="windows.uia")],
        )
    )

    with TestClient(app) as client:
        headers = {"Authorization": "Bearer test-token"}
        assert client.get("/v1/adaptive/decisions").status_code == 401
        assert client.get("/v1/adaptive/decisions", headers=headers).json()[0]["decision_id"] == (
            decision.decision_id
        )
        assert (
            client.get(f"/v1/adaptive/decision/{decision.decision_id}", headers=headers).json()[
                "selected_backend"
            ]
            == "windows.uia"
        )
        assert (
            client.get("/v1/adaptive/explain/run-1", headers=headers).json()[0]["workflow_step_id"]
            == "step-1"
        )
        assert (
            client.get("/v1/adaptive/policy/status", headers=headers).json()[
                "automatic_promotion_enabled"
            ]
            is False
        )
