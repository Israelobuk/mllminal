from pathlib import Path

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


def test_resume_skips_verified_steps_and_retries_only_incomplete_step(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    first_calls = 0
    second_calls = 0
    fail_second = True

    def first(_arguments: dict[str, object]) -> CapabilityResult:
        nonlocal first_calls
        first_calls += 1
        return CapabilityResult(capability="fixture.first", succeeded=True, output={"ok": True})

    def second(_arguments: dict[str, object]) -> CapabilityResult:
        nonlocal second_calls, fail_second
        second_calls += 1
        if fail_second:
            fail_second = False
            return CapabilityResult(
                capability="fixture.second", succeeded=False, error="temporary_failure"
            )
        return CapabilityResult(capability="fixture.second", succeeded=True, output={"done": True})

    definition = WorkflowDefinition(
        name="resumable fixture",
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
                approval_required=False,
                verification=WorkflowVerification(expected={"ok": True}),
            ),
            WorkflowStep(
                id="second",
                order=2,
                capability="fixture.second",
                depends_on=["first"],
                approval_required=False,
                verification=WorkflowVerification(expected={"done": True}),
            ),
        ],
    )
    service.create(definition, idempotency_key="create-resume")
    service.register_capability("fixture.first", first)
    service.register_capability("fixture.second", second)

    failed = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-resume",
    )
    assert failed.state.value == "failed"
    assert first_calls == 1
    assert second_calls == 1

    restarted = WorkflowService(tmp_path / "workflow.db")
    restarted.register_capability("fixture.first", first)
    restarted.register_capability("fixture.second", second)
    resumed = restarted.resume(failed.id, idempotency_key="resume-run")

    assert resumed.state.value == "succeeded"
    assert first_calls == 1
    assert second_calls == 2
    attempts = restarted.attempts(failed.id)
    assert [(attempt.step_id, attempt.attempt_number) for attempt in attempts] == [
        ("first", 1),
        ("second", 1),
        ("second", 2),
    ]
    assert len(restarted.checkpoints(failed.id)) == 2
    assert restarted.execution(failed.id).state.value == "succeeded"
