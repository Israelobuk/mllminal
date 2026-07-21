"""Durable, explicit workflow repair proposals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mllminal.contracts import new_id
from mllminal.repair.contracts import (
    RepairApprovalRequest,
    RepairChange,
    RepairFailureClass,
    RepairProposal,
    RepairProposalRequest,
    RepairResult,
)
from mllminal.workflow.contracts import WorkflowDefinition, WorkflowPermission
from mllminal.workflow.service import WorkflowService

_FAILURE_MARKERS = {
    "target": RepairFailureClass.TARGET_NOT_FOUND,
    "not_found": RepairFailureClass.TARGET_NOT_FOUND,
    "application": RepairFailureClass.APPLICATION_NOT_AVAILABLE,
    "permission": RepairFailureClass.PERMISSION_DENIED,
    "input": RepairFailureClass.INPUT_MISSING,
    "state": RepairFailureClass.STATE_MISMATCH,
    "verification": RepairFailureClass.VERIFICATION_FAILED,
    "collision": RepairFailureClass.FILE_COLLISION,
    "timeout": RepairFailureClass.TIMEOUT,
    "cancel": RepairFailureClass.USER_CANCELLED,
    "emergency": RepairFailureClass.EMERGENCY_STOPPED,
    "capability_not_registered": RepairFailureClass.APPLICATION_NOT_AVAILABLE,
}


class WorkflowRepairService:
    def __init__(self, workflow: WorkflowService, data_dir: Path) -> None:
        self.workflow = workflow
        self.path = data_dir
        self.path.mkdir(parents=True, exist_ok=True)

    def propose(self, request: RepairProposalRequest) -> RepairProposal:
        run = self.workflow.run_record(request.run_id)
        definition = self.workflow.definition(run.workflow_id)
        failure_class = self._classify(run, request.diagnostics)
        changes = self._changes(run, request.diagnostics)
        preview = self._preview(definition, changes)
        proposal = RepairProposal(
            run_id=run.id,
            workflow_id=definition.id,
            source_workflow_version=definition.version,
            failure_class=failure_class,
            explanation=self._explanation(failure_class, changes),
            diagnostics=request.diagnostics,
            changes=changes,
            preview_workflow=preview,
        )
        self._save(proposal)
        return proposal

    def approve(self, proposal_id: str, request: RepairApprovalRequest) -> RepairResult:
        proposal = self._load(proposal_id)
        if proposal.status != "proposed":
            raise RuntimeError("Repair proposal is no longer pending approval")
        if not request.approved:
            rejected = proposal.model_copy(update={"status": "rejected"})
            self._save(rejected)
            return RepairResult(proposal=rejected)
        if not proposal.changes:
            raise PermissionError("Repair approval requires an explicit typed change")
        workflow = self.workflow.create(
            proposal.preview_workflow,
            idempotency_key=f"repair-create-{proposal.id}",
        )
        approved = proposal.model_copy(
            update={"status": "approved", "approved_workflow_id": workflow.id}
        )
        self._save(approved)
        return RepairResult(proposal=approved, workflow=workflow)

    def _load(self, proposal_id: str) -> RepairProposal:
        if Path(proposal_id).name != proposal_id:
            raise ValueError("invalid_repair_proposal_id")
        path = self.path / f"{proposal_id}.json"
        if not path.exists():
            raise KeyError(proposal_id)
        return RepairProposal.model_validate_json(path.read_text(encoding="utf-8"))

    def _save(self, proposal: RepairProposal) -> None:
        path = self.path / f"{proposal.id}.json"
        tmp = path.with_name(path.name + ".next")
        tmp.write_text(proposal.model_dump_json(), encoding="utf-8", newline="")
        tmp.replace(path)

    @staticmethod
    def _classify(run: Any, diagnostics: dict[str, Any]) -> RepairFailureClass:
        marker = str(diagnostics.get("failure_class", "")).casefold()
        if marker:
            for value in RepairFailureClass:
                if value.value == marker:
                    return value
        error = " ".join(
            str(item.capability_result.error or "")
            for item in run.step_results
            if item.capability_result is not None
        ).casefold()
        for marker, failure in _FAILURE_MARKERS.items():
            if marker in error:
                return failure
        return RepairFailureClass.ADAPTER_CRASHED

    @staticmethod
    def _changes(run: Any, diagnostics: dict[str, Any]) -> list[RepairChange]:
        failed = next((item for item in run.step_results if item.state == "failed"), None)
        replacement = diagnostics.get("replacement_capability")
        if failed is None or not isinstance(replacement, str) or not replacement:
            return []
        old = failed.capability_result.capability if failed.capability_result else None
        return [
            RepairChange(
                step_id=failed.step_id,
                field="capability",
                old_value=old,
                new_value=replacement,
                reason="Use the explicitly selected bounded adapter capability",
            )
        ]

    @staticmethod
    def _preview(definition: WorkflowDefinition, changes: list[RepairChange]) -> WorkflowDefinition:
        steps = list(definition.steps)
        permissions = list(definition.permissions)
        for change in changes:
            step = next((item for item in steps if item.id == change.step_id), None)
            if (
                step is None
                or change.field != "capability"
                or not isinstance(change.new_value, str)
            ):
                continue
            updated = step.model_copy(
                update={
                    "capability": change.new_value,
                    "approval_required": True,
                    "verification": step.verification,
                }
            )
            steps[steps.index(step)] = updated
            scope = WorkflowRepairService._scope(change.new_value)
            permissions = [item for item in permissions if item.capability != step.capability]
            permissions.append(
                WorkflowPermission(
                    capability=change.new_value,
                    scope=scope,
                    consequential=True,
                )
            )
        return WorkflowDefinition(
            id=new_id(),
            name=definition.name,
            version=definition.version + 1,
            parent_workflow_id=definition.id,
            inputs=definition.inputs,
            permissions=permissions,
            steps=steps,
        )

    @staticmethod
    def _scope(capability: str) -> str:
        if capability.startswith("filesystem."):
            return "filesystem.write"
        if capability.startswith("spreadsheet."):
            return "spreadsheet.export"
        if capability.startswith("email."):
            return "email.draft"
        return "workflow.repair"

    @staticmethod
    def _explanation(failure: RepairFailureClass, changes: list[RepairChange]) -> str:
        if changes:
            return (
                f"The run failed with {failure.value}; a typed capability replacement "
                "is proposed for approval."
            )
        return (
            f"The run failed with {failure.value}; bounded diagnostics were preserved, "
            "but no safe automatic change was inferred."
        )
