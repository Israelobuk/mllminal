"""Versioned contracts for explicit workflow demonstrations."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now
from mllminal.interaction.contracts import InteractionCaptureResult, InteractionEvent


class DemonstrationState(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    STOPPED = "stopped"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class VariableLabel(StrEnum):
    FIXED_VALUE = "fixed_value"
    ASK_EVERY_RUN = "ask_every_run"
    SAVED_CONTACT = "saved_contact"
    CURRENT_DATE = "current_date"
    SELECTED_FILE = "selected_file"
    DO_NOT_AUTOMATE = "do_not_automate"


class DemonstrationSession(Contract):
    id: str = Field(default_factory=new_id)
    label: str
    state: DemonstrationState = DemonstrationState.RECORDING
    timeout_seconds: int = Field(default=900, ge=1, le=3600)
    emergency_stop_shortcut: str = "CTRL+ALT+ESC"
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    step_count: int = Field(default=0, ge=0)
    candidate_id: str | None = None


class DemonstrationStatus(Contract):
    session: DemonstrationSession | None = None
    recording: bool
    visible_recording: bool
    visible_status: str


class DemonstrationStartRequest(Contract):
    label: str
    timeout_seconds: int = Field(default=900, ge=1, le=3600)
    emergency_stop_shortcut: str = "CTRL+ALT+ESC"


class DemonstrationVariableRequest(Contract):
    event_id: str
    label: VariableLabel
    field_name: str | None = None


class DemonstrationCaptureRequest(Contract):
    event: InteractionEvent
    normalized_file_operation: str | None = None
    application_transition: str | None = None
    text_entry_occurred: bool = False


class DemonstrationCaptureResult(Contract):
    accepted: bool
    reason: str
    interaction: InteractionCaptureResult | None = None
    session: DemonstrationSession | None = None


class DemonstrationStep(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    sequence: int = Field(ge=1)
    event: InteractionEvent
    normalized_file_operation: str | None = None
    application_transition: str | None = None
    text_entry_occurred: bool = False


class VariableAssignment(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    event_id: str
    label: VariableLabel
    field_name: str | None = None


class WorkflowCandidate(Contract):
    id: str = Field(default_factory=new_id)
    session_id: str
    title: str
    status: str = "draft"
    activated: bool = False
    step_ids: list[str] = Field(default_factory=list)
    variables: list[VariableAssignment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class DemonstrationStopResult(Contract):
    session: DemonstrationSession
    candidate: WorkflowCandidate
