from datetime import UTC, datetime

from mllminal.compiler.contracts import CompilerRequest
from mllminal.compiler.service import WorkflowCompilerService
from mllminal.mining.contracts import MinedStep, WorkflowCandidate


def test_compiler_maps_control_actions_without_application_name_branching() -> None:
    candidate = WorkflowCandidate(
        application="unfamiliar-reporting-tool",
        steps=[
            MinedStep(
                application="unfamiliar-reporting-tool",
                kind="control.invoked",
                action_type="Export report",
            ),
            MinedStep(
                application="unfamiliar-reporting-tool",
                kind="control.invoked",
                action_type="Create draft",
            ),
        ],
        occurrences=2,
        confidence=0.9,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
    )

    result = WorkflowCompilerService().compile(
        CompilerRequest(name="unfamiliar app workflow", candidates=[candidate])
    )

    assert [step.capability for step in result.workflow.steps] == [
        "document.export",
        "draft.create",
    ]
    assert {item.scope for item in result.permission_manifest} == {
        "document.write",
        "draft.write",
    }
    assert result.unsupported_steps == []
