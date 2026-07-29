from pathlib import Path

from mllminal.workflow.contracts import (
    CapabilityResult,
    WorkflowApplicationRequirement,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowPermission,
    WorkflowRunRequest,
    WorkflowStep,
    WorkflowTransition,
    WorkflowVerification,
)
from mllminal.workflow.service import WorkflowService


def test_workflow_runs_declared_application_transition_and_step_provider(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    calls: list[str] = []

    service.register_backend(
        "browser.capture",
        "browser.native",
        lambda _arguments: (
            calls.append("browser.native")
            or CapabilityResult(
                capability="browser.capture", succeeded=True, output={"captured": True}
            )
        ),
    )
    service.register_backend(
        "spreadsheet.write",
        "spreadsheet.native",
        lambda _arguments: (
            calls.append("spreadsheet.native")
            or CapabilityResult(
                capability="spreadsheet.write", succeeded=True, output={"written": True}
            )
        ),
    )
    service.register_transition(
        "browser",
        "spreadsheet",
        lambda arguments: (
            calls.append(
                f"transition:{arguments['from_application']}->{arguments['to_application']}"
            )
            or CapabilityResult(
                capability="application.transition", succeeded=True, output={"connected": True}
            )
        ),
    )
    definition = WorkflowDefinition(
        name="browser to spreadsheet",
        state=WorkflowDefinitionState.ACTIVE,
        permissions=[
            WorkflowPermission(capability="browser.capture", scope="browser"),
            WorkflowPermission(capability="spreadsheet.write", scope="spreadsheet"),
        ],
        transitions=[
            WorkflowTransition(
                from_application_id="browser",
                to_application_id="spreadsheet",
                approval_required=False,
            )
        ],
        steps=[
            WorkflowStep(
                id="capture",
                order=1,
                capability="browser.capture",
                application=WorkflowApplicationRequirement(
                    application_id="browser",
                    application_kind="browser",
                    required_capabilities=["browser.capture"],
                    provider_candidates=["browser.native"],
                ),
                approval_required=False,
                verification=WorkflowVerification(expected={"captured": True}),
            ),
            WorkflowStep(
                id="write",
                order=2,
                capability="spreadsheet.write",
                depends_on=["capture"],
                application=WorkflowApplicationRequirement(
                    application_id="spreadsheet",
                    application_kind="spreadsheet",
                    required_capabilities=["spreadsheet.write"],
                    provider_candidates=["spreadsheet.native"],
                ),
                approval_required=False,
                verification=WorkflowVerification(expected={"written": True}),
            ),
        ],
    )
    service.create(definition, idempotency_key="create-transition")

    run = service.run(
        definition.id,
        WorkflowRunRequest(preview=False),
        idempotency_key="run-transition",
    )

    assert run.state.value == "succeeded"
    assert calls == ["browser.native", "transition:browser->spreadsheet", "spreadsheet.native"]
    assert [attempt.provider_id for attempt in service.attempts(run.id)] == [
        "browser.native",
        "spreadsheet.native",
    ]
