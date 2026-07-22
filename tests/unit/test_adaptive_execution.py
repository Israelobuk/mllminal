from pathlib import Path

import pytest

from mllminal.learning.adaptive import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionRequest,
    AdaptiveExecutionService,
)
from mllminal.learning.profile_contracts import ApplicationInteractionProfile
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository
from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def _adaptive(
    path: Path, *, emergency_stop_active=lambda: False
) -> tuple[AdaptiveExecutionService, ApplicationInteractionProfile]:
    repository = LearningRepository(path)
    repository.initialize()
    profile = ApplicationInteractionProfile(
        application_identity="explorer",
        executable_name="explorer.exe",
        stable_automation_ids=["open-button"],
    )
    repository.save_interaction_profile(profile, identity_key="explorer")
    profiles = ApplicationInteractionProfileService(repository)
    return AdaptiveExecutionService(
        repository,
        profiles,
        emergency_stop_active=emergency_stop_active,
    ), profile


def _request(profile: ApplicationInteractionProfile, run_id: str) -> AdaptiveExecutionRequest:
    return AdaptiveExecutionRequest(
        workflow_run_id=run_id,
        workflow_step_id="step-1",
        application_profile_id=profile.profile_id,
        abstract_action="control.invoke",
        target_signature="automation_id:open-button",
        candidates=[
            AdaptiveBackendCandidate(backend="windows.uia"),
            AdaptiveBackendCandidate(backend="local.vision"),
        ],
    )


def test_decisions_are_durable_and_verified_failure_changes_next_backend_ranking(
    tmp_path: Path,
) -> None:
    service, profile = _adaptive(tmp_path / "learning.db")

    first = service.decide(_request(profile, "run-1"))
    assert first.selected_backend == "windows.uia"
    assert first.rejected_backends == []
    assert "deterministic" in first.decision_reason

    failed = service.record_outcome(
        first.decision_id,
        execution_succeeded=False,
        verification_passed=False,
        failure_class="target_not_found",
    )
    assert failed.execution_outcome == "failed"
    assert failed.verification_outcome == "failed"
    assert failed.reward_signal_id is not None

    second = service.decide(_request(profile, "run-2"))
    assert second.selected_backend == "local.vision"
    assert service.decision(first.decision_id).decision_id == first.decision_id

    restarted, _ = _adaptive(tmp_path / "learning.db")
    assert restarted.decision(first.decision_id).execution_outcome == "failed"


def test_workflow_runtime_uses_adaptive_backend_and_stops_before_execution_on_emergency(
    tmp_path: Path,
) -> None:
    adaptive, profile = _adaptive(tmp_path / "learning.db")
    workflow = WorkflowService(tmp_path / "workflow.db", adaptive=adaptive)
    calls: list[str] = []
    workflow.register_backend(
        "control.invoke",
        "windows.uia",
        lambda _arguments: (
            calls.append("windows.uia")
            or CapabilityResult(
                capability="control.invoke", succeeded=False, error="target_not_found"
            )
        ),
    )
    workflow.register_backend(
        "control.invoke",
        "local.vision",
        lambda _arguments: (
            calls.append("local.vision")
            or CapabilityResult(
                capability="control.invoke", succeeded=True, output={"verified": True}
            )
        ),
    )
    definition = WorkflowDefinition(
        name="Open target",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="control.invoke", scope="local")],
        steps=[
            WorkflowStep(
                order=1,
                capability="control.invoke",
                approval_required=False,
                application_profile_id=profile.profile_id,
                abstract_action="control.invoke",
                target_signature="automation_id:open-button",
                backend_candidates=["windows.uia", "local.vision"],
                verification=WorkflowVerification(expected={"verified": True}),
            )
        ],
    )
    workflow.create(definition, idempotency_key="create")

    failed = workflow.run(definition.id, WorkflowRunRequest(preview=False), idempotency_key="run-1")
    succeeded = workflow.run(
        definition.id, WorkflowRunRequest(preview=False), idempotency_key="run-2"
    )

    assert failed.state.value == "failed"
    assert succeeded.state.value == "succeeded"
    assert calls == ["windows.uia", "local.vision"]
    assert adaptive.explain(succeeded.id)[0].selected_backend == "local.vision"

    stopped_adaptive, stopped_profile = _adaptive(
        tmp_path / "stopped.db", emergency_stop_active=lambda: True
    )
    stopped_workflow = WorkflowService(tmp_path / "stopped-workflow.db", adaptive=stopped_adaptive)
    stopped_workflow.register_backend(
        "control.invoke",
        "windows.uia",
        lambda _arguments: pytest.fail("emergency stop must prevent handler execution"),
    )
    stopped_definition = definition.model_copy(
        update={
            "id": "stopped-workflow",
            "steps": [
                definition.steps[0].model_copy(
                    update={"application_profile_id": stopped_profile.profile_id}
                )
            ],
        }
    )
    stopped_workflow.create(stopped_definition, idempotency_key="stopped-create")
    stopped = stopped_workflow.run(
        stopped_definition.id, WorkflowRunRequest(preview=False), idempotency_key="stopped-run"
    )

    assert stopped.state.value == "failed"
    decision = stopped_adaptive.explain(stopped.id)[0]
    assert decision.selected_backend is None
    assert decision.rejected_backends[0].reason == "emergency_stop_active"


def test_adaptive_requests_reject_sensitive_target_material(tmp_path: Path) -> None:
    service, profile = _adaptive(tmp_path / "learning.db")

    with pytest.raises(ValueError, match="prohibited"):
        service.decide(
            _request(profile, "run-1").model_copy(
                update={"target_signature": "password:do-not-store"}
            )
        )
