from pathlib import Path

import pytest

from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRollbackPlanState,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def test_rollback_requires_typed_approval_and_runs_verified_effects_in_reverse(
    tmp_path: Path,
) -> None:
    service = WorkflowService(tmp_path / "rollback.db")
    rollback_calls: list[str] = []
    definition = WorkflowDefinition(
        name="rollback fixture",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[
            WorkflowPermission(capability="fixture.first", scope="fixture"),
            WorkflowPermission(capability="fixture.second", scope="fixture"),
        ],
        steps=[
            WorkflowStep(
                id="first",
                order=1,
                capability="fixture.first",
                rollback_capability="fixture.undo_first",
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            ),
            WorkflowStep(
                id="second",
                order=2,
                capability="fixture.second",
                depends_on=["first"],
                rollback_capability="fixture.undo_second",
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            ),
        ],
    )
    service.create(definition, idempotency_key="create-rollback")
    for capability in ("fixture.first", "fixture.second"):
        service.register_capability(
            capability,
            lambda _arguments, name=capability: CapabilityResult(
                capability=name, succeeded=True, output={"ok": True}
            ),
        )
    service.register_capability(
        "fixture.undo_first",
        lambda _arguments: (
            rollback_calls.append("first")
            or CapabilityResult(capability="fixture.undo_first", succeeded=True)
        ),
    )
    service.register_capability(
        "fixture.undo_second",
        lambda _arguments: (
            rollback_calls.append("second")
            or CapabilityResult(capability="fixture.undo_second", succeeded=True)
        ),
    )

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-rollback",
    )
    plan = service.propose_rollback(run.id, reason="fixture recovery")

    assert plan.state is WorkflowRollbackPlanState.PROPOSED
    assert [step.step_id for step in plan.steps] == ["second", "first"]
    assert all(step.source_attempt_id for step in plan.steps)
    with pytest.raises(PermissionError, match="approval"):
        service.execute_rollback(plan.id, idempotency_key="execute-before-approval")

    approved = service.approve_rollback(plan.id, approved=True, idempotency_key="approve-rollback")
    assert approved.state is WorkflowRollbackPlanState.APPROVED
    rolled_back = service.execute_rollback(plan.id, idempotency_key="execute-rollback")

    assert rolled_back.state.value == "rolled_back"
    assert rolled_back.rollback_state == "complete"
    assert rollback_calls == ["second", "first"]
    assert service.rollback_plan(plan.id).state is WorkflowRollbackPlanState.EXECUTED
