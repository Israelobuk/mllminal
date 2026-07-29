from pathlib import Path

from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowInput,
    WorkflowInputType,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def test_workflow_executes_dependencies_before_dependents_and_resolves_bindings(
    tmp_path: Path,
) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    calls: list[str] = []
    received: list[dict[str, object]] = []

    service.register_capability(
        "browser.capture",
        lambda _arguments: (
            calls.append("capture")
            or CapabilityResult(
                capability="browser.capture",
                succeeded=True,
                output={"rows": [{"name": "Ada"}]},
            )
        ),
    )

    def write(arguments: dict[str, object]) -> CapabilityResult:
        calls.append("write")
        received.append(arguments)
        return CapabilityResult(
            capability="spreadsheet.write",
            succeeded=True,
            output={"written": True},
        )

    service.register_capability("spreadsheet.write", write)
    definition = WorkflowDefinition(
        name="browser to spreadsheet",
        inputs=[WorkflowInput(name="destination", type=WorkflowInputType.PATH)],
        permissions=[
            WorkflowPermission(capability="browser.capture", scope="browser"),
            WorkflowPermission(capability="spreadsheet.write", scope="spreadsheet"),
        ],
        steps=[
            WorkflowStep(
                id="write",
                order=1,
                capability="spreadsheet.write",
                depends_on=["capture"],
                input_bindings={
                    "rows": WorkflowBinding(
                        source_step_id="capture",
                        source_field="rows",
                        target_type=WorkflowInputType.PREVIOUS_OUTPUT,
                    )
                },
                arguments={"destination": "$input.destination"},
                approval_required=False,
                verification=WorkflowVerification(expected={"written": True}),
            ),
            WorkflowStep(
                id="capture",
                order=2,
                capability="browser.capture",
                approval_required=False,
                verification=WorkflowVerification(expected={"rows": [{"name": "Ada"}]}),
            ),
        ],
    )
    service.create(definition, idempotency_key="create-dag")
    service.activate(definition.id, idempotency_key="activate-dag")

    run = service.run(
        definition.id,
        WorkflowRunRequest(inputs={"destination": "contacts.xlsx"}, preview=False),
        idempotency_key="run-dag",
    )

    assert run.state.value == "succeeded"
    assert calls == ["capture", "write"]
    assert received == [{"destination": "contacts.xlsx", "rows": [{"name": "Ada"}]}]
