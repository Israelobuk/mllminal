"""Acceptance workflow definitions for bounded local file and spreadsheet work."""

from mllminal.workflow.contracts import (
    WorkflowApplicationRequirement,
    WorkflowBinding,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowInput,
    WorkflowInputType,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
    WorkflowVerification,
)


def build_filesystem_spreadsheet_workflow() -> WorkflowDefinition:
    """Build the provider-neutral local source-to-spreadsheet acceptance workflow.

    The workflow copies an approved local workbook into an approved destination, then
    crosses into the spreadsheet capability surface for metadata inspection and final
    output verification. Providers remain replaceable; the workflow never reads
    credentials or invokes an unrestricted shell.
    """

    return WorkflowDefinition(
        name="local filesystem to spreadsheet",
        state=WorkflowDefinitionState.ACTIVE,
        inputs=[
            WorkflowInput(name="source_path", type=WorkflowInputType.FILE),
            WorkflowInput(name="destination_path", type=WorkflowInputType.FILE),
        ],
        permissions=[
            WorkflowPermission(
                capability="filesystem.copy", scope="filesystem.write", consequential=True
            ),
            WorkflowPermission(
                capability="spreadsheet.inspect", scope="spreadsheet.read", consequential=False
            ),
            WorkflowPermission(
                capability="spreadsheet.verify_output",
                scope="spreadsheet.read",
                consequential=False,
            ),
        ],
        transitions=[
            WorkflowTransition(
                from_application_id="filesystem",
                to_application_id="spreadsheet",
                approval_required=True,
            )
        ],
        steps=[
            WorkflowStep(
                id="copy_source",
                order=1,
                capability="filesystem.copy",
                arguments={
                    "source": "$input.source_path",
                    "destination": "$input.destination_path",
                },
                approval_required=True,
                application=WorkflowApplicationRequirement(
                    application_id="filesystem",
                    application_kind="filesystem",
                    required_capabilities=["filesystem.copy"],
                    provider_hint="filesystem",
                ),
                verification=WorkflowVerification(expected={"operation": "copy"}),
            ),
            WorkflowStep(
                id="inspect_spreadsheet",
                order=2,
                capability="spreadsheet.inspect",
                depends_on=["copy_source"],
                input_bindings={
                    "path": WorkflowBinding(
                        source_step_id="copy_source",
                        source_field="destination",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="spreadsheet",
                    application_kind="spreadsheet",
                    required_capabilities=["spreadsheet.inspect"],
                    provider_candidates=[
                        "python-spreadsheet-inspection",
                        "excel-desktop",
                        "libreoffice",
                    ],
                ),
                verification=WorkflowVerification(expected={"operation": "inspect"}),
            ),
            WorkflowStep(
                id="verify_spreadsheet",
                order=3,
                capability="spreadsheet.verify_output",
                depends_on=["inspect_spreadsheet"],
                input_bindings={
                    "path": WorkflowBinding(
                        source_step_id="inspect_spreadsheet",
                        source_field="path",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="spreadsheet",
                    application_kind="spreadsheet",
                    required_capabilities=["spreadsheet.verify_output"],
                    provider_candidates=[
                        "python-spreadsheet-inspection",
                        "excel-desktop",
                        "libreoffice",
                    ],
                ),
                verification=WorkflowVerification(expected={"exists": True, "non_empty": True}),
            ),
        ],
    )
