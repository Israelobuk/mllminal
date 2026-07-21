"""Explicit, bounded workflow demonstration recording."""

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import utc_now
from mllminal.demonstration.contracts import (
    DemonstrationCaptureRequest,
    DemonstrationCaptureResult,
    DemonstrationSession,
    DemonstrationState,
    DemonstrationStatus,
    DemonstrationStep,
    DemonstrationStopResult,
    VariableAssignment,
    VariableLabel,
    WorkflowCandidate,
)
from mllminal.demonstration.persistence import (
    DemonstrationIdempotencyRow,
    DemonstrationSessionRow,
    DemonstrationStepRow,
    DemonstrationVariableRow,
    WorkflowCandidateRow,
    load_steps,
    load_variables,
)
from mllminal.interaction.contracts import InteractionEvent
from mllminal.interaction.service import InteractionService
from mllminal.persistence import Base


class DemonstrationService:
    def __init__(
        self,
        database_path: Path,
        interaction: InteractionService,
        profile_id_for_application: Callable[[str], str | None] | None = None,
    ) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.interaction = interaction
        self.profile_id_for_application = profile_id_for_application
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)

    def status(self, session_id: str | None = None) -> DemonstrationStatus:
        session = self._load_session(session_id)
        if session is not None and session.state is DemonstrationState.RECORDING:
            session = self._expire_if_needed(session)
        recording = session is not None and session.state is DemonstrationState.RECORDING
        if session is None:
            visible = "DEMONSTRATION IDLE"
        elif session.state is DemonstrationState.RECORDING:
            visible = "DEMONSTRATION RECORDING"
        elif session.state is DemonstrationState.EXPIRED:
            visible = "DEMONSTRATION EXPIRED"
        elif session.state is DemonstrationState.CANCELLED:
            visible = "DEMONSTRATION CANCELLED"
        else:
            visible = "DEMONSTRATION STOPPED"
        return DemonstrationStatus(
            session=session,
            recording=recording,
            visible_recording=True,
            visible_status=visible,
        )

    def start(
        self,
        label: str,
        *,
        timeout_seconds: int = 900,
        emergency_stop_shortcut: str = "CTRL+ALT+ESC",
        idempotency_key: str,
    ) -> DemonstrationSession:
        def action(database: DbSession) -> DemonstrationSession:
            active = database.scalar(
                select(DemonstrationSessionRow).where(
                    DemonstrationSessionRow.state == DemonstrationState.RECORDING.value
                )
            )
            if active is not None:
                raise RuntimeError("A demonstration is already recording")
            now = utc_now()
            session = DemonstrationSession(
                label=label,
                timeout_seconds=timeout_seconds,
                emergency_stop_shortcut=self._normalize_shortcut(emergency_stop_shortcut),
                started_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=timeout_seconds),
            )
            database.add(self._session_row(session))
            return session

        return cast(
            DemonstrationSession,
            self._mutate(idempotency_key, "demonstration.start", action, DemonstrationSession),
        )

    def stop(self, session_id: str, *, idempotency_key: str) -> DemonstrationStopResult:
        cached = self._cached(idempotency_key, "demonstration.stop")
        if cached is not None:
            return DemonstrationStopResult.model_validate(cached)
        session = self._expire_if_needed(self._require_session(session_id))
        if session.state is DemonstrationState.STOPPED and session.candidate_id:
            result = DemonstrationStopResult(
                session=session,
                candidate=self.candidate(session.candidate_id),
            )
            self._save_idempotency(idempotency_key, "demonstration.stop", result)
            return result
        if session.state is not DemonstrationState.RECORDING:
            raise RuntimeError(f"Demonstration cannot stop from {session.state.value} state")
        session = session.model_copy(
            update={"state": DemonstrationState.STOPPED, "updated_at": utc_now()}
        )
        with DbSession(self.engine) as database, database.begin():
            row = database.get(DemonstrationSessionRow, session_id)
            if row is None:
                raise KeyError(session_id)
            row.state = DemonstrationState.STOPPED.value
            row.updated_at = session.updated_at
        candidate = self._create_candidate(session)
        session = session.model_copy(update={"candidate_id": candidate.id})
        result = DemonstrationStopResult(session=session, candidate=candidate)
        self._save_idempotency(idempotency_key, "demonstration.stop", result)
        return result

    def cancel(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        reason: str = "cancelled",
    ) -> DemonstrationSession:
        def action(database: DbSession) -> DemonstrationSession:
            row = database.get(DemonstrationSessionRow, session_id)
            if row is None:
                raise KeyError(session_id)
            row.state = DemonstrationState.CANCELLED.value
            row.updated_at = utc_now()
            return self._session_from_row(row)

        _ = reason
        return cast(
            DemonstrationSession,
            self._mutate(idempotency_key, "demonstration.cancel", action, DemonstrationSession),
        )

    def emergency_stop(self, session_id: str, *, idempotency_key: str) -> DemonstrationSession:
        return self.cancel(
            session_id,
            idempotency_key=idempotency_key,
            reason="emergency_stop",
        )

    def record(
        self,
        session_id: str,
        request: DemonstrationCaptureRequest,
        *,
        idempotency_key: str,
    ) -> DemonstrationCaptureResult:
        cached = self._cached(idempotency_key, "demonstration.record")
        if cached is not None:
            return DemonstrationCaptureResult.model_validate(cached)
        session = self._require_session(session_id)
        session = self._expire_if_needed(session)
        if session.state is not DemonstrationState.RECORDING:
            return self._record_result(
                idempotency_key,
                DemonstrationCaptureResult(
                    accepted=False,
                    reason=f"demonstration_{session.state.value}",
                    session=session,
                ),
            )
        if (
            request.event.shortcut
            and self._normalize_shortcut(request.event.shortcut) == session.emergency_stop_shortcut
        ):
            stopped = self.emergency_stop(
                session_id,
                idempotency_key=f"{idempotency_key}:emergency",
            )
            return self._record_result(
                idempotency_key,
                DemonstrationCaptureResult(
                    accepted=False,
                    reason="emergency_stop",
                    session=stopped,
                ),
            )
        interaction_result = self.interaction.capture(
            request.event,
            idempotency_key=f"demonstration:{idempotency_key}",
        )
        if not interaction_result.accepted or interaction_result.event is None:
            return self._record_result(
                idempotency_key,
                DemonstrationCaptureResult(
                    accepted=False,
                    reason=interaction_result.reason,
                    interaction=interaction_result,
                    session=session,
                ),
            )
        with DbSession(self.engine) as database, database.begin():
            row = database.get(DemonstrationSessionRow, session_id)
            if row is None or row.state != DemonstrationState.RECORDING.value:
                result = DemonstrationCaptureResult(
                    accepted=False,
                    reason="demonstration_not_recording",
                    interaction=interaction_result,
                    session=self._session_from_row(row) if row else None,
                )
            else:
                step = DemonstrationStep(
                    session_id=session_id,
                    sequence=row.step_count + 1,
                    event=interaction_result.event,
                    normalized_file_operation=request.normalized_file_operation,
                    application_transition=request.application_transition,
                    text_entry_occurred=request.text_entry_occurred,
                    fragile=request.fragile,
                    source_event_id=request.source_event_id,
                    required_capability=self._capability_for_event(request.event),
                    application_profile_id=(
                        request.application_profile_id or self._profile_id_for_event(request.event)
                    ),
                )
                row.step_count += 1
                row.updated_at = utc_now()
                database.add(
                    DemonstrationStepRow(
                        id=step.id,
                        session_id=step.session_id,
                        sequence=step.sequence,
                        payload_json=step.model_dump_json(),
                    )
                )
                result = DemonstrationCaptureResult(
                    accepted=True,
                    reason="recorded",
                    interaction=interaction_result,
                    session=self._session_from_row(row),
                )
        return self._record_result(idempotency_key, result)

    def assign_variable(
        self,
        session_id: str,
        event_id: str,
        label: VariableLabel,
        *,
        field_name: str | None = None,
        idempotency_key: str,
    ) -> VariableAssignment:
        def action(database: DbSession) -> VariableAssignment:
            session = database.get(DemonstrationSessionRow, session_id)
            if session is None:
                raise KeyError(session_id)
            step = database.scalar(
                select(DemonstrationStepRow).where(
                    DemonstrationStepRow.session_id == session_id,
                    DemonstrationStepRow.payload_json.contains(event_id),
                )
            )
            if step is None:
                raise KeyError(event_id)
            assignment = VariableAssignment(
                session_id=session_id,
                event_id=event_id,
                label=label,
                field_name=field_name,
            )
            database.add(
                DemonstrationVariableRow(
                    id=assignment.id,
                    session_id=assignment.session_id,
                    event_id=assignment.event_id,
                    label=assignment.label.value,
                    field_name=assignment.field_name,
                )
            )
            return assignment

        return cast(
            VariableAssignment,
            self._mutate(idempotency_key, "demonstration.variable", action, VariableAssignment),
        )

    def sessions(self) -> list[DemonstrationSession]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(DemonstrationSessionRow).order_by(DemonstrationSessionRow.started_at)
            )
            return [self._session_from_row(row) for row in rows]

    def steps(self, session_id: str) -> list[DemonstrationStep]:
        with DbSession(self.engine) as database:
            return [
                DemonstrationStep.model_validate_json(row.payload_json)
                for row in load_steps(database, session_id)
            ]

    def candidate(self, candidate_id: str) -> WorkflowCandidate:
        with DbSession(self.engine) as database:
            row = database.get(WorkflowCandidateRow, candidate_id)
            if row is None:
                raise KeyError(candidate_id)
            return WorkflowCandidate.model_validate_json(row.payload_json)

    def _create_candidate(self, session: DemonstrationSession) -> WorkflowCandidate:
        with DbSession(self.engine) as database, database.begin():
            steps = [
                DemonstrationStep.model_validate_json(row.payload_json)
                for row in load_steps(database, session.id)
            ]
            variables = [
                VariableAssignment(
                    id=row.id,
                    session_id=row.session_id,
                    event_id=row.event_id,
                    label=VariableLabel(row.label),
                    field_name=row.field_name,
                )
                for row in load_variables(database, session.id)
            ]
            candidate = WorkflowCandidate(
                session_id=session.id,
                title=session.label,
                step_ids=[step.id for step in steps],
                variables=variables,
                fragile_step_ids=[step.id for step in steps if step.fragile],
                approval_step_ids=[
                    step.id
                    for step in steps
                    if step.event.kind.value in {"file.operation", "control.invoked"}
                ],
                required_capabilities=sorted({step.required_capability for step in steps}),
                application_profile_ids=sorted(
                    {
                        step.application_profile_id
                        for step in steps
                        if step.application_profile_id is not None
                    }
                ),
                verification_requirements=sorted(
                    {
                        "independent filesystem verification"
                        if step.event.kind.value == "file.operation"
                        else "post-action state verification"
                        for step in steps
                        if step.event.kind.value in {"file.operation", "control.invoked"}
                    }
                ),
            )
            row = database.get(DemonstrationSessionRow, session.id)
            if row is None:
                raise KeyError(session.id)
            row.state = session.state.value
            row.candidate_id = candidate.id
            row.updated_at = utc_now()
            database.add(
                WorkflowCandidateRow(
                    id=candidate.id,
                    session_id=candidate.session_id,
                    title=candidate.title,
                    status=candidate.status,
                    activated=candidate.activated,
                    payload_json=candidate.model_dump_json(),
                    created_at=candidate.created_at,
                )
            )
            return candidate

    def _load_session(self, session_id: str | None) -> DemonstrationSession | None:
        with DbSession(self.engine) as database:
            row = (
                database.get(DemonstrationSessionRow, session_id)
                if session_id
                else database.scalar(
                    select(DemonstrationSessionRow).order_by(
                        DemonstrationSessionRow.updated_at.desc()
                    )
                )
            )
            return self._session_from_row(row) if row else None

    def _require_session(self, session_id: str) -> DemonstrationSession:
        session = self._load_session(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def _expire_if_needed(self, session: DemonstrationSession) -> DemonstrationSession:
        if session.state is not DemonstrationState.RECORDING or session.expires_at > utc_now():
            return session
        with DbSession(self.engine) as database, database.begin():
            row = database.get(DemonstrationSessionRow, session.id)
            if row is not None and row.state == DemonstrationState.RECORDING.value:
                row.state = DemonstrationState.EXPIRED.value
                row.updated_at = utc_now()
                return self._session_from_row(row)
        return session.model_copy(update={"state": DemonstrationState.EXPIRED})

    @staticmethod
    def _session_row(session: DemonstrationSession) -> DemonstrationSessionRow:
        return DemonstrationSessionRow(
            id=session.id,
            label=session.label,
            state=session.state.value,
            timeout_seconds=session.timeout_seconds,
            emergency_stop_shortcut=session.emergency_stop_shortcut,
            started_at=session.started_at,
            updated_at=session.updated_at,
            expires_at=session.expires_at,
            step_count=session.step_count,
            candidate_id=session.candidate_id,
        )

    @staticmethod
    def _session_from_row(row: DemonstrationSessionRow) -> DemonstrationSession:
        return DemonstrationSession(
            id=row.id,
            label=row.label,
            state=DemonstrationState(row.state),
            timeout_seconds=row.timeout_seconds,
            emergency_stop_shortcut=row.emergency_stop_shortcut,
            started_at=row.started_at,
            updated_at=row.updated_at,
            expires_at=row.expires_at,
            step_count=row.step_count,
            candidate_id=row.candidate_id,
        )

    def _mutate(self, key: str, operation: str, action: Any, model: Any) -> Any:
        cached = self._cached(key, operation)
        if cached is not None:
            return model.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            result = action(database)
            database.add(
                DemonstrationIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )
            return result

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.get(DemonstrationIdempotencyRow, key)
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))

    def _record_result(
        self, key: str, result: DemonstrationCaptureResult
    ) -> DemonstrationCaptureResult:
        self._save_idempotency(key, "demonstration.record", result)
        return result

    def _save_idempotency(self, key: str, operation: str, result: Any) -> None:
        with DbSession(self.engine) as database, database.begin():
            database.add(
                DemonstrationIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )

    def _profile_id_for_event(self, event: InteractionEvent) -> str | None:
        if self.profile_id_for_application is None or event.target is None:
            return None
        return self.profile_id_for_application(event.target.application)

    @staticmethod
    def _capability_for_event(event: Any) -> str:
        kind = event.kind.value
        if kind == "file.operation":
            return "filesystem.metadata"
        if kind == "control.invoked":
            return "windows.uia.invoke"
        if kind.startswith("keyboard") or kind.startswith("text_entry"):
            return "windows.input.metadata"
        return "windows.observation"

    @staticmethod
    def _normalize_shortcut(shortcut: str) -> str:
        return "+".join(part.strip().upper() for part in shortcut.split("+"))
