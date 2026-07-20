"""Contracts for proposing workflows from repeated semantic interactions."""

from datetime import datetime

from pydantic import Field

from mllminal.contracts import Contract, new_id


class MiningRequest(Contract):
    lookback_minutes: int = Field(default=1440, ge=1, le=10080)
    minimum_occurrences: int = Field(default=2, ge=2, le=100)
    max_steps: int = Field(default=8, ge=2, le=12)


class MinedStep(Contract):
    application: str
    kind: str
    control_role: str | None = None
    control_name: str | None = None
    action_type: str | None = None
    shortcut: str | None = None
    navigation_key: str | None = None
    text_field_classification: str | None = None
    text_length_bucket: str | None = None


class WorkflowCandidate(Contract):
    id: str = Field(default_factory=new_id)
    application: str
    steps: list[MinedStep] = Field(min_length=2, max_length=12)
    occurrences: int = Field(ge=2)
    confidence: float = Field(ge=0.0, le=1.0)
    first_seen: datetime
    last_seen: datetime
    source_event_ids: list[str] = Field(default_factory=list, max_length=256)


class MiningResult(Contract):
    event_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    candidates: list[WorkflowCandidate] = Field(default_factory=list)
    metadata_only: bool = True
