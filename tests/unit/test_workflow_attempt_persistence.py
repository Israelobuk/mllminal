from pathlib import Path

from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowStepAttemptState,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def _definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        name="durable fixture",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="fixture.ok", scope="fixture")],
        steps=[
            WorkflowStep(
                id="fixture",
                order=1,
                capability="fixture.ok",
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            )
        ],
    )


def test_successful_step_attempt_and_checkpoint_survive_service_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "workflow.db"
    service = WorkflowService(database_path)
    definition = _definition()
    service.create(definition, idempotency_key="create-durable")
    service.register_capability(
        "fixture.ok",
        lambda _arguments: CapabilityResult(
            capability="fixture.ok",
            succeeded=True,
            output={"ok": True, "secret": "never copied to checkpoint"},
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-durable",
    )

    execution = service.execution(run.id)
    attempts = service.attempts(run.id)
    checkpoints = service.checkpoints(run.id)
    assert execution.state.value == "succeeded"
    assert len(attempts) == 1
    assert attempts[0].state is WorkflowStepAttemptState.SUCCEEDED
    assert attempts[0].checkpoint_id == checkpoints[0].id
    assert len(checkpoints) == 1
    assert checkpoints[0].verified is True
    assert "secret" not in checkpoints[0].model_dump_json()

    restarted = WorkflowService(database_path)
    assert restarted.execution(run.id).state.value == "succeeded"
    assert restarted.attempts(run.id)[0].id == attempts[0].id
    assert restarted.checkpoints(run.id)[0].output_digest == checkpoints[0].output_digest


def test_failed_step_attempt_is_durable_without_verified_checkpoint(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "failed-workflow.db")
    definition = _definition()
    service.create(definition, idempotency_key="create-failed-durable")
    service.register_capability(
        "fixture.ok",
        lambda _arguments: CapabilityResult(
            capability="fixture.ok", succeeded=False, error="provider_timeout"
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-failed-durable",
    )

    assert run.state.value == "failed"
    attempts = service.attempts(run.id)
    assert len(attempts) == 1
    assert attempts[0].state is WorkflowStepAttemptState.FAILED
    assert attempts[0].error_code == "provider_timeout"
    assert service.checkpoints(run.id) == []
    assert service.execution(run.id).state.value == "failed"
