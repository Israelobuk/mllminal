from pathlib import Path

from mllminal.apps.contracts import CapabilityRequest
from mllminal.apps.filesystem import FilesystemAdapter
from mllminal.workflow.acceptance import (
    build_document_pdf_workflow,
    build_file_intake_organize_workflow,
    build_report_email_draft_workflow,
)
from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowRunRequest,
)
from mllminal.workflow.service import WorkflowService


def test_document_pdf_workflow_stops_at_verified_bounded_pdf(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    source = tmp_path / "report.docx"
    output = tmp_path / "out" / "report.pdf"
    output.parent.mkdir()
    source.write_bytes(b"bounded document fixture")

    service.register_capability(
        "filesystem.inspect",
        lambda arguments: CapabilityResult(
            capability="filesystem.inspect",
            succeeded=Path(str(arguments["path"])).is_file(),
            output={"operation": "inspect", "path": str(arguments["path"])},
        ),
    )

    def export(arguments: dict[str, object]) -> CapabilityResult:
        destination = Path(str(arguments["output_path"]))
        destination.write_bytes(b"%PDF-1.7\n% bounded fixture\n")
        return CapabilityResult(
            capability="document.export_pdf",
            succeeded=True,
            output={"operation": "export_pdf", "path": str(destination)},
        )

    service.register_capability("document.export_pdf", export)
    service.register_capability(
        "document.verify_pdf",
        lambda arguments: CapabilityResult(
            capability="document.verify_pdf",
            succeeded=Path(str(arguments["path"])).read_bytes().startswith(b"%PDF-"),
            output={
                "path": str(arguments["path"]),
                "valid": Path(str(arguments["path"])).read_bytes().startswith(b"%PDF-"),
            },
        ),
    )
    service.register_transition(
        "filesystem",
        "document",
        lambda _arguments: CapabilityResult(
            capability="application.transition", succeeded=True, output={"connected": True}
        ),
    )

    definition = build_document_pdf_workflow()
    service.create(definition, idempotency_key="create-document-pdf")
    service.activate(definition.id, idempotency_key="activate-document-pdf")
    pending = service.run(
        definition.id,
        WorkflowRunRequest(
            inputs={"source_path": str(source), "output_path": str(output)}, preview=False
        ),
        idempotency_key="run-document-pdf",
    )
    run = service.approve(pending.id, True, idempotency_key="approve-document-pdf")

    assert run.state.value == "succeeded"
    assert output.read_bytes().startswith(b"%PDF-")
    assert run.step_results[-1].verification.state is VerificationState.PASSED


def test_report_email_workflow_never_registers_or_executes_send(tmp_path: Path) -> None:
    service = WorkflowService(tmp_path / "workflow.db")
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.7\n")
    calls: list[str] = []

    service.register_capability(
        "document.verify_pdf",
        lambda arguments: CapabilityResult(
            capability="document.verify_pdf",
            succeeded=Path(str(arguments["path"])).is_file(),
            output={"path": str(arguments["path"]), "valid": True},
        ),
    )

    def email_step(arguments: dict[str, object], capability: str) -> CapabilityResult:
        calls.append(capability)
        draft_id = str(arguments.get("draft_id", "draft-1"))
        return CapabilityResult(
            capability=capability,
            succeeded=True,
            output={"draft_id": draft_id, "draft": True, "sent": False},
        )

    for capability in (
        "email.create_draft",
        "email.set_recipients",
        "email.set_subject",
        "email.set_body",
        "email.attach_file",
    ):
        service.register_capability(
            capability, lambda arguments, name=capability: email_step(arguments, name)
        )
    service.register_capability(
        "email.verify_draft",
        lambda arguments: CapabilityResult(
            capability="email.verify_draft",
            succeeded=True,
            output={"draft_id": str(arguments["draft_id"]), "draft": True, "sent": False},
        ),
    )
    service.register_transition(
        "document",
        "email",
        lambda _arguments: CapabilityResult(
            capability="application.transition", succeeded=True, output={"connected": True}
        ),
    )
    service.register_verifier(
        "email.verify_draft",
        lambda result: VerificationResult(
            state=VerificationState.PASSED
            if result.output.get("draft") is True and result.output.get("sent") is False
            else VerificationState.FAILED,
            reason="Draft is saved for review and remains unsent",
            observed=result.output,
        ),
    )

    definition = build_report_email_draft_workflow()
    assert "email.send" not in {step.capability for step in definition.steps}
    service.create(definition, idempotency_key="create-report-email")
    service.activate(definition.id, idempotency_key="activate-report-email")
    pending = service.run(
        definition.id,
        WorkflowRunRequest(
            inputs={
                "report_path": str(report),
                "recipient": "reviewer@example.com",
                "subject": "Weekly report",
                "body": "Please review the attached report.",
            },
            preview=False,
        ),
        idempotency_key="run-report-email",
    )
    run = service.approve(pending.id, True, idempotency_key="approve-report-email")

    assert run.state.value == "succeeded"
    assert calls == [
        "email.create_draft",
        "email.set_recipients",
        "email.set_subject",
        "email.set_body",
        "email.attach_file",
    ]
    assert run.step_results[-1].capability_result is not None
    assert run.step_results[-1].capability_result.output["sent"] is False


def test_file_intake_workflow_organizes_latest_file_inside_workspace(tmp_path: Path) -> None:
    intake = tmp_path / "intake"
    organized = tmp_path / "organized"
    intake.mkdir()
    organized.mkdir()
    source = intake / "latest.txt"
    destination = organized / "latest.txt"
    source.write_text("bounded intake", encoding="utf-8")
    adapter = FilesystemAdapter(tmp_path)
    service = WorkflowService(tmp_path / "workflow.db")

    def execute(arguments: dict[str, object], capability: str) -> CapabilityResult:
        result = __import__("asyncio").run(
            adapter.execute(
                CapabilityRequest(
                    capability=capability,
                    arguments=arguments,
                    preview=False,
                )
            )
        )
        return CapabilityResult(
            capability=result.capability,
            succeeded=result.succeeded,
            output=result.output,
            error=result.error,
        )

    for capability in ("filesystem.find_latest", "filesystem.move", "filesystem.inspect"):
        service.register_capability(
            capability, lambda arguments, name=capability: execute(arguments, name)
        )
    for capability in ("filesystem.find_latest", "filesystem.move", "filesystem.inspect"):
        service.register_verifier(
            capability,
            lambda result: VerificationResult(
                state=VerificationState.PASSED if result.succeeded else VerificationState.FAILED,
                reason="Filesystem state is verified inside the workspace",
                observed=result.output,
            ),
        )

    definition = build_file_intake_organize_workflow()
    service.create(definition, idempotency_key="create-file-intake")
    service.activate(definition.id, idempotency_key="activate-file-intake")
    pending = service.run(
        definition.id,
        WorkflowRunRequest(
            inputs={
                "intake_folder": str(intake),
                "destination_path": str(destination),
            },
            preview=False,
        ),
        idempotency_key="run-file-intake",
    )
    run = service.approve(pending.id, True, idempotency_key="approve-file-intake")

    assert run.state.value == "succeeded"
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "bounded intake"
    assert destination.is_relative_to(tmp_path)
