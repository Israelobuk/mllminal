import pytest
from pydantic import ValidationError

from mllminal.workflow.contracts import (
    WorkflowApplicationRequirement,
    WorkflowBinding,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAttempt,
    WorkflowStepAttemptState,
    WorkflowVerification,
)


def test_cross_application_definition_preserves_typed_dependencies_and_bindings() -> None:
    definition = WorkflowDefinition(
        name="browser to spreadsheet",
        permissions=[
            WorkflowPermission(capability="browser.capture", scope="browser"),
            WorkflowPermission(capability="spreadsheet.write", scope="spreadsheet"),
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
                ),
                approval_required=False,
                verification=WorkflowVerification(expected={"captured": True}),
            ),
            WorkflowStep(
                id="write",
                order=2,
                capability="spreadsheet.write",
                depends_on=["capture"],
                input_bindings={
                    "rows": WorkflowBinding(
                        source_step_id="capture",
                        source_field="rows",
                        target_type="previous_output",
                    )
                },
                application=WorkflowApplicationRequirement(
                    application_id="spreadsheet",
                    application_kind="spreadsheet",
                    required_capabilities=["spreadsheet.write"],
                ),
                approval_required=False,
                verification=WorkflowVerification(expected={"written": True}),
            ),
        ],
    )

    assert definition.steps[1].depends_on == ["capture"]
    assert definition.steps[1].input_bindings["rows"].target_type.value == "previous_output"
    assert definition.steps[0].application.application_kind == "browser"
    assert definition.steps[1].application.application_kind == "spreadsheet"


def test_cross_application_definition_rejects_unknown_dependency_and_cycles() -> None:
    with pytest.raises(ValidationError, match="unknown workflow step dependency"):
        WorkflowDefinition(
            name="unknown dependency",
            permissions=[WorkflowPermission(capability="fixture.ok", scope="fixture")],
            steps=[
                WorkflowStep(order=1, capability="fixture.ok", depends_on=["missing"]),
            ],
        )

    with pytest.raises(ValidationError, match="workflow step dependencies must be acyclic"):
        WorkflowDefinition(
            name="cyclic workflow",
            permissions=[
                WorkflowPermission(capability="fixture.a", scope="fixture"),
                WorkflowPermission(capability="fixture.b", scope="fixture"),
            ],
            steps=[
                WorkflowStep(id="a", order=1, capability="fixture.a", depends_on=["b"]),
                WorkflowStep(id="b", order=2, capability="fixture.b", depends_on=["a"]),
            ],
        )


def test_execution_attempt_and_checkpoint_contracts_are_restart_safe() -> None:
    execution = WorkflowExecution(
        workflow_id="workflow-1",
        workflow_version=3,
        state=WorkflowExecutionState.RUNNING,
        current_step_id="write",
        completed_step_ids=["capture"],
        last_checkpoint_id="checkpoint-1",
    )
    attempt = WorkflowStepAttempt(
        execution_id=execution.id,
        step_id="write",
        attempt_number=1,
        state=WorkflowStepAttemptState.SUCCEEDED,
        provider_id="spreadsheet.local",
        idempotency_key="execution-1:write:1",
        checkpoint_id="checkpoint-1",
    )
    checkpoint = WorkflowCheckpoint(
        id="checkpoint-1",
        execution_id=execution.id,
        step_id="write",
        attempt_id=attempt.id,
        sequence=2,
        state=WorkflowStepAttemptState.SUCCEEDED,
        input_digest="sha256:input",
        output_digest="sha256:output",
        verified=True,
    )

    restored = WorkflowExecution.model_validate_json(execution.model_dump_json())
    assert restored.last_checkpoint_id == checkpoint.id
    assert attempt.idempotency_key == "execution-1:write:1"
    assert checkpoint.verified is True
    assert checkpoint.output_digest == "sha256:output"


def test_execution_contracts_reject_unmodeled_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowExecution(
            workflow_id="workflow-1",
            workflow_version=1,
            state=WorkflowExecutionState.CREATED,
            secret_value="must not be persisted",
        )
