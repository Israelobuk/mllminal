"""Approval-governed typed workflow runtime with deterministic verification."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import utc_now
from mllminal.persistence import Base
from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowExecution,
    WorkflowExecutionState,
    WorkflowInputType,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunRequest,
    WorkflowRunState,
    WorkflowStep,
    WorkflowStepAttempt,
    WorkflowStepAttemptState,
    WorkflowStepResult,
)
from mllminal.workflow.persistence import (
    WorkflowCheckpointRow,
    WorkflowDefinitionRow,
    WorkflowExecutionRow,
    WorkflowIdempotencyRow,
    WorkflowRunEventRow,
    WorkflowRunRow,
    WorkflowStepAttemptRow,
)

if TYPE_CHECKING:
    from mllminal.learning.adaptive import AdaptiveExecutionService


CapabilityHandler = Callable[[dict[str, Any]], CapabilityResult]


class WorkflowService:
    def __init__(
        self,
        database_path: Path,
        *,
        adaptive: "AdaptiveExecutionService | None" = None,
    ) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self._handlers: dict[str, CapabilityHandler] = {}
        self._backend_handlers: dict[tuple[str, str], CapabilityHandler] = {}
        self.adaptive = adaptive

    def register_capability(self, name: str, handler: CapabilityHandler) -> None:
        """Register a bounded local capability implementation for live runs."""
        self._handlers[name] = handler

    def register_backend(self, capability: str, backend: str, handler: CapabilityHandler) -> None:
        """Register a bounded capability implementation for a named backend."""
        self._backend_handlers[(capability, backend)] = handler

    def create(self, definition: WorkflowDefinition, *, idempotency_key: str) -> WorkflowDefinition:
        cached = self._cached(idempotency_key, "workflow.create")
        if cached is not None:
            return WorkflowDefinition.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            if database.get(WorkflowDefinitionRow, definition.id) is not None:
                raise ValueError(f"Workflow already exists: {definition.id}")
            database.add(self._definition_row(definition))
            self._add_idempotency(database, idempotency_key, "workflow.create", definition)
        return definition

    def activate(self, workflow_id: str, *, idempotency_key: str) -> WorkflowDefinition:
        cached = self._cached(idempotency_key, "workflow.activate")
        if cached is not None:
            return WorkflowDefinition.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            row = database.get(WorkflowDefinitionRow, workflow_id)
            if row is None:
                raise KeyError(workflow_id)
            if row.state == WorkflowDefinitionState.ARCHIVED.value:
                raise RuntimeError("Archived workflows cannot be activated")
            row.state = WorkflowDefinitionState.ACTIVE.value
            definition = self._definition_from_row(row).model_copy(
                update={"state": WorkflowDefinitionState.ACTIVE}
            )
            row.payload_json = definition.model_dump_json()
            self._add_idempotency(database, idempotency_key, "workflow.activate", definition)
        return definition

    def archive(self, workflow_id: str, *, idempotency_key: str) -> WorkflowDefinition:
        cached = self._cached(idempotency_key, "workflow.archive")
        if cached is not None:
            return WorkflowDefinition.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            row = database.get(WorkflowDefinitionRow, workflow_id)
            if row is None:
                raise KeyError(workflow_id)
            row.state = WorkflowDefinitionState.ARCHIVED.value
            definition = self._definition_from_row(row).model_copy(
                update={"state": WorkflowDefinitionState.ARCHIVED}
            )
            row.payload_json = definition.model_dump_json()
            self._add_idempotency(database, idempotency_key, "workflow.archive", definition)
        return definition

    def run(
        self,
        workflow_id: str,
        request: WorkflowRunRequest,
        *,
        idempotency_key: str,
    ) -> WorkflowRun:
        cached = self._cached(idempotency_key, "workflow.run")
        if cached is not None:
            return WorkflowRun.model_validate(cached)
        definition = self.definition(workflow_id)
        inputs = self._validate_inputs(definition, request.inputs)
        if not request.preview and definition.state is not WorkflowDefinitionState.ACTIVE:
            raise PermissionError("Only active workflows may run outside preview mode")
        state = WorkflowRunState.PREVIEW if request.preview else WorkflowRunState.RUNNING
        run = WorkflowRun(
            workflow_id=definition.id,
            workflow_version=definition.version,
            state=state,
            preview=request.preview,
            inputs=inputs,
        )
        execution_steps = self._execution_steps(definition)
        event_type = "run.created"
        if request.preview:
            run.step_results = [self._preview_result(step) for step in execution_steps]
            run.current_step_order = len(execution_steps)
        elif any(step.approval_required for step in execution_steps):
            first = next(step for step in execution_steps if step.approval_required)
            run.state = WorkflowRunState.PENDING_APPROVAL
            run.pending_approval_step_id = first.id
            run.current_step_order = first.order
        else:
            self._persist_run(run, event_type="run.started")
            run = self._execute(run, definition)
            event_type = "run.completed"
        self._persist_run(run, event_type=event_type)
        self._save_idempotency(idempotency_key, "workflow.run", run)
        return run

    def resume(self, run_id: str, *, idempotency_key: str) -> WorkflowRun:
        cached = self._cached(idempotency_key, "workflow.resume")
        if cached is not None:
            return WorkflowRun.model_validate(cached)
        run = self.run_record(run_id)
        if run.preview or run.state not in {WorkflowRunState.RUNNING, WorkflowRunState.FAILED}:
            raise RuntimeError("Only interrupted or failed live runs can be resumed")
        definition = self.definition(run.workflow_id)
        if definition.state is not WorkflowDefinitionState.ACTIVE:
            raise PermissionError("Only active workflows may be resumed")
        run.pending_approval_step_id = None
        run = self._execute(run, definition, resume=True)
        self._persist_run(run, event_type="run.resumed")
        self._save_idempotency(idempotency_key, "workflow.resume", run)
        return run

    def approve(
        self,
        run_id: str,
        approved: bool,
        *,
        idempotency_key: str,
    ) -> WorkflowRun:
        cached = self._cached(idempotency_key, "workflow.approve")
        if cached is not None:
            return WorkflowRun.model_validate(cached)
        run = self.run_record(run_id)
        if run.state is not WorkflowRunState.PENDING_APPROVAL:
            raise RuntimeError("Workflow run is not awaiting approval")
        definition = self.definition(run.workflow_id)
        if not approved:
            run.state = WorkflowRunState.CANCELLED
            run.pending_approval_step_id = None
            run.updated_at = utc_now()
            self._persist_run(run, event_type="approval.rejected")
        else:
            run.pending_approval_step_id = None
            run = self._execute(run, definition)
            self._persist_run(run, event_type="approval.granted")
        self._save_idempotency(idempotency_key, "workflow.approve", run)
        return run

    def rollback(self, run_id: str, *, idempotency_key: str) -> WorkflowRun:
        cached = self._cached(idempotency_key, "workflow.rollback")
        if cached is not None:
            return WorkflowRun.model_validate(cached)
        run = self.run_record(run_id)
        definition = self.definition(run.workflow_id)
        succeeded = {item.step_id for item in run.step_results if item.state == "succeeded"}
        steps = [step for step in definition.steps if step.id in succeeded]
        missing = [step for step in steps if not step.rollback_capability]
        if missing:
            run.rollback_state = "unavailable"
            self._persist_run(run, event_type="rollback.unavailable")
        else:
            rollback_failed = False
            for step in reversed(steps):
                handler = self._handlers.get(cast(str, step.rollback_capability))
                if (
                    handler is None
                    or not handler(self._resolve_arguments(step, run.inputs)).succeeded
                ):
                    rollback_failed = True
                    break
            run.rollback_state = "partial" if rollback_failed else "complete"
            if not rollback_failed:
                run.state = WorkflowRunState.ROLLED_BACK
            self._persist_run(run, event_type="rollback.completed")
        self._save_idempotency(idempotency_key, "workflow.rollback", run)
        return run

    def definitions(self) -> list[WorkflowDefinition]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowDefinitionRow).order_by(WorkflowDefinitionRow.created_at)
            )
            return [self._definition_from_row(row) for row in rows]

    def definition(self, workflow_id: str) -> WorkflowDefinition:
        with DbSession(self.engine) as database:
            row = database.get(WorkflowDefinitionRow, workflow_id)
            if row is None:
                raise KeyError(workflow_id)
            return self._definition_from_row(row)

    def runs(self) -> list[WorkflowRun]:
        with DbSession(self.engine) as database:
            rows = database.scalars(select(WorkflowRunRow).order_by(WorkflowRunRow.created_at))
            return [WorkflowRun.model_validate_json(row.payload_json) for row in rows]

    def run_record(self, run_id: str) -> WorkflowRun:
        with DbSession(self.engine) as database:
            row = database.get(WorkflowRunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            return WorkflowRun.model_validate_json(row.payload_json)

    def execution(self, execution_id: str) -> WorkflowExecution:
        with DbSession(self.engine) as database:
            row = database.get(WorkflowExecutionRow, execution_id)
            if row is None:
                raise KeyError(execution_id)
            return WorkflowExecution.model_validate_json(row.payload_json)

    def attempts(self, execution_id: str) -> list[WorkflowStepAttempt]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowStepAttemptRow)
                .where(WorkflowStepAttemptRow.execution_id == execution_id)
                .order_by(WorkflowStepAttemptRow.attempt_number)
            )
            return [WorkflowStepAttempt.model_validate_json(row.payload_json) for row in rows]

    def checkpoints(self, execution_id: str) -> list[WorkflowCheckpoint]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowCheckpointRow)
                .where(WorkflowCheckpointRow.execution_id == execution_id)
                .order_by(WorkflowCheckpointRow.sequence)
            )
            return [WorkflowCheckpoint.model_validate_json(row.payload_json) for row in rows]

    def events(self, run_id: str) -> list[WorkflowRunEvent]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowRunEventRow)
                .where(WorkflowRunEventRow.run_id == run_id)
                .order_by(WorkflowRunEventRow.created_at)
            )
            return [WorkflowRunEvent.model_validate_json(row.payload_json) for row in rows]

    def _execute(
        self,
        run: WorkflowRun,
        definition: WorkflowDefinition,
        *,
        resume: bool = False,
    ) -> WorkflowRun:
        run.state = WorkflowRunState.RUNNING
        execution = WorkflowExecution(
            id=run.id,
            workflow_id=run.workflow_id,
            workflow_version=run.workflow_version,
            state=WorkflowExecutionState.RUNNING,
        )
        self._persist_execution(execution)
        if resume:
            run.step_results = [item for item in run.step_results if item.state == "succeeded"]
            completed_step_ids = {item.step_id for item in run.step_results}
            for restored_checkpoint in self.checkpoints(run.id):
                if (
                    restored_checkpoint.verified
                    and restored_checkpoint.resumable
                    and restored_checkpoint.step_id not in completed_step_ids
                ):
                    run.step_results.append(
                        WorkflowStepResult(
                            step_id=restored_checkpoint.step_id,
                            state="succeeded",
                            verification=VerificationResult(
                                state=VerificationState.PASSED,
                                reason="Restored from durable checkpoint",
                            ),
                        )
                    )
                    completed_step_ids.add(restored_checkpoint.step_id)
        for step in self._execution_steps(definition):
            if resume and any(
                item.step_id == step.id and item.state == "succeeded" for item in run.step_results
            ):
                continue
            run.current_step_order = step.order
            attempt_number = self._next_attempt_number(run.id, step.id)
            attempt = WorkflowStepAttempt(
                execution_id=run.id,
                step_id=step.id,
                attempt_number=attempt_number,
                state=WorkflowStepAttemptState.RUNNING,
                provider_id=(
                    step.application.provider_hint
                    if step.application is not None and step.application.provider_hint is not None
                    else step.capability
                ),
                idempotency_key=f"{run.id}:{step.id}:{attempt_number}",
                started_at=utc_now(),
            )
            self._persist_attempt(attempt)
            decision = None
            handler = self._handlers.get(step.capability)
            if self.adaptive is not None and step.application_profile_id is not None:
                from mllminal.learning.adaptive import (
                    AdaptiveBackendCandidate,
                    AdaptiveExecutionRequest,
                )

                candidates = (
                    step.backend_candidates
                    or [
                        backend
                        for capability, backend in self._backend_handlers
                        if capability == step.capability
                    ]
                    or ["default"]
                )
                decision = self.adaptive.decide(
                    AdaptiveExecutionRequest(
                        workflow_run_id=run.id,
                        workflow_step_id=step.id,
                        application_profile_id=step.application_profile_id,
                        abstract_action=step.abstract_action or step.capability,
                        target_signature=step.target_signature or step.capability,
                        candidates=[AdaptiveBackendCandidate(backend=name) for name in candidates],
                        safety_filters_applied=["workflow_permission_verified"],
                    )
                )
                if decision.selected_backend is None:
                    result = CapabilityResult(
                        capability=step.capability,
                        succeeded=False,
                        error=(
                            "clarification_required"
                            if decision.clarification_required
                            else "adaptive_backend_unavailable"
                        ),
                    )
                    verification = VerificationResult(
                        state=VerificationState.UNAVAILABLE,
                        reason=decision.decision_reason,
                    )
                    attempt = attempt.model_copy(
                        update={
                            "state": WorkflowStepAttemptState.FAILED,
                            "error_code": result.error,
                            "finished_at": utc_now(),
                        }
                    )
                    self._persist_attempt(attempt)
                    run.step_results.append(
                        WorkflowStepResult(
                            step_id=step.id,
                            state="failed",
                            capability_result=result,
                            verification=verification,
                        )
                    )
                    self._persist_run(run, event_type="step.failed")
                    run.state = WorkflowRunState.FAILED
                    break
                handler = self._backend_handlers.get(
                    (step.capability, decision.selected_backend), handler
                )
                attempt = attempt.model_copy(update={"provider_id": decision.selected_backend})
                self._persist_attempt(attempt)
            resolved_arguments: dict[str, Any] = {}
            if handler is None:
                result = CapabilityResult(
                    capability=step.capability,
                    succeeded=False,
                    error="capability_not_registered",
                )
                verification = VerificationResult(
                    state=VerificationState.UNAVAILABLE,
                    reason="No bounded capability handler is registered",
                )
            else:
                resolved_arguments = self._resolve_arguments(step, run.inputs, run.step_results)
                result = handler(resolved_arguments)
                verification = self._verify(step, result)
            if decision is not None and self.adaptive is not None:
                self.adaptive.record_outcome(
                    decision.decision_id,
                    execution_succeeded=result.succeeded,
                    verification_passed=verification.state is VerificationState.PASSED,
                    failure_class=result.error,
                )
            step_state = (
                "succeeded"
                if result.succeeded and verification.state is VerificationState.PASSED
                else "failed"
            )
            checkpoint: WorkflowCheckpoint | None = None
            if step_state == "succeeded":
                checkpoint = WorkflowCheckpoint(
                    execution_id=run.id,
                    step_id=step.id,
                    attempt_id=attempt.id,
                    sequence=self._next_checkpoint_sequence(run.id),
                    state=WorkflowStepAttemptState.SUCCEEDED,
                    input_digest=self._digest(resolved_arguments),
                    output_digest=self._digest(result.output),
                    verified=True,
                    verified_effects={"verified": True},
                )
                self._persist_checkpoint(checkpoint)
            attempt = attempt.model_copy(
                update={
                    "state": (
                        WorkflowStepAttemptState.SUCCEEDED
                        if step_state == "succeeded"
                        else WorkflowStepAttemptState.FAILED
                    ),
                    "checkpoint_id": checkpoint.id if checkpoint is not None else None,
                    "error_code": result.error,
                    "finished_at": utc_now(),
                }
            )
            self._persist_attempt(attempt)
            run.step_results.append(
                WorkflowStepResult(
                    step_id=step.id,
                    state=step_state,
                    capability_result=result,
                    verification=verification,
                )
            )
            self._persist_run(
                run,
                event_type="step.completed" if step_state == "succeeded" else "step.failed",
            )
            if step_state == "failed":
                run.state = WorkflowRunState.FAILED
                break
        else:
            run.state = WorkflowRunState.SUCCEEDED
            run.current_step_order = len(definition.steps)
        run.updated_at = utc_now()
        self._persist_execution(
            execution.model_copy(
                update={
                    "state": self._execution_state(run.state),
                    "current_step_id": (
                        None
                        if run.state is WorkflowRunState.SUCCEEDED
                        else next(
                            (
                                step.id
                                for step in self._execution_steps(definition)
                                if step.order == run.current_step_order
                            ),
                            None,
                        )
                    ),
                    "completed_step_ids": [
                        item.step_id for item in run.step_results if item.state == "succeeded"
                    ],
                    "last_checkpoint_id": (
                        self.checkpoints(run.id)[-1].id if self.checkpoints(run.id) else None
                    ),
                    "updated_at": run.updated_at,
                }
            )
        )
        return run

    @staticmethod
    def _execution_steps(definition: WorkflowDefinition) -> list[WorkflowStep]:
        steps_by_id = {step.id: step for step in definition.steps}
        pending = set(steps_by_id)
        completed: set[str] = set()
        ordered: list[WorkflowStep] = []
        while pending:
            ready = sorted(
                (
                    steps_by_id[step_id]
                    for step_id in pending
                    if set(steps_by_id[step_id].depends_on) <= completed
                ),
                key=lambda step: step.order,
            )
            if not ready:
                raise RuntimeError("workflow step dependencies cannot be resolved")
            ordered.extend(ready)
            completed.update(step.id for step in ready)
            pending.difference_update(step.id for step in ready)
        return ordered

    @staticmethod
    def _preview_result(step: WorkflowStep) -> WorkflowStepResult:
        return WorkflowStepResult(
            step_id=step.id,
            state="preview",
            verification=VerificationResult(
                state=VerificationState.NOT_RUN,
                reason="Preview does not execute or inspect external state",
            ),
        )

    @staticmethod
    def _verify(step: WorkflowStep, result: CapabilityResult) -> VerificationResult:
        if not result.succeeded:
            return VerificationResult(
                state=VerificationState.FAILED,
                reason=result.error or "Capability failed",
                observed=result.output,
            )
        if step.verification is None:
            return VerificationResult(
                state=VerificationState.UNAVAILABLE,
                reason="Independent verification is required",
                observed=result.output,
            )
        expected = step.verification.expected
        if all(result.output.get(key) == value for key, value in expected.items()):
            return VerificationResult(
                state=VerificationState.PASSED,
                reason="Expected fields matched capability output",
                observed=result.output,
            )
        return VerificationResult(
            state=VerificationState.FAILED,
            reason="Capability output did not match expected fields",
            observed=result.output,
        )

    @staticmethod
    def _resolve_arguments(
        step: WorkflowStep,
        inputs: dict[str, Any],
        step_results: list[WorkflowStepResult] | None = None,
    ) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, str) and value.startswith("$input."):
                return inputs.get(value.removeprefix("$input."))
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return value

        arguments = cast(dict[str, Any], resolve(step.arguments))
        if not step.input_bindings:
            return arguments
        if step_results is None:
            raise RuntimeError("workflow step bindings require execution results")
        results_by_step = {result.step_id: result for result in step_results}
        for target_name, binding in step.input_bindings.items():
            source_result = results_by_step.get(binding.source_step_id)
            if (
                source_result is None
                or source_result.state != "succeeded"
                or source_result.capability_result is None
            ):
                raise RuntimeError(
                    f"workflow binding source is not a completed step: {binding.source_step_id}"
                )
            if binding.source_field not in source_result.capability_result.output:
                raise ValueError(
                    f"workflow binding source field is missing: {binding.source_field}"
                )
            value = source_result.capability_result.output[binding.source_field]
            if binding.target_type is not WorkflowInputType.PREVIOUS_OUTPUT and not (
                WorkflowService._valid_input_type(binding.target_type.value, value)
            ):
                raise ValueError(f"workflow binding type mismatch: {target_name}")
            arguments[target_name] = value
        return arguments

    @staticmethod
    def _validate_inputs(definition: WorkflowDefinition, values: dict[str, Any]) -> dict[str, Any]:
        known = {item.name: item for item in definition.inputs}
        extra = set(values) - set(known)
        if extra:
            raise ValueError(f"Unknown workflow inputs: {sorted(extra)}")
        result: dict[str, Any] = {}
        for name, item in known.items():
            if name in values:
                value = values[name]
            elif item.default is not None:
                value = item.default
            elif item.required:
                raise ValueError(f"Required workflow input missing: {name}")
            else:
                value = None
            if value is not None and not WorkflowService._valid_input_type(item.type.value, value):
                raise ValueError(f"Invalid value for workflow input: {name}")
            result[name] = value
        return result

    @staticmethod
    def _valid_input_type(kind: str, value: Any) -> bool:
        return {
            "string": lambda: isinstance(value, str),
            "path": lambda: isinstance(value, str),
            "file": lambda: isinstance(value, str),
            "folder": lambda: isinstance(value, str),
            "date": lambda: isinstance(value, str),
            "datetime": lambda: isinstance(value, str),
            "contact": lambda: isinstance(value, str),
            "application": lambda: isinstance(value, str),
            "selected_item": lambda: isinstance(value, str),
            "previous_output": lambda: isinstance(value, (str, int, float, bool, dict, list)),
            "user_choice": lambda: isinstance(value, (str, int, float, bool)),
            "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda: isinstance(value, bool),
        }[kind]()

    @staticmethod
    def _definition_row(definition: WorkflowDefinition) -> WorkflowDefinitionRow:
        return WorkflowDefinitionRow(
            id=definition.id,
            name=definition.name,
            version=definition.version,
            state=definition.state.value,
            payload_json=definition.model_dump_json(),
            created_at=definition.created_at,
        )

    @staticmethod
    def _definition_from_row(row: WorkflowDefinitionRow) -> WorkflowDefinition:
        return WorkflowDefinition.model_validate_json(row.payload_json)

    @staticmethod
    def _execution_state(state: WorkflowRunState) -> WorkflowExecutionState:
        return {
            WorkflowRunState.PREVIEW: WorkflowExecutionState.CREATED,
            WorkflowRunState.PENDING_APPROVAL: WorkflowExecutionState.PAUSED,
            WorkflowRunState.RUNNING: WorkflowExecutionState.RUNNING,
            WorkflowRunState.SUCCEEDED: WorkflowExecutionState.SUCCEEDED,
            WorkflowRunState.FAILED: WorkflowExecutionState.FAILED,
            WorkflowRunState.ROLLED_BACK: WorkflowExecutionState.ROLLED_BACK,
            WorkflowRunState.CANCELLED: WorkflowExecutionState.CANCELLED,
        }[state]

    @staticmethod
    def _digest(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _next_attempt_number(self, execution_id: str, step_id: str) -> int:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowStepAttemptRow).where(
                    WorkflowStepAttemptRow.execution_id == execution_id,
                    WorkflowStepAttemptRow.step_id == step_id,
                )
            )
            return len(list(rows)) + 1

    def _next_checkpoint_sequence(self, execution_id: str) -> int:
        return len(self.checkpoints(execution_id)) + 1

    def _persist_execution(self, execution: WorkflowExecution) -> None:
        with DbSession(self.engine) as database, database.begin():
            row = database.get(WorkflowExecutionRow, execution.id)
            if row is None:
                database.add(
                    WorkflowExecutionRow(
                        id=execution.id,
                        workflow_id=execution.workflow_id,
                        state=execution.state.value,
                        payload_json=execution.model_dump_json(),
                        created_at=execution.created_at,
                        updated_at=execution.updated_at,
                    )
                )
            else:
                row.state = execution.state.value
                row.payload_json = execution.model_dump_json()
                row.updated_at = execution.updated_at

    def _persist_attempt(self, attempt: WorkflowStepAttempt) -> None:
        created_at = attempt.started_at or utc_now()
        with DbSession(self.engine) as database, database.begin():
            row = database.get(WorkflowStepAttemptRow, attempt.id)
            if row is None:
                database.add(
                    WorkflowStepAttemptRow(
                        id=attempt.id,
                        execution_id=attempt.execution_id,
                        step_id=attempt.step_id,
                        attempt_number=attempt.attempt_number,
                        state=attempt.state.value,
                        payload_json=attempt.model_dump_json(),
                        created_at=created_at,
                    )
                )
            else:
                row.state = attempt.state.value
                row.payload_json = attempt.model_dump_json()

    def _persist_checkpoint(self, checkpoint: WorkflowCheckpoint) -> None:
        with DbSession(self.engine) as database, database.begin():
            if database.get(WorkflowCheckpointRow, checkpoint.id) is not None:
                return
            database.add(
                WorkflowCheckpointRow(
                    id=checkpoint.id,
                    execution_id=checkpoint.execution_id,
                    step_id=checkpoint.step_id,
                    sequence=checkpoint.sequence,
                    payload_json=checkpoint.model_dump_json(),
                    created_at=checkpoint.created_at,
                )
            )

    def _sync_execution(self, run: WorkflowRun) -> None:
        try:
            execution = self.execution(run.id)
        except KeyError:
            execution = WorkflowExecution(
                id=run.id,
                workflow_id=run.workflow_id,
                workflow_version=run.workflow_version,
            )
        checkpoints = self.checkpoints(run.id)
        self._persist_execution(
            execution.model_copy(
                update={
                    "state": self._execution_state(run.state),
                    "current_step_id": run.pending_approval_step_id,
                    "completed_step_ids": [
                        item.step_id for item in run.step_results if item.state == "succeeded"
                    ],
                    "last_checkpoint_id": checkpoints[-1].id if checkpoints else None,
                    "input_digest": self._digest(run.inputs),
                    "updated_at": run.updated_at,
                }
            )
        )

    def _persist_run(self, run: WorkflowRun, *, event_type: str) -> None:
        event = WorkflowRunEvent(run_id=run.id, event_type=event_type, payload=run.model_dump())
        with DbSession(self.engine) as database, database.begin():
            row = database.get(WorkflowRunRow, run.id)
            if row is None:
                database.add(
                    WorkflowRunRow(
                        id=run.id,
                        workflow_id=run.workflow_id,
                        state=run.state.value,
                        payload_json=run.model_dump_json(),
                        created_at=run.created_at,
                        updated_at=run.updated_at,
                    )
                )
            else:
                row.state = run.state.value
                row.payload_json = run.model_dump_json()
                row.updated_at = run.updated_at
            database.add(
                WorkflowRunEventRow(
                    id=event.id,
                    run_id=event.run_id,
                    event_type=event.event_type,
                    payload_json=event.model_dump_json(),
                    created_at=event.created_at,
                )
            )
        self._sync_execution(run)

    def _save_idempotency(self, key: str, operation: str, result: Any) -> None:
        with DbSession(self.engine) as database, database.begin():
            self._add_idempotency(database, key, operation, result)

    @staticmethod
    def _add_idempotency(database: DbSession, key: str, operation: str, result: Any) -> None:
        database.add(
            WorkflowIdempotencyRow(
                key=key,
                operation=operation,
                result_json=result.model_dump_json(),
                created_at=utc_now(),
            )
        )

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.get(WorkflowIdempotencyRow, key)
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))
