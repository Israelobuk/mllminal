"""Versioned contracts for activity, application, and task modeling."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now


class ActivitySource(StrEnum):
    INTERACTION = "interaction"
    DEVICE = "device"


class BoundaryKind(StrEnum):
    TASK_STARTED = "task.started"
    TASK_ENDED = "task.ended"
    CONTEXT_SWITCH = "context.switch"
    IDLE_GAP = "idle.gap"


class ActivitySegment(Contract):
    id: str = Field(default_factory=new_id)
    source: ActivitySource
    application: str = "unknown"
    window: str | None = None
    started_at: datetime
    ended_at: datetime
    event_ids: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(default=0.0, ge=0.0)


class ApplicationSession(Contract):
    id: str = Field(default_factory=new_id)
    application: str
    started_at: datetime
    ended_at: datetime
    segment_ids: list[str] = Field(default_factory=list)
    event_count: int = Field(default=0, ge=0)


class TaskSession(Contract):
    id: str = Field(default_factory=new_id)
    title: str
    started_at: datetime
    ended_at: datetime
    application_session_ids: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)


class ContextSwitch(Contract):
    id: str = Field(default_factory=new_id)
    from_application: str
    to_application: str
    occurred_at: datetime
    reason: str = "application_changed"


class TaskBoundary(Contract):
    id: str = Field(default_factory=new_id)
    kind: BoundaryKind
    occurred_at: datetime
    application: str
    task_session_id: str | None = None
    reason: str


class ActivitySummary(Contract):
    id: str = Field(default_factory=new_id)
    period_started_at: datetime
    period_ended_at: datetime
    generated_at: datetime = Field(default_factory=utc_now)
    segment_count: int = Field(default=0, ge=0)
    application_session_count: int = Field(default=0, ge=0)
    task_session_count: int = Field(default=0, ge=0)
    context_switch_count: int = Field(default=0, ge=0)
    task_boundary_count: int = Field(default=0, ge=0)
    applications: list[str] = Field(default_factory=list)


class ActivityRefreshRequest(Contract):
    lookback_minutes: int = Field(default=1440, ge=1, le=10080)


class ActivityRefreshResult(Contract):
    summary: ActivitySummary
    segments: list[ActivitySegment] = Field(default_factory=list)
    application_sessions: list[ApplicationSession] = Field(default_factory=list)
    task_sessions: list[TaskSession] = Field(default_factory=list)
    context_switches: list[ContextSwitch] = Field(default_factory=list)
    task_boundaries: list[TaskBoundary] = Field(default_factory=list)
