from pathlib import Path

from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def test_provider_neutral_verification_strategy_is_used_for_unknown_capability(
    tmp_path: Path,
) -> None:
    service = WorkflowService(tmp_path / "verification.db")
    definition = WorkflowDefinition(
        name="generic verification fixture",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="fixture.generic", scope="application.write")],
        steps=[
            WorkflowStep(
                id="generic",
                order=1,
                capability="fixture.generic",
                approval_required=False,
                verification=WorkflowVerification(kind="bounded_output"),
            )
        ],
    )
    service.create(definition, idempotency_key="create-generic-verification")
    service.register_capability(
        "fixture.generic",
        lambda _arguments: CapabilityResult(
            capability="fixture.generic",
            succeeded=True,
            output={"provider_state": "ready"},
        ),
    )
    service.register_verification_kind(
        "bounded_output",
        lambda result: VerificationResult(
            state=(
                VerificationState.PASSED
                if result.output.get("provider_state") == "ready"
                else VerificationState.FAILED
            ),
            reason="Generic provider state was independently checked",
            observed={"provider_state": result.output.get("provider_state")},
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-generic-verification",
    )

    assert run.state.value == "succeeded"
    assert run.step_results[0].verification.state is VerificationState.PASSED


def test_recovery_runs_only_after_approval_and_checks_generic_rollback_output(
    tmp_path: Path,
) -> None:
    service = WorkflowService(tmp_path / "recovery.db")
    definition = WorkflowDefinition(
        name="generic recovery fixture",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[WorkflowPermission(capability="fixture.effect", scope="application.write")],
        steps=[
            WorkflowStep(
                id="effect",
                order=1,
                capability="fixture.effect",
                approval_required=False,
                rollback_capability="fixture.undo",
                verification=WorkflowVerification(expected={"ok": True}),
                rollback_verification=WorkflowVerification(
                    kind="exact_fields", expected={"restored": True}
                ),
            )
        ],
    )
    service.create(definition, idempotency_key="create-generic-recovery")
    service.register_capability(
        "fixture.effect",
        lambda _arguments: CapabilityResult(
            capability="fixture.effect", succeeded=True, output={"ok": True}
        ),
    )
    service.register_capability(
        "fixture.undo",
        lambda _arguments: CapabilityResult(
            capability="fixture.undo", succeeded=True, output={"restored": True}
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-generic-recovery",
    )
    plan = service.propose_rollback(run.id, reason="generic recovery")
    approved = service.approve_rollback(
        plan.id, approved=True, idempotency_key="approve-generic-recovery"
    )
    assert approved.state.value == "approved"

    rolled_back = service.execute_rollback(plan.id, idempotency_key="execute-generic-recovery")

    assert rolled_back.rollback_state == "complete"
    assert rolled_back.state.value == "rolled_back"
