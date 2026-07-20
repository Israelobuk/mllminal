"""Contracts for explicit workflow repair proposals and versioned recovery."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now
from mllminal.workflow.contracts import WorkflowDefinition


class RepairFailureClass(StrEnum):
    TARGET_NOT_FOUND = "target_not_found"
    APPLICATION_NOT_AVAILABLE = "application_not_available"
    PERMISSION_DENIED = "permission_denied"
    INPUT_MISSING = "input_missing"
    STATE_MISMATCH = "state_mismatch"
    VERIFICATION_FAILED = "verification_failed"
    FILE_COLLISION = "file_collision"
    TIMEOUT = "timeout"
    USER_CANCELLED = "user_cancelled"
    EMERGENCY_STOPPED = "emergency_stopped"
    ADAPTER_CRASHED = "adapter_crashed"


class RepairProposalRequest(Contract):
    run_id: str
    diagnostics: dict[str, Any] = Field(default_factory=dict, max_length=32)


class RepairApprovalRequest(Contract):
    approved: bool


class RepairChange(Contract):
    step_id: str
    field: str
    old_value: Any = None
    new_value: Any = None
    reason: str


class RepairProposal(Contract):
    id: str = Field(default_factory=new_id)
    run_id: str
    workflow_id: str
    source_workflow_version: int = Field(ge=1)
    failure_class: RepairFailureClass
    explanation: str
    diagnostics: dict[str, Any] = Field(default_factory=dict, max_length=32)
    changes: list[RepairChange] = Field(default_factory=list, max_length=32)
    preview_workflow: WorkflowDefinition
    status: str = "proposed"
    created_at: datetime = Field(default_factory=utc_now)
    approved_workflow_id: str | None = None


class RepairResult(Contract):
    proposal: RepairProposal
    workflow: WorkflowDefinition | None = None
