import asyncio
import zipfile
from pathlib import Path

from mllminal.apps.contracts import CapabilityRequest
from mllminal.apps.filesystem import FilesystemAdapter
from mllminal.providers.contracts import AbstractCapability, ProviderRequest
from mllminal.providers.spreadsheets import PythonSpreadsheetInspectionProvider
from mllminal.workflow.acceptance import build_filesystem_spreadsheet_workflow
from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowDefinitionState,
    WorkflowRunRequest,
)
from mllminal.workflow.service import WorkflowService


def _make_workbook(path: Path) -> None:
    relationships_namespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    workbook = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheets><sheet name="Data" sheetId="1" r:id="rId1"
    xmlns:r="{relationships_namespace}" /></sheets>
</workbook>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)


def test_filesystem_spreadsheet_workflow_declares_bounded_cross_app_contract() -> None:
    definition = build_filesystem_spreadsheet_workflow()

    assert definition.state is WorkflowDefinitionState.ACTIVE
    assert [step.id for step in definition.steps] == [
        "copy_source",
        "inspect_spreadsheet",
        "verify_spreadsheet",
    ]
    assert definition.transitions[0].from_application_id == "filesystem"
    assert definition.transitions[0].to_application_id == "spreadsheet"
    assert definition.steps[1].input_bindings["path"].source_step_id == "copy_source"
    assert definition.steps[2].input_bindings["path"].source_step_id == "inspect_spreadsheet"
    assert all(step.application is not None for step in definition.steps)


def test_filesystem_spreadsheet_workflow_copies_and_verifies_inside_workspace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.xlsx"
    destination = tmp_path / "output" / "report.xlsx"
    destination.parent.mkdir()
    _make_workbook(source)
    adapter = FilesystemAdapter(tmp_path)
    inspector = PythonSpreadsheetInspectionProvider()
    service = WorkflowService(tmp_path / "workflow.db")

    def copy(arguments: dict[str, object]) -> CapabilityResult:
        result = asyncio.run(
            adapter.execute(
                CapabilityRequest(
                    capability="filesystem.copy",
                    arguments={
                        "source": arguments["source"],
                        "destination": arguments["destination"],
                    },
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

    def inspect(arguments: dict[str, object]) -> CapabilityResult:
        result = asyncio.run(
            inspector.execute(
                ProviderRequest(
                    capability=AbstractCapability.SPREADSHEET_INSPECT,
                    arguments={"path": arguments["path"]},
                )
            )
        )
        return CapabilityResult(
            capability="spreadsheet.inspect",
            succeeded=result.succeeded,
            output=result.output,
            error=result.error,
        )

    service.register_capability("filesystem.copy", copy)
    service.register_capability("spreadsheet.inspect", inspect)
    service.register_capability(
        "spreadsheet.verify_output",
        lambda arguments: CapabilityResult(
            capability="spreadsheet.verify_output",
            succeeded=Path(str(arguments["path"])).is_file(),
            output={
                "path": str(arguments["path"]),
                "exists": Path(str(arguments["path"])).is_file(),
                "non_empty": Path(str(arguments["path"])).stat().st_size > 0
                if Path(str(arguments["path"])).is_file()
                else False,
            },
        ),
    )
    service.register_transition(
        "filesystem",
        "spreadsheet",
        lambda _arguments: CapabilityResult(
            capability="application.transition", succeeded=True, output={"connected": True}
        ),
    )
    service.register_verifier(
        "filesystem.copy",
        lambda result: VerificationResult(
            state=(
                VerificationState.PASSED
                if result.succeeded and Path(str(result.output["destination"])).is_file()
                else VerificationState.FAILED
            ),
            reason="Copied output exists inside the approved workspace"
            if result.succeeded and Path(str(result.output["destination"])).is_file()
            else "Copied output is missing",
            observed=result.output,
        ),
    )
    service.register_verifier(
        "spreadsheet.inspect",
        lambda result: VerificationResult(
            state=(
                VerificationState.PASSED
                if result.succeeded and result.output.get("sheets") == ["Data"]
                else VerificationState.FAILED
            ),
            reason="Workbook metadata was independently inspected"
            if result.succeeded and result.output.get("sheets") == ["Data"]
            else "Workbook metadata inspection failed",
            observed=result.output,
        ),
    )
    service.register_verifier(
        "spreadsheet.verify_output",
        lambda result: VerificationResult(
            state=VerificationState.PASSED
            if result.succeeded and result.output.get("non_empty") is True
            else VerificationState.FAILED,
            reason="Spreadsheet output is present and non-empty",
            observed=result.output,
        ),
    )

    definition = build_filesystem_spreadsheet_workflow()
    service.create(definition, idempotency_key="create-filesystem-spreadsheet")
    service.activate(definition.id, idempotency_key="activate-filesystem-spreadsheet")
    pending = service.run(
        definition.id,
        WorkflowRunRequest(
            inputs={"source_path": str(source), "destination_path": str(destination)},
            preview=False,
        ),
        idempotency_key="run-filesystem-spreadsheet",
    )
    run = service.approve(pending.id, True, idempotency_key="approve-filesystem-spreadsheet")

    assert run.state.value == "succeeded"
    assert destination.is_file()
    assert [item.verification.state for item in run.step_results] == [
        VerificationState.PASSED,
        VerificationState.PASSED,
        VerificationState.PASSED,
    ]
    assert all(
        Path(str(item.capability_result.output["path"])).is_relative_to(tmp_path)
        for item in run.step_results[1:]
    )
