"""Versioned contracts for typed workflow definitions and execution."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from mllminal.contracts import Contract, new_id, utc_now


class WorkflowDefinitionState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowInputType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    PATH = "path"
    FILE = "file"
    FOLDER = "folder"
    DATE = "date"
    DATETIME = "datetime"
    CONTACT = "contact"
    APPLICATION = "application"
    SELECTED_ITEM = "selected_item"
    PREVIOUS_OUTPUT = "previous_output"
    USER_CHOICE = "user_choice"


class WorkflowRunState(StrEnum):
    PREVIEW = "preview"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class VerificationState(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class WorkflowInput(Contract):
    name: str
    type: WorkflowInputType
    required: bool = True
    default: Any = None


class WorkflowPermission(Contract):
    capability: str
    scope: str
    consequential: bool = True


class WorkflowVerification(Contract):
    kind: str = "exact_fields"
    expected: dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(Contract):
    id: str = Field(default_factory=new_id)
    order: int = Field(ge=1)
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True
    rollback_capability: str | None = None
    verification: WorkflowVerification | None = None


class WorkflowDefinition(Contract):
    id: str = Field(default_factory=new_id)
    name: str
    version: int = Field(default=1, ge=1)
    state: WorkflowDefinitionState = WorkflowDefinitionState.DRAFT
    parent_workflow_id: str | None = None
    inputs: list[WorkflowInput] = Field(default_factory=list)
    permissions: list[WorkflowPermission] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_order_and_ids(self) -> "WorkflowDefinition":
        if len({step.id for step in self.steps}) != len(self.steps):
            raise ValueError("workflow step IDs must be unique")
        orders = [step.order for step in self.steps]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("workflow steps must have contiguous order values")
        capabilities = {permission.capability for permission in self.permissions}
        missing = {step.capability for step in self.steps} - capabilities
        if missing:
            raise ValueError(f"workflow permissions missing for: {sorted(missing)}")
        return self


class WorkflowCreateRequest(Contract):
    definition: WorkflowDefinition


class WorkflowRunRequest(Contract):
    inputs: dict[str, Any] = Field(default_factory=dict)
    preview: bool = True


class WorkflowApprovalRequest(Contract):
    approved: bool


class CapabilityResult(Contract):
    capability: str
    succeeded: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class VerificationResult(Contract):
    state: VerificationState
    reason: str
    observed: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepResult(Contract):
    step_id: str
    state: str
    capability_result: CapabilityResult | None = None
    verification: VerificationResult


class WorkflowRun(Contract):
    model_config = ConfigDict(extra="forbid", frozen=False)
    id: str = Field(default_factory=new_id)
    workflow_id: str
    workflow_version: int
    state: WorkflowRunState
    preview: bool
    inputs: dict[str, Any] = Field(default_factory=dict)
    current_step_order: int = 0
    pending_approval_step_id: str | None = None
    step_results: list[WorkflowStepResult] = Field(default_factory=list)
    rollback_state: str = "not_needed"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowRunEvent(Contract):
    id: str = Field(default_factory=new_id)
    run_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
