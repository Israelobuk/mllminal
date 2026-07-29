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


class WorkflowExecutionState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RECOVERABLE = "recoverable"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class WorkflowStepAttemptState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"
    SKIPPED = "skipped"


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


class WorkflowApplicationRequirement(Contract):
    """The bounded application surface required by one workflow step."""

    application_id: str
    application_kind: str
    required_capabilities: list[str] = Field(min_length=1)
    provider_hint: str | None = None
    provider_candidates: list[str] = Field(default_factory=list)


class WorkflowBinding(Contract):
    """A typed value binding from a completed dependency into a step input."""

    source_step_id: str
    source_field: str
    target_type: WorkflowInputType


class WorkflowTransition(Contract):
    """An explicit bounded transition between two application surfaces."""

    from_application_id: str
    to_application_id: str
    capability: str = "application.transition"
    approval_required: bool = True


class WorkflowRetryPolicy(Contract):
    """Bounded retry policy for provider failures with known transient causes."""

    max_attempts: int = Field(default=1, ge=1, le=3)
    retryable_errors: list[str] = Field(default_factory=list)


class WorkflowStep(Contract):
    id: str = Field(default_factory=new_id)
    order: int = Field(ge=1)
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = True
    application_profile_id: str | None = None
    application: WorkflowApplicationRequirement | None = None
    abstract_action: str | None = None
    target_signature: str | None = None
    backend_candidates: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    input_bindings: dict[str, WorkflowBinding] = Field(default_factory=dict)
    retry_policy: WorkflowRetryPolicy = Field(default_factory=WorkflowRetryPolicy)
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
    transitions: list[WorkflowTransition] = Field(default_factory=list)
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

        step_ids = {step.id for step in self.steps}
        for step in self.steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError(f"workflow step dependencies must be unique: {step.id}")
            unknown = set(step.depends_on) - step_ids
            if unknown:
                raise ValueError(
                    f"unknown workflow step dependency for {step.id}: {sorted(unknown)}"
                )
            if step.id in step.depends_on:
                raise ValueError("workflow step dependencies must be acyclic")
            if step.application is not None and step.capability not in set(
                step.application.required_capabilities
            ):
                raise ValueError(
                    f"application requirement does not allow step capability: {step.id}"
                )
            for binding in step.input_bindings.values():
                if binding.source_step_id not in step.depends_on:
                    raise ValueError(f"workflow binding source must be a dependency: {step.id}")

        application_ids = {
            step.application.application_id for step in self.steps if step.application is not None
        }
        transition_keys: set[tuple[str, str]] = set()
        for transition in self.transitions:
            key = (transition.from_application_id, transition.to_application_id)
            if transition.from_application_id == transition.to_application_id:
                raise ValueError("workflow application transitions must change application")
            if key in transition_keys:
                raise ValueError("workflow application transitions must be unique")
            if (
                not {transition.from_application_id, transition.to_application_id}
                <= application_ids
            ):
                raise ValueError("workflow transition applications must be used by workflow steps")
            transition_keys.add(key)

        dependencies = {step.id: set(step.depends_on) for step in self.steps}
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("workflow step dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)
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


class WorkflowExecution(Contract):
    """Restart-safe execution identity without raw external application data."""

    model_config = ConfigDict(extra="forbid", frozen=False)
    id: str = Field(default_factory=new_id)
    workflow_id: str
    workflow_version: int = Field(ge=1)
    state: WorkflowExecutionState = WorkflowExecutionState.CREATED
    current_step_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    last_checkpoint_id: str | None = None
    input_digest: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowStepAttempt(Contract):
    """Durable, idempotent record of one provider attempt for one step."""

    id: str = Field(default_factory=new_id)
    execution_id: str
    step_id: str
    attempt_number: int = Field(ge=1)
    state: WorkflowStepAttemptState = WorkflowStepAttemptState.PENDING
    provider_id: str
    idempotency_key: str
    effect_idempotency_key: str | None = None
    checkpoint_id: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowCheckpoint(Contract):
    """A resumable boundary containing only digests and verified effect metadata."""

    id: str = Field(default_factory=new_id)
    execution_id: str
    step_id: str
    attempt_id: str
    sequence: int = Field(ge=1)
    state: WorkflowStepAttemptState
    input_digest: str
    output_digest: str
    verified: bool = False
    resumable: bool = True
    verified_effects: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


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
