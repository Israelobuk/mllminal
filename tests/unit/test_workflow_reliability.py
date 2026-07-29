from pathlib import Path

from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRetryPolicy,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def test_retry_policy_retries_only_declared_transient_failure(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "retry.db")
    calls = 0

    def handler(_arguments: dict[str, object]) -> CapabilityResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            return CapabilityResult(
                capability="fixture.retry", succeeded=False, error="temporary_failure"
            )
        return CapabilityResult(capability="fixture.retry", succeeded=True, output={"ok": True})

    definition = WorkflowDefinition(
        name="bounded retry",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="fixture.retry", scope="fixture")],
        steps=[
            WorkflowStep(
                id="retry",
                order=1,
                capability="fixture.retry",
                approval_required=False,
                retry_policy=WorkflowRetryPolicy(
                    max_attempts=2, retryable_errors=["temporary_failure"]
                ),
                verification=WorkflowVerification(expected={"ok": True}),
            )
        ],
    )
    service.create(definition, idempotency_key="create-retry")
    service.register_capability("fixture.retry", handler)

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-retry",
    )

    assert run.state.value == "succeeded"
    assert calls == 2
    attempts = service.attempts(run.id)
    assert [(item.attempt_number, item.state.value) for item in attempts] == [
        (1, "failed"),
        (2, "succeeded"),
    ]
    assert service._cached(f"{run.id}:retry", "workflow.step.execute") is not None


def test_independent_verifier_can_reject_successful_provider_output(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "verify.db")
    definition = WorkflowDefinition(
        name="independent verification",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="fixture.write", scope="fixture")],
        steps=[
            WorkflowStep(
                id="write",
                order=1,
                capability="fixture.write",
                approval_required=False,
                verification=WorkflowVerification(expected={"written": True}),
            )
        ],
    )
    service.create(definition, idempotency_key="create-verify")
    service.register_capability(
        "fixture.write",
        lambda _arguments: CapabilityResult(
            capability="fixture.write", succeeded=True, output={"written": True}
        ),
    )
    service.register_verifier(
        "fixture.write",
        lambda _result: VerificationResult(
            state=VerificationState.FAILED,
            reason="independent observer found no durable effect",
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-verify",
    )

    assert run.state.value == "failed"
    assert run.step_results[0].verification.reason == "independent observer found no durable effect"
    assert service.checkpoints(run.id) == []
