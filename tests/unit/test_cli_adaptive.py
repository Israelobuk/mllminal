from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings
from mllminal.learning.adaptive import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionRequest,
    AdaptiveExecutionService,
)
from mllminal.learning.profile_contracts import ApplicationInteractionProfile
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository

runner = CliRunner()


def test_adaptive_cli_shows_persisted_decisions_and_policy_status(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path, workspace_root=tmp_path)
    repository = LearningRepository(settings.database_path)
    repository.initialize()
    profile = ApplicationInteractionProfile(
        application_identity="explorer",
        executable_name="explorer.exe",
        stable_automation_ids=["open-button"],
    )
    repository.save_interaction_profile(profile, identity_key="explorer")
    service = AdaptiveExecutionService(repository, ApplicationInteractionProfileService(repository))
    decision = service.decide(
        AdaptiveExecutionRequest(
            workflow_run_id="run-1",
            workflow_step_id="step-1",
            application_profile_id=profile.profile_id,
            abstract_action="control.invoke",
            target_signature="automation_id:open-button",
            candidates=[AdaptiveBackendCandidate(backend="windows.uia")],
        )
    )
    app = create_app(settings)

    decisions = runner.invoke(app, ["adaptive", "decisions"])
    detail = runner.invoke(app, ["adaptive", "decision", decision.decision_id])
    explanation = runner.invoke(app, ["adaptive", "explain", "run-1"])
    policy = runner.invoke(app, ["adaptive", "policy", "status"])

    assert decisions.exit_code == detail.exit_code == explanation.exit_code == policy.exit_code == 0
    assert decision.decision_id in decisions.stdout
    assert "windows.uia" in detail.stdout
    assert "step-1" in explanation.stdout
    assert "automatic_promotion_enabled" in policy.stdout
