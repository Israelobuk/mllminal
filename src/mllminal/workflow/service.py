"""Approval-governed typed workflow runtime with deterministic verification."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import utc_now
from mllminal.persistence import Base
from mllminal.workflow.contracts import (
    CapabilityResult,
    VerificationResult,
    VerificationState,
    WorkflowDefinition,
    WorkflowDefinitionState,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunRequest,
    WorkflowRunState,
    WorkflowStep,
    WorkflowStepResult,
)
from mllminal.workflow.persistence import (
    WorkflowDefinitionRow,
    WorkflowIdempotencyRow,
    WorkflowRunEventRow,
    WorkflowRunRow,
)

CapabilityHandler = Callable[[dict[str, Any]], CapabilityResult]


class WorkflowService:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self._handlers: dict[str, CapabilityHandler] = {}

    def register_capability(self, name: str, handler: CapabilityHandler) -> None:
        """Register a bounded local capability implementation for live runs."""
        self._handlers[name] = handler

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
        if request.preview:
            run.step_results = [self._preview_result(step) for step in definition.steps]
            run.current_step_order = len(definition.steps)
        elif any(step.approval_required for step in definition.steps):
            first = next(step for step in definition.steps if step.approval_required)
            run.state = WorkflowRunState.PENDING_APPROVAL
            run.pending_approval_step_id = first.id
            run.current_step_order = first.order
        else:
            run = self._execute(run, definition)
        self._persist_run(run, event_type="run.created")
        self._save_idempotency(idempotency_key, "workflow.run", run)
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

    def events(self, run_id: str) -> list[WorkflowRunEvent]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(WorkflowRunEventRow)
                .where(WorkflowRunEventRow.run_id == run_id)
                .order_by(WorkflowRunEventRow.created_at)
            )
            return [WorkflowRunEvent.model_validate_json(row.payload_json) for row in rows]

    def _execute(self, run: WorkflowRun, definition: WorkflowDefinition) -> WorkflowRun:
        run.state = WorkflowRunState.RUNNING
        for step in definition.steps:
            run.current_step_order = step.order
            handler = self._handlers.get(step.capability)
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
                run.step_results.append(
                    WorkflowStepResult(
                        step_id=step.id,
                        state="failed",
                        capability_result=result,
                        verification=verification,
                    )
                )
                run.state = WorkflowRunState.FAILED
                break
            result = handler(self._resolve_arguments(step, run.inputs))
            verification = self._verify(step, result)
            step_state = (
                "succeeded"
                if result.succeeded and verification.state is VerificationState.PASSED
                else "failed"
            )
            run.step_results.append(
                WorkflowStepResult(
                    step_id=step.id,
                    state=step_state,
                    capability_result=result,
                    verification=verification,
                )
            )
            if step_state == "failed":
                run.state = WorkflowRunState.FAILED
                break
        else:
            run.state = WorkflowRunState.SUCCEEDED
            run.current_step_order = len(definition.steps)
        run.updated_at = utc_now()
        return run

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
    def _resolve_arguments(step: WorkflowStep, inputs: dict[str, Any]) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, str) and value.startswith("$input."):
                return inputs.get(value.removeprefix("$input."))
            if isinstance(value, dict):
                return {key: resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            return value

        return cast(dict[str, Any], resolve(step.arguments))

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
            "date": lambda: isinstance(value, str),
            "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
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
