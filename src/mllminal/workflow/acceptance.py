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


def build_document_pdf_workflow() -> WorkflowDefinition:
    """Build a bounded document-to-PDF workflow with explicit output verification."""

    return WorkflowDefinition(
        name="document to verified PDF",
        state=WorkflowDefinitionState.ACTIVE,
        inputs=[
            WorkflowInput(name="source_path", type=WorkflowInputType.FILE),
            WorkflowInput(name="output_path", type=WorkflowInputType.FILE),
        ],
        permissions=[
            WorkflowPermission(
                capability="filesystem.inspect", scope="filesystem.read", consequential=False
            ),
            WorkflowPermission(
                capability="document.export_pdf", scope="document.export", consequential=True
            ),
            WorkflowPermission(
                capability="document.verify_pdf", scope="document.read", consequential=False
            ),
        ],
        transitions=[
            WorkflowTransition(
                from_application_id="filesystem",
                to_application_id="document",
                approval_required=True,
            )
        ],
        steps=[
            WorkflowStep(
                id="inspect_source",
                order=1,
                capability="filesystem.inspect",
                arguments={"path": "$input.source_path"},
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="filesystem",
                    application_kind="filesystem",
                    required_capabilities=["filesystem.inspect"],
                    provider_hint="filesystem",
                ),
                verification=WorkflowVerification(expected={"operation": "inspect"}),
            ),
            WorkflowStep(
                id="export_pdf",
                order=2,
                capability="document.export_pdf",
                depends_on=["inspect_source"],
                arguments={"output_path": "$input.output_path"},
                input_bindings={
                    "source_path": WorkflowBinding(
                        source_step_id="inspect_source",
                        source_field="path",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=True,
                application=WorkflowApplicationRequirement(
                    application_id="document",
                    application_kind="document",
                    required_capabilities=["document.export_pdf"],
                    provider_candidates=[
                        "native-document",
                        "portable-document",
                        "manual-document",
                    ],
                ),
                verification=WorkflowVerification(expected={"operation": "export_pdf"}),
            ),
            WorkflowStep(
                id="verify_pdf",
                order=3,
                capability="document.verify_pdf",
                depends_on=["export_pdf"],
                input_bindings={
                    "path": WorkflowBinding(
                        source_step_id="export_pdf",
                        source_field="path",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="document",
                    application_kind="document",
                    required_capabilities=["document.verify_pdf"],
                    provider_candidates=[
                        "native-document",
                        "portable-document",
                        "manual-document",
                    ],
                ),
                verification=WorkflowVerification(expected={"valid": True}),
            ),
        ],
    )


def build_report_email_draft_workflow() -> WorkflowDefinition:
    """Build a report-to-unsent-draft workflow with no send capability."""

    email_steps = [
        ("set_recipients", "email.set_recipients", ["create_draft"]),
        ("set_subject", "email.set_subject", ["set_recipients"]),
        ("set_body", "email.set_body", ["set_subject"]),
        ("attach_report", "email.attach_file", ["set_body"]),
    ]
    steps = [
        WorkflowStep(
            id="verify_report",
            order=1,
            capability="document.verify_pdf",
            arguments={"path": "$input.report_path"},
            approval_required=False,
            application=WorkflowApplicationRequirement(
                application_id="document",
                application_kind="document",
                required_capabilities=["document.verify_pdf"],
                provider_candidates=[
                    "native-document",
                    "portable-document",
                    "manual-document",
                ],
            ),
            verification=WorkflowVerification(expected={"valid": True}),
        ),
        WorkflowStep(
            id="create_draft",
            order=2,
            capability="email.create_draft",
            depends_on=["verify_report"],
            approval_required=True,
            application=WorkflowApplicationRequirement(
                application_id="email",
                application_kind="email",
                required_capabilities=["email.create_draft"],
                provider_candidates=[
                    "outlook-classic",
                    "browser-email",
                    "system-mail-compose",
                ],
            ),
            verification=WorkflowVerification(expected={"draft": True, "sent": False}),
        ),
    ]
    for order, (step_id, capability, dependencies) in enumerate(email_steps, start=3):
        source_step_id = dependencies[0]
        argument_bindings = {
            "draft_id": WorkflowBinding(
                source_step_id=source_step_id,
                source_field="draft_id",
                target_type=WorkflowInputType.PREVIOUS_OUTPUT,
            )
        }
        arguments: dict[str, object] = {}
        if capability == "email.set_recipients":
            arguments["recipients"] = ["$input.recipient"]
        elif capability == "email.set_subject":
            arguments["subject"] = "$input.subject"
        elif capability == "email.set_body":
            arguments["body"] = "$input.body"
        else:
            arguments["path"] = "$input.report_path"
        steps.append(
            WorkflowStep(
                id=step_id,
                order=order,
                capability=capability,
                depends_on=dependencies,
                arguments=arguments,
                input_bindings=argument_bindings,
                approval_required=True,
                application=WorkflowApplicationRequirement(
                    application_id="email",
                    application_kind="email",
                    required_capabilities=[capability],
                    provider_candidates=[
                        "outlook-classic",
                        "browser-email",
                        "system-mail-compose",
                    ],
                ),
                verification=WorkflowVerification(expected={"draft": True, "sent": False}),
            )
        )
    steps.append(
        WorkflowStep(
            id="verify_draft",
            order=7,
            capability="email.verify_draft",
            depends_on=["attach_report"],
            input_bindings={
                "draft_id": WorkflowBinding(
                    source_step_id="attach_report",
                    source_field="draft_id",
                    target_type=WorkflowInputType.PREVIOUS_OUTPUT,
                )
            },
            approval_required=False,
            application=WorkflowApplicationRequirement(
                application_id="email",
                application_kind="email",
                required_capabilities=["email.verify_draft"],
                provider_candidates=["outlook-classic", "browser-email"],
            ),
            verification=WorkflowVerification(expected={"draft": True, "sent": False}),
        )
    )
    return WorkflowDefinition(
        name="report to unsent email draft",
        state=WorkflowDefinitionState.ACTIVE,
        inputs=[
            WorkflowInput(name="report_path", type=WorkflowInputType.FILE),
            WorkflowInput(name="recipient", type=WorkflowInputType.CONTACT),
            WorkflowInput(name="subject", type=WorkflowInputType.STRING),
            WorkflowInput(name="body", type=WorkflowInputType.STRING),
        ],
        permissions=[
            WorkflowPermission(
                capability="document.verify_pdf", scope="document.read", consequential=False
            ),
            WorkflowPermission(
                capability="email.create_draft", scope="email.draft", consequential=True
            ),
            *[
                WorkflowPermission(capability=capability, scope="email.draft", consequential=True)
                for _, capability, _ in email_steps
            ],
            WorkflowPermission(
                capability="email.verify_draft", scope="email.draft", consequential=False
            ),
        ],
        transitions=[
            WorkflowTransition(
                from_application_id="document",
                to_application_id="email",
                approval_required=True,
            )
        ],
        steps=steps,
    )


def build_file_intake_organize_workflow() -> WorkflowDefinition:
    """Build a confined intake-folder organization workflow."""

    return WorkflowDefinition(
        name="organize latest file intake",
        state=WorkflowDefinitionState.ACTIVE,
        inputs=[
            WorkflowInput(name="intake_folder", type=WorkflowInputType.FOLDER),
            WorkflowInput(name="destination_path", type=WorkflowInputType.FILE),
            WorkflowInput(name="pattern", type=WorkflowInputType.STRING, default="*"),
        ],
        permissions=[
            WorkflowPermission(
                capability="filesystem.find_latest", scope="filesystem.read", consequential=False
            ),
            WorkflowPermission(
                capability="filesystem.move", scope="filesystem.write", consequential=True
            ),
            WorkflowPermission(
                capability="filesystem.inspect", scope="filesystem.read", consequential=False
            ),
        ],
        steps=[
            WorkflowStep(
                id="find_latest",
                order=1,
                capability="filesystem.find_latest",
                arguments={
                    "folder": "$input.intake_folder",
                    "pattern": "$input.pattern",
                },
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="filesystem",
                    application_kind="filesystem",
                    required_capabilities=["filesystem.find_latest"],
                    provider_hint="filesystem",
                ),
                verification=WorkflowVerification(expected={"operation": "find_latest"}),
            ),
            WorkflowStep(
                id="organize_file",
                order=2,
                capability="filesystem.move",
                depends_on=["find_latest"],
                arguments={"destination": "$input.destination_path"},
                input_bindings={
                    "source": WorkflowBinding(
                        source_step_id="find_latest",
                        source_field="path",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=True,
                application=WorkflowApplicationRequirement(
                    application_id="filesystem",
                    application_kind="filesystem",
                    required_capabilities=["filesystem.move"],
                    provider_hint="filesystem",
                ),
                verification=WorkflowVerification(expected={"operation": "move"}),
            ),
            WorkflowStep(
                id="verify_organized_file",
                order=3,
                capability="filesystem.inspect",
                depends_on=["organize_file"],
                input_bindings={
                    "path": WorkflowBinding(
                        source_step_id="organize_file",
                        source_field="destination",
                        target_type=WorkflowInputType.FILE,
                    )
                },
                approval_required=False,
                application=WorkflowApplicationRequirement(
                    application_id="filesystem",
                    application_kind="filesystem",
                    required_capabilities=["filesystem.inspect"],
                    provider_hint="filesystem",
                ),
                verification=WorkflowVerification(expected={"operation": "inspect"}),
            ),
        ],
    )
